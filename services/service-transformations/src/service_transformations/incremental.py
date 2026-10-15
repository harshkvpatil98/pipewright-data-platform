"""Recomputing only what changed (D2, O7).

A recipe re-run after 1,000 rows were appended to 1,000,000 used to compute
all 1,001,000 again. A recipe can now say how its runs compute
(`TransformationPipeline.incremental_mode`):

- **append**: when the input gained rows at the end since the last run
  (checked, not assumed: the rows the last run read must still be there,
  unchanged, first) and every step works row by row, only the new rows are
  computed and added to what the last run made.
- **partition**: with a column chosen, only the partitions whose rows changed
  are computed again, and the rest are taken from what the last run made,
  for a recipe whose every step keeps partitions apart (works row by row, or
  groups or removes repeats with the column among its keys). Rows come back
  in a different order than a full run gives; a recipe that orders its rows
  runs in full.

Anything else runs in full, and the run's log says which step, or which
change to the input, stopped it. What "works row by row" means is read off
the IR each step compiles to, not a list kept by hand: projections and
filters do; ordering, limiting, grouping, removing repeats, reshaping, and
reading the clock do not. `tests/test_incremental.py` holds every case to
the one rule that matters: the same rows and values as a full run.
"""

from __future__ import annotations

import hashlib
import io
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from pandas.api.types import is_bool_dtype, is_datetime64_any_dtype, is_numeric_dtype
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.words import count_of, listing

from service_transformations.execution_context import CLOCK_FUNCTIONS, SEMANTIC_VERSION, VersionPin, context_from_run
from service_transformations.ir.expressions import Call, Case, Cast, Column, Expr
from service_transformations.ir.from_steps import compile_step
from service_transformations.ir.nodes import (
    Aggregate,
    Distinct,
    Extension,
    Filter,
    Join,
    Limit,
    Node,
    Project,
    Scan,
    SetOp,
    Sort,
    Window,
)

MODES = ("full", "append", "partition")


@dataclass
class Previous:
    """What the last successful run read and made."""

    run_id: Any
    steps: list[dict[str, Any]]
    base_pin: VersionPin
    step_pins: list[VersionPin]
    input_path: str
    input_type: str
    input_spec: dict[str, Any] | None
    output_path: str
    output_schema: dict[str, Any] | None
    #: Each input column's kind as the last run read it (`column_kinds`); None for a run before they were kept.
    input_kinds: dict[str, str] | None = None


@dataclass
class Decision:
    mode: str
    #: Why a run that could have been incremental runs in full; empty otherwise.
    reason: str = ""
    previous: Previous | None = None
    partition_column: str | None = None


@dataclass
class Outcome:
    csv_bytes: bytes
    frame: pd.DataFrame
    #: What the run's log says it did.
    message: str
    details: dict[str, Any] = field(default_factory=dict)


# ------------------------------------------------------------ the last run


def _previous(db: Session, pipeline) -> Previous | None:
    from service_datasets.models import DatasetVersion
    from service_pipeline_runs.models import PipelineRun

    run = db.scalar(
        select(PipelineRun)
        .where(PipelineRun.pipeline_id == pipeline.id, PipelineRun.run_type == "dataset_transformation",
               PipelineRun.status == "succeeded")
        .order_by(PipelineRun.completed_at.desc(), PipelineRun.created_at.desc())
        .limit(1)
    )
    context = context_from_run(run.summary_json) if run is not None else None
    if context is None or context.semantic_version != SEMANTIC_VERSION:
        return None
    base = next((pin for pin in context.inputs if pin.role == "base"), None)
    output = next((pin for pin in context.outputs if pin.role == "output"), None)
    if base is None or output is None or base.version_number is None or output.version_number is None:
        return None

    def version(dataset_id: str, number: int):
        found = db.scalar(select(DatasetVersion).where(
            DatasetVersion.dataset_id == _uuid(dataset_id), DatasetVersion.version_number == number))
        return None if found is None or getattr(found, "retention_state", None) == "pruned" else found

    read, made = version(base.dataset_id, base.version_number), version(output.dataset_id, output.version_number)
    if read is None or made is None:
        return None
    return Previous(
        run_id=run.id, steps=list(context.steps), base_pin=base,
        step_pins=[pin for pin in context.inputs if pin.role == "step"],
        input_path=read.file_path, input_type=read.file_type or "csv", input_spec=read.ingest_spec_json,
        output_path=made.file_path, output_schema=made.schema_json,
        input_kinds=(run.summary_json or {}).get("input_kinds"),
    )


