"""Cells of different languages sharing one namespace.

The roadmap's shape, exactly: *a recipe cell's output is a dataframe the next
Python cell can read, and a Python cell's output is a dataset the next visual
cell can transform.* The namespace is what makes that true -- every cell reads
the frames earlier cells produced, and binds its own output under a name.

**Frames, not objects.** The shared thing is a `DataFrame` and only a
`DataFrame`. A Python cell's arbitrary objects stay in that cell, because a SQL
cell cannot read a Python class and a recipe cell cannot transform one; letting
them into the namespace would make "shared" mean "shared with one of the three".

**Execution is sequential and stops at the first failure.** A notebook is a
narrative. Running cell 7 against the state cell 4 would have produced, had it
not failed, produces numbers that were never true.

**It runs in the request, not on the worker.** The roadmap called for
out-of-process execution so a long cell could not hold an HTTP connection. What
is here instead is a bound on how long a cell *can* be: the sandbox stops a
Python cell after fifteen seconds, SQL carries a statement timeout, and
:data:`MAX_RUN_SECONDS` stops the whole notebook. A run that cannot exceed two
minutes does not need a queue to keep it off the request, and a queue would add
a job table, a worker node type and polling to every client for the same result.
Moving it to the worker becomes worth doing when notebooks are allowed to run
long, which is a decision about limits rather than about plumbing.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from sqlalchemy import Engine

from shared_python.errors import BadRequestError

from service_workbench import sandbox
from service_workbench.execute import run_script
from service_workbench.safety import SessionPolicy

CELL_KINDS = ("sql", "python", "recipe", "markdown")

#: A name a cell can bind its output to, and that another cell can then use.
_NAME = re.compile(r"^[a-z_][a-z0-9_]*$", re.IGNORECASE)

#: Frames held in one run. Beyond this the notebook is a pipeline, and pipelines
#: have a place to live that is not memory.
MAX_FRAMES = 50
MAX_FRAME_ROWS = 200_000

#: Wall clock for a whole notebook run.
#:
#: Per-cell limits alone are not enough: a twenty-cell notebook where every cell
#: sits just inside its own budget still holds an HTTP connection for minutes.
#: Bounding the run is what makes a synchronous notebook defensible -- see the
#: module docstring for why it is synchronous at all.
MAX_RUN_SECONDS = 120


@dataclass
class Cell:
    kind: str
    source: str = ""
    output_name: str | None = None
    config: dict[str, Any] = field(default_factory=dict)
    position: int = 0

    def __post_init__(self) -> None:
        if self.kind not in CELL_KINDS:
            raise BadRequestError(
                f"'{self.kind}' is not a kind of cell. Use one of: {', '.join(CELL_KINDS)}."
            )
        if self.output_name is not None and not _NAME.match(self.output_name):
            raise BadRequestError(
                f"'{self.output_name}' cannot be used as a name. Names start with a "
                "letter or underscore and contain letters, numbers and underscores."
            )


@dataclass
class CellResult:
    position: int
    kind: str
    ok: bool
    duration_ms: float = 0.0
    output_name: str | None = None
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, Any]] = field(default_factory=list)
    row_count: int = 0
    truncated: bool = False
    stdout: str = ""
    error: str = ""
    skipped: bool = False
    #: What the namespace held after this cell ran.
    bindings: dict[str, str] = field(default_factory=dict)


@dataclass
class NotebookResult:
    cells: list[CellResult] = field(default_factory=list)
    duration_ms: float = 0.0

    @property
    def failed(self) -> bool:
        return any(cell.error for cell in self.cells)


@dataclass
class Namespace:
    """The frames cells pass between each other."""

    frames: dict[str, pd.DataFrame] = field(default_factory=dict)

    def bind(self, name: str, frame: pd.DataFrame) -> None:
        if len(frame) > MAX_FRAME_ROWS:
            raise BadRequestError(
                f"'{name}' has {len(frame):,} rows; a notebook holds up to "
                f"{MAX_FRAME_ROWS:,}. Filter it, or save it as a dataset."
            )
        if name not in self.frames and len(self.frames) >= MAX_FRAMES:
            raise BadRequestError(
                f"A notebook holds up to {MAX_FRAMES} named results at once."
            )
        self.frames[name] = frame

    def describe(self) -> dict[str, str]:
        return {
            name: f"{len(frame)} rows x {len(frame.columns)} columns"
            for name, frame in self.frames.items()
        }


def run_notebook(
    cells: list[Cell],
    *,
    engine: Engine | None = None,
    policy: SessionPolicy | None = None,
    namespace: Namespace | None = None,
    row_preview: int = 100,
    budget_seconds: int = MAX_RUN_SECONDS,
) -> NotebookResult:
    """Run cells in order, threading one namespace through them."""
    space = namespace or Namespace()
    result = NotebookResult()
    started = time.perf_counter()
    stopped = False
    out_of_time = False

    for position, cell in enumerate(sorted(cells, key=lambda c: c.position)):
        if stopped:
            skipped = CellResult(position=position, kind=cell.kind, ok=False, skipped=True)
            if out_of_time:
                skipped.error = (
                    f"The notebook ran for more than {budget_seconds} seconds, so the "
                    "remaining cells were not started."
                )
            result.cells.append(skipped)
            continue

        outcome = _run_cell(cell, position, space, engine, policy, row_preview)
        outcome.bindings = space.describe()
        result.cells.append(outcome)
        if outcome.error:
            stopped = True
        elif time.perf_counter() - started > budget_seconds:
            # Checked after the cell, not before it: a budget that prevents any
            # work at all is a refusal, and it should read as one rather than as
            # a notebook that silently did nothing.
            stopped = True
            out_of_time = True

    result.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    return result


def _run_cell(
    cell: Cell,
    position: int,
    space: Namespace,
    engine: Engine | None,
    policy: SessionPolicy | None,
    row_preview: int,
) -> CellResult:
    started = time.perf_counter()
    outcome = CellResult(
        position=position, kind=cell.kind, ok=True, output_name=cell.output_name
    )

    try:
        if cell.kind == "markdown":
            pass
        elif cell.kind == "sql":
            _run_sql(cell, outcome, space, engine, policy, row_preview)
        elif cell.kind == "python":
            _run_python(cell, outcome, space, row_preview)
        else:
            _run_recipe(cell, outcome, space, row_preview)
    except BadRequestError as exc:
        outcome.ok = False
        outcome.error = str(exc)
    except Exception as exc:  # noqa: BLE001 - a cell may fail in any way
        outcome.ok = False
        outcome.error = f"{type(exc).__name__}: {exc}"

    outcome.duration_ms = round((time.perf_counter() - started) * 1000, 3)
    return outcome


def _run_sql(
    cell: Cell,
    outcome: CellResult,
    space: Namespace,
    engine: Engine | None,
    policy: SessionPolicy | None,
    row_preview: int,
) -> None:
    if engine is None:
        raise BadRequestError(
            "This notebook has no database connection, so SQL cells cannot run. "
            "Choose a connection, or use Python cells on the frames you have."
        )
    script = run_script(
        engine,
        cell.source,
        policy=policy or SessionPolicy(),
        parameters=cell.config.get("parameters") or {},
    )
    failing = next((s for s in script.statements if s.error), None)
    if failing is not None:
        raise BadRequestError(f"Statement {failing.index}: {failing.error}")

    # The last statement that returned rows is the cell's result: a script
    # ending in a SELECT after some SETs should show the SELECT.
    returning = [s for s in script.statements if s.columns]
    if not returning:
        outcome.stdout = _describe_writes(script)
        return

    last = returning[-1]
    frame = pd.DataFrame(last.rows, columns=last.columns)
    _publish(cell, outcome, space, frame, row_preview, truncated=last.truncated)


def _describe_writes(script: Any) -> str:
    affected = sum(s.rows_affected or 0 for s in script.statements)
    return f"{len(script.statements)} statement(s) ran; {affected} row(s) affected."


def _run_python(cell: Cell, outcome: CellResult, space: Namespace, row_preview: int) -> None:
    # The gate, not the mechanism: a deployment that cannot sandbox properly
    # refuses here with a reason rather than running the cell.
    sandbox.require_usable()
    result = sandbox.run(cell.source, dict(space.frames))
    outcome.stdout = result.stdout
    if not result.ok:
        raise BadRequestError(result.error)

    # Only frames cross the boundary. A Python cell's scalars and objects stay
    # in that cell, because nothing else in the notebook can read them.
    for name, frame in result.frames.items():
        space.bind(name, frame)

    chosen = cell.output_name or _last_new_frame(result.frames, space)
    if chosen and chosen in space.frames:
        outcome.output_name = chosen
        _preview(outcome, space.frames[chosen], row_preview)
    elif result.bindings and not outcome.stdout:
        outcome.stdout = "\n".join(
            f"{name} = {value}" for name, value in result.bindings.items()
        )


def _last_new_frame(frames: dict[str, pd.DataFrame], space: Namespace) -> str | None:
    return next(reversed(list(frames)), None) if frames else None


def _run_recipe(cell: Cell, outcome: CellResult, space: Namespace, row_preview: int) -> None:
    from service_transformations.executor import apply_transformation_steps
    from service_transformations.recipe_yaml import steps_from_yaml

    source_name = cell.config.get("input")
    if not source_name:
        raise BadRequestError("A recipe cell needs to say which result it transforms.")
    if source_name not in space.frames:
        available = ", ".join(space.frames) or "nothing yet"
        raise BadRequestError(
            f"'{source_name}' is not a result in this notebook. Available: {available}."
        )

    steps = cell.config.get("steps")
    if steps is None:
        # A recipe cell can hold YAML in its source, which is what makes a
        # notebook reviewable in a pull request alongside the code around it.
        steps = steps_from_yaml(cell.source) if cell.source.strip() else []
    if not isinstance(steps, list):
        raise BadRequestError("A recipe cell's steps must be a list.")

    frame, warnings = apply_transformation_steps(space.frames[source_name], steps)
    if warnings:
        outcome.stdout = "\n".join(warnings)
    _publish(cell, outcome, space, frame, row_preview)


def _publish(
    cell: Cell,
    outcome: CellResult,
    space: Namespace,
    frame: pd.DataFrame,
    row_preview: int,
    *,
    truncated: bool = False,
) -> None:
    if cell.output_name:
        space.bind(cell.output_name, frame)
        outcome.output_name = cell.output_name
    _preview(outcome, frame, row_preview)
    outcome.truncated = outcome.truncated or truncated


def _preview(outcome: CellResult, frame: pd.DataFrame, row_preview: int) -> None:
    from service_workbench.execute import _json_safe

    head = frame.head(row_preview)
    outcome.columns = [str(name) for name in frame.columns]
    outcome.rows = [
        {str(key): _json_safe(value) for key, value in row.items()}
        for row in head.to_dict(orient="records")
    ]
    outcome.row_count = len(frame)
    outcome.truncated = len(frame) > row_preview