def _uuid(value: str):
    import uuid

    return uuid.UUID(str(value))


# --------------------------------------------------- what the steps allow


def _expressions(node: Node) -> list[Expr]:
    if isinstance(node, Project):
        return [expr for _, expr in node.projections]
    if isinstance(node, Filter):
        return [node.predicate]
    if isinstance(node, Aggregate):
        return [expr for _, expr in (*node.group_by, *node.aggregates)]
    if isinstance(node, Sort):
        return [key.expr for key in node.keys]
    if isinstance(node, Join) and node.on is not None:
        return [node.on]
    if isinstance(node, Window):
        return [key.expr for key in node.order_by] + [arg for _, call in node.functions for arg in call.args]
    return []


def _reads_clock(expr: Expr) -> bool:
    if isinstance(expr, Call):
        return expr.name in CLOCK_FUNCTIONS or any(_reads_clock(arg) for arg in expr.args)
    if isinstance(expr, Case):
        return any(_reads_clock(c) or _reads_clock(v) for c, v in expr.branches) or (
            expr.default is not None and _reads_clock(expr.default))
    if isinstance(expr, Cast):
        return _reads_clock(expr.value)
    return False


def _own_nodes(after: Node, before: Node) -> list[Node]:
    """The nodes a step added on top of `before`."""
    found: list[Node] = []
    pending = [after]
    while pending:
        node = pending.pop()
        if node is before:
            continue
        found.append(node)
        pending.extend(node.children())
    return found


_LABELS = {
    "sort_rows": "Sort rows", "limit_rows": "Keep the first rows", "remove_duplicates": "Remove duplicates",
    "aggregate": "Group and total", "pivot": "Pivot", "unpivot": "Unpivot", "union_datasets": "Add rows from a dataset",
    "join_datasets": "Join another dataset", "fill_nulls": "Fill empty values",
}


def _step_name(index: int, step_type: str) -> str:
    label = _LABELS.get(step_type, step_type.replace("_", " ").capitalize())
    return f"step {index} ({label})"


def why_not(steps: list[dict[str, Any]], scan: Scan, mode: str, partition_column: str | None,
            unchanged_datasets: set[str]) -> str | None:
    """Why these steps cannot run incrementally in `mode`, in words; None when they can."""
    node: Node = scan
    p = partition_column
    for index, step in enumerate(steps, start=1):
        step_type, config = step.get("step_type") or step.get("type"), dict(step.get("config") or {})
        name = _step_name(index, str(step_type))
        try:
            after = compile_step(node, str(step_type), config)
        except Exception:  # noqa: BLE001 - a step the IR cannot describe is not known to be row by row
            return f"{name} could not be described, so it is not known to work row by row"
        for part in _own_nodes(after, node):
            reason = _part_reason(part, name, mode, p, config, unchanged_datasets)
            if reason:
                return reason
        node = after
    if mode == "partition" and p not in node.schema():
        return f"the recipe's result has no {p} column to divide by"
    return None


def _part_reason(part: Node, name: str, mode: str, p: str | None, config: dict[str, Any],
                 unchanged_datasets: set[str]) -> str | None:
    if any(_reads_clock(expr) for expr in _expressions(part)):
        return f"{name} reads the clock, so rows made at the last run would come out differently now"
    if isinstance(part, Filter):
        return None
    if isinstance(part, Project):
        if mode == "partition":
            projected = dict(part.projections)
            if p not in projected:
                return f"{name} drops {p}, the column that divides the data"
            if projected[p] != Column(p):
                return f"{name} changes {p}, the column that divides the data"
        return None
    if isinstance(part, Sort):
        return f"{name} puts every row in order, so new rows belong among the old"
    if isinstance(part, Limit):
        return f"{name} keeps a number of rows that depends on all of them"
    if isinstance(part, Aggregate):
        if mode == "partition" and (p, Column(p)) in part.group_by:
            return None
        return (f"{name} groups rows across partitions" if mode == "partition"
                else f"{name} groups rows, so a row added now can change a group made before")
    if isinstance(part, Distinct):
        if mode == "partition" and (not part.subset or p in part.subset):
            return None
        return f"{name} removes repeated rows across all of them"
    if isinstance(part, (SetOp,)):
        return f"{name} adds another dataset's rows to all of them"
    if isinstance(part, Window):
        if mode == "partition" and p in part.partition_by:
            return None
        return (f"{name} looks across partitions" if mode == "partition"
                else f"{name} looks at other rows, so a row added now can change the answer for one made before")
    if isinstance(part, Extension):
        if part.name in ("filter_rows", "derive_column", "split_column"):
            if mode == "partition" and part.name != "filter_rows":
                target = config.get("target_column") if part.name == "derive_column" else config.get("column")
                dropped = part.name == "split_column" and config.get("drop_original") and config.get("column") == p
                if target == p or dropped:
                    return f"{name} changes {p}, the column that divides the data"
            return None
        if part.name == "join_datasets":
            other = str(config.get("right_dataset_id") or "")
            how = str(config.get("how") or "inner")
            if how not in ("inner", "left", "semi", "anti", "cross"):
                return f"{name} keeps rows of the other dataset that match nothing, so it needs all of them"
            if other not in unchanged_datasets:
                return f"{name} joins a dataset that changed since the last run"
            return None
        if part.name == "union_datasets":
            return f"{name} adds another dataset's rows to all of them"
        from service_transformations.tools import TOOLS

        spec = TOOLS.get(part.name)
        if spec is not None and spec.calls_out:
            return f"{name} asks a web service, whose answers can change between runs"
        if spec is not None and spec.row_wise:
            # A tool that works on each row by itself (a lookup, an as-of join): E1.
            if spec.reads_dataset and str(config.get("right_dataset_id") or "") not in unchanged_datasets:
                return f"{name} reads a dataset that changed since the last run"
            return None
        if part.name == "fill_nulls":
            return f"{name} fills empty values from other rows"
        return f"{name} reshapes all the rows together"
    if isinstance(part, Join):
        return f"{name} joins rows in a way that needs all of them"
    return f"{name} is not known to work row by row"


# ----------------------------------------------------------- the decision


def decide(db: Session, *, pipeline, steps: list[dict[str, Any]], scan: Scan, base_pin: VersionPin,
           step_heads: dict[str, VersionPin]) -> Decision:
    """Whether this run can be incremental, from the recipe and its last run alone."""
    mode = getattr(pipeline, "incremental_mode", None) or "full"
    if mode not in ("append", "partition"):
        return Decision("full")
    previous = _previous(db, pipeline)
    if previous is None:
        return Decision("full", "there is no earlier run of this recipe to build on", None)
    if _canonical(previous.steps) != _canonical(steps):
        return Decision("full", "the recipe's steps changed since the last run")
    if previous.base_pin.dataset_id != base_pin.dataset_id:
        return Decision("full", "the recipe reads a different dataset than at the last run")
    unchanged = {pin.dataset_id for pin in previous.step_pins
                 if (head := step_heads.get(pin.dataset_id)) is not None and head.version_number == pin.version_number}
    partition = pipeline.partition_column if mode == "partition" else None
    if mode == "partition" and partition not in scan.schema():
        return Decision("full", f"the input has no {partition} column to divide by")
    reason = why_not(steps, scan, mode, partition, unchanged)
    if reason:
        return Decision("full", reason)
    return Decision(mode, "", previous, partition)


def _canonical(steps: list[dict[str, Any]]) -> list[tuple[str, str]]:
    import json

    return [(str(step.get("step_type") or step.get("type")),
             json.dumps(step.get("config") or {}, sort_keys=True, default=str)) for step in steps]


# ---------------------------------------------------------------- running


def _read(storage, path: str, file_type: str, spec: dict[str, Any] | None) -> pd.DataFrame:
    from service_ingestion.read_copy import frame_of

    return frame_of(storage, path, storage.read_bytes(path), file_type=file_type, spec=spec)


def _same_rows(a: pd.DataFrame, b: pd.DataFrame) -> bool:
    """Whether two frames hold the same values, row for row (5 and 5.0 are the same number)."""
    if list(a.columns) != list(b.columns) or len(a) != len(b):
        return False
    a, b = a.reset_index(drop=True), b.reset_index(drop=True)
    for name in a.columns:
        x, y = a[name], b[name]
        if x.dtype == y.dtype:
            if not np.array_equal(pd.util.hash_pandas_object(x, index=False).to_numpy(),
                                  pd.util.hash_pandas_object(y, index=False).to_numpy()):
                return False
        elif is_numeric_dtype(x) and is_numeric_dtype(y) and not is_bool_dtype(x) and not is_bool_dtype(y):
            if not np.allclose(x.to_numpy(dtype="float64"), y.to_numpy(dtype="float64"), equal_nan=True):
                return False
        elif not x.astype(str).where(x.notna(), "").equals(y.astype(str).where(y.notna(), "")):
            return False
    return True


def _text(csv_bytes: bytes) -> pd.DataFrame:
    """A CSV exactly as written: every value as text, an empty cell as an empty string."""
    return pd.read_csv(io.BytesIO(csv_bytes), dtype=str, keep_default_na=False, na_filter=False)


def _typed(text: pd.DataFrame, schema: dict[str, Any] | None) -> pd.DataFrame:
    """The kept rows of the last result, typed as that result's columns were when it was made."""
    kinds = {str(c.get("name")): str(c.get("inferred_type") or "") for c in (schema or {}).get("columns") or []
             if isinstance(c, dict)}
    out = pd.DataFrame(index=text.index)
    for name in text.columns:
        values = text[name].replace("", np.nan)
        kind = kinds.get(str(name), "")
        if kind in ("int", "float", "decimal"):
            out[name] = pd.to_numeric(values, errors="coerce")
        elif kind == "bool":
            out[name] = values.map({"True": True, "False": False})
        elif kind == "datetime":
            out[name] = _dates(values)
        elif kind == "date":
            out[name] = _dates(values).dt.date
        else:
            out[name] = values.astype(object).where(values.notna(), None)
    return out


def _dates(values: pd.Series) -> pd.Series:
    """Dates as this platform writes them (ISO 8601), read fast; anything else read slowly."""
    try:
        return pd.to_datetime(values, errors="raise", format="ISO8601")
    except (ValueError, TypeError):
        return pd.to_datetime(values, errors="coerce", format="mixed")


def _csv_rows(frame: pd.DataFrame) -> bytes:
    buffer = io.StringIO()
    frame.to_csv(buffer, index=False, header=False)
    return buffer.getvalue().encode("utf-8")


def _combine(kept_text: pd.DataFrame, fresh: pd.DataFrame, previous: Previous) -> pd.DataFrame:
    kept = _typed(kept_text, previous.output_schema)
    if fresh.empty:
        return kept.reset_index(drop=True)
    if kept.empty:
        return fresh.reset_index(drop=True)
    return pd.concat([kept, fresh], ignore_index=True)


@dataclass
class Input:
    """The input as the run would read it, without reading it until asked."""

    raw: Callable[[], bytes]
    whole: Callable[[], pd.DataFrame]
    parse: Callable[[bytes], pd.DataFrame]
    file_type: str
    spec: dict[str, Any] | None


def column_kinds(frame: pd.DataFrame, *, sample: int | None = 1_000) -> dict[str, str]:
    """What each column holds, as one word: from its dtype, or the Python types of its first
    `sample` values (all of them when None). Kept with every run of an incremental recipe, so
    the next can tell whether rows read alone come out as the rows before them did."""
    from datetime import date, datetime

    kinds: dict[str, str] = {}
    for name in frame.columns:
        series = frame[name]
        if is_bool_dtype(series):
            kinds[str(name)] = "bool"
        elif is_numeric_dtype(series):
            kinds[str(name)] = "int" if pd.api.types.is_integer_dtype(series) else "float"
        elif is_datetime64_any_dtype(series):
            kinds[str(name)] = "datetime"
        else:
            values = series.dropna()
            values = values if sample is None else values.head(sample)
            types = {type(value) for value in values}
            if not types:
                kinds[str(name)] = "empty"
            elif types <= {bool}:
                kinds[str(name)] = "bool"
            elif types <= {int}:
                kinds[str(name)] = "int"
            elif types <= {int, float}:
                kinds[str(name)] = "float"
            elif types <= {str}:
                kinds[str(name)] = "string"
            elif types <= {date}:
                kinds[str(name)] = "date"
            elif types <= {datetime, pd.Timestamp, date}:
                kinds[str(name)] = "datetime"
            else:
                kinds[str(name)] = "mixed"
    return kinds


def _added_rows(previous: Previous, now: Input, storage) -> tuple[pd.DataFrame, str, dict[str, str] | None] | str:
    """The rows added at the end since the last run, checked; or why there is no such thing."""
    before_bytes = storage.read_bytes(previous.input_path)
    now_bytes = now.raw()
    if (previous.input_type == now.file_type == "csv" and previous.input_spec == now.spec
            and before_bytes.endswith(b"\n") and now_bytes.startswith(before_bytes)):
        # The file the last run read is, byte for byte, the start of this one: only the
        # rest needs reading, under the header they share.
        tail = now_bytes[len(before_bytes):]
        header = before_bytes[: before_bytes.find(b"\n") + 1]
        if not tail.strip():
            return pd.DataFrame(), "none", previous.input_kinds
        added = now.parse(header + tail)
        # Read alone, a few rows can come out as another type than the rows before them
        # did ("02134" as a number): then the whole file is read after all.
        known = previous.input_kinds
        kinds = column_kinds(added, sample=None)
        # Compared as a mapping: PostgreSQL keeps JSON keys in an order of its own, and the
        # shared header has already settled the columns' order.
        if known is not None and set(map(str, added.columns)) == set(known) and all(
                kind == "empty" or known.get(name) == kind for name, kind in kinds.items()):
            return added, "the new rows only", known
    before = _read(storage, previous.input_path, previous.input_type, previous.input_spec)
    whole = now.whole()
    if list(before.columns) != list(whole.columns):
        return "the input's columns changed since the last run"
    if len(whole) < len(before):
        return "the input has fewer rows than at the last run, so some were removed"
    if not _same_rows(before, whole.iloc[: len(before)]):
        return "rows the last run read have changed, not only new rows added after them"
    return whole.iloc[len(before):].reset_index(drop=True), "the whole input, to check it", column_kinds(whole)


def run_append(decision: Decision, *, now: Input, steps: list[Any], storage,
               apply: Callable[[pd.DataFrame, Any], tuple[pd.DataFrame, list[str]]]) -> Outcome | str:
    """The new rows' result added to the last; or why it has to run in full after all."""
    previous = decision.previous
    assert previous is not None
    found = _added_rows(previous, now, storage)
    if isinstance(found, str):
        return found
    added, read, input_kinds = found
    made = storage.read_bytes(previous.output_path)
    try:
        fresh, warnings = _apply_all(added, steps, apply)
    except _SubsetRefused as refused:
        return str(refused)
    header = list(pd.read_csv(io.BytesIO(made), nrows=0).columns)
    if len(fresh.columns) and header != [str(c) for c in fresh.columns]:
        return "the result's columns would differ from the last run's"
    csv_bytes = made + (_csv_rows(fresh) if len(fresh) else b"")
    frame = _combine(_text(made), fresh, previous)
    message = (f"Computed only the {count_of(len(added), 'row')} added since the last run, and kept the "
               f"{count_of(len(frame) - len(fresh), 'row')} it made." if len(added)
               else "The input has not changed since the last run, so its result was kept as it was.")
    return Outcome(csv_bytes, frame, message,
                   {"mode": "append", "rows_computed": len(added), "rows_kept": len(frame) - len(fresh),
                    "read": read, "warnings": warnings, "input_kinds": input_kinds})


class _SubsetRefused(Exception):
    """A step's checks refused the rows to compute on their own (a column of only empty values,
    say), though they might pass over all the rows; a full run decides."""


def _apply_all(frame: pd.DataFrame, steps: list[Any], apply) -> tuple[pd.DataFrame, list[str]]:
    from shared_python.errors import BadRequestError
    from shared_python.memory import check_frame

    if frame.empty:
        return pd.DataFrame(), []
    warnings: list[str] = []
    for index, step in enumerate(steps, start=1):
        try:
            frame, step_warnings = apply(frame, step)
        except BadRequestError as exc:
            raise _SubsetRefused(f"step {index}'s checks refused the changed rows on their own ({exc.detail})") from exc
        check_frame(frame, where=f"Step {index} ({step.step_type.replace('_', ' ')})")
        warnings.extend(step_warnings)
    return frame, warnings


def _key(value: Any) -> Any:
    """A partition value as something to compare: an empty one as None, numbers as numbers."""
    if value is None or (not isinstance(value, (list, dict)) and pd.isna(value)):
        return None
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    if isinstance(value, pd.Timestamp):
        return value.to_pydatetime()
    if isinstance(value, str) and value == "":
        return None
    return value


def _partition_digests(frame: pd.DataFrame, column: str) -> dict[Any, str]:
    row_hashes = pd.util.hash_pandas_object(frame, index=False).to_numpy()
    keys = [_key(value) for value in frame[column].tolist()]
    digests: dict[Any, Any] = {}
    for key, row in zip(keys, row_hashes):
        digests.setdefault(key, hashlib.sha256()).update(int(row).to_bytes(8, "little"))
    return {key: digest.hexdigest() for key, digest in digests.items()}


def _output_keys(text: pd.Series, like: pd.Series) -> list[Any]:
    """The last result's partition values, read as the input's column holds them."""
    values = text.replace("", np.nan)
    if is_bool_dtype(like):
        parsed = values.map({"True": True, "False": False})
    elif is_numeric_dtype(like):
        parsed = pd.to_numeric(values, errors="coerce")
    elif is_datetime64_any_dtype(like):
        parsed = pd.to_datetime(values, errors="coerce", format="mixed")
    else:
        sample = like.dropna()
        if len(sample) and all(type(v).__name__ == "date" for v in sample.head(100)):
            parsed = pd.to_datetime(values, errors="coerce", format="mixed").dt.date
        else:
            parsed = values
    return [_key(value) for value in parsed.tolist()]


def run_partitions(decision: Decision, *, now: Input, steps: list[Any], storage,
                   apply: Callable[[pd.DataFrame, Any], tuple[pd.DataFrame, list[str]]]) -> Outcome | str:
    """The changed partitions computed again, the rest kept; or why it has to run in full after all."""
    previous, column = decision.previous, decision.partition_column
    assert previous is not None and column is not None
    before = _read(storage, previous.input_path, previous.input_type, previous.input_spec)
    now = now.whole()
    if list(before.columns) != list(now.columns):
        return "the input's columns changed since the last run"
    old, new = _partition_digests(before, column), _partition_digests(now, column)
    changed = {key for key in old.keys() | new.keys() if old.get(key) != new.get(key)}
    made = storage.read_bytes(previous.output_path)
    kept_text = _text(made)
    if column not in kept_text.columns:
        return f"the last run's result has no {column} column"
    in_changed = [_key(value) in changed for value in now[column].tolist()]
    try:
        fresh, warnings = _apply_all(now[in_changed].reset_index(drop=True), steps, apply)
    except _SubsetRefused as refused:
        return str(refused)
    if len(fresh.columns) and list(kept_text.columns) != [str(c) for c in fresh.columns]:
        return "the result's columns would differ from the last run's"
    output_keys = _output_keys(kept_text[column], now[column])
    kept_text = kept_text[[key not in changed for key in output_keys]]
    buffer = io.StringIO()
    kept_text.to_csv(buffer, index=False)
    csv_bytes = buffer.getvalue().encode("utf-8") + (_csv_rows(fresh) if len(fresh) else b"")
    frame = _combine(kept_text, fresh, previous)
    shown = sorted(("(empty)" if key is None else str(key)) for key in changed)
    message = (
        f"Computed again only the {count_of(len(changed), 'partition')} of {column} whose rows changed "
        f"({listing(shown, limit=5)}), of {count_of(len(old.keys() | new.keys()), 'partition')}, and kept the rest."
        if changed else "No partition's rows changed since the last run, so its result was kept as it was."
    )
    return Outcome(csv_bytes, frame, message,
                   {"mode": "partition", "partitions_computed": len(changed), "rows_computed": int(sum(in_changed)),
                    "rows_kept": int(len(kept_text)), "warnings": warnings, "input_kinds": column_kinds(now)})
