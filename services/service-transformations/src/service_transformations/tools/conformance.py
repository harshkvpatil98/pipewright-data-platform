"""The tool library's structural checks, as a function (X1).

`test_tool_library.py` holds every built-in tool to these by iterating the
registry; a plugin's tools are held to the same ones here, by the gateway
when it loads a plugin. A test checks that this function and the test suite
agree on every built-in tool.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from service_transformations.steps.context import ACTIVE_CONTEXT, StepContext
from service_transformations.tools.spec import ParamKind, ToolSpec

#: Tools whose answer for a missing value is a real answer, not a null.
ALLOWED_ON_NULL = frozenset({
    "null.fill_constant", "null.null_to_empty", "null.is_blank", "check.is_date",
    "check.is_number", "check.quarantine", "rows.filter",
})


@dataclass
class ToolReport:
    tool: str
    passed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.failures

    def expect(self, name: str, passed: bool, detail: str = "") -> None:
        if passed:
            self.passed.append(name)
        else:
            self.failures.append(f"{name}: {detail}" if detail else name)


def _frame(spec: ToolSpec) -> pd.DataFrame:
    return pd.DataFrame(list(spec.example.rows))


def _config(spec: ToolSpec, frame: pd.DataFrame) -> dict[str, Any]:
    column = spec.example.column or (list(frame.columns)[0] if len(frame.columns) else None)
    config = {"tool": spec.name, **spec.example.params}
    if column is not None:
        config["column"] = column
    return config


def _apply(spec: ToolSpec, frame: pd.DataFrame, config: dict[str, Any]) -> pd.DataFrame:
    from service_transformations.tools.apply import apply_tool
    from service_transformations.tools.catalogue.checks import CheckFailed

    other = pd.DataFrame(list(spec.example.other))
    token = ACTIVE_CONTEXT.set(StepContext(resolve_dataset=lambda _id: other.copy(),
                                           describe_dataset=lambda _id: "the example's other dataset"))
    try:
        return apply_tool(frame, config)[0]
    except CheckFailed:
        # A check stopping the run on empty data is its job; it still must not crash.
        return frame
    finally:
        ACTIVE_CONTEXT.reset(token)


def _normalise(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, bool):
        return value
    if isinstance(value, pd.Timestamp):
        return str(value)
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, int):
        return value
    return str(value)


def _observed(spec: ToolSpec, frame: pd.DataFrame, result: pd.DataFrame) -> list[Any] | None:
    target = spec.example.output
    if target == "__columns__":
        return [",".join(str(name) for name in result.columns)]
    if target is None:
        target = spec.example.column or list(frame.columns)[0]
    if target not in result.columns:
        return None
    return [None if pd.isna(v) else v for v in result[target].tolist()]


def check_tool(spec: ToolSpec) -> ToolReport:
    """Every structural check the library holds a tool to, without pytest."""
    from service_transformations import tools
    from service_transformations.tools.apply import build

    report = ToolReport(tool=spec.name)
    report.expect("has a title", bool(spec.title.strip()))
    report.expect("says what it does in a sentence", spec.summary.strip().endswith("."))
    report.expect("has a category", bool(spec.category.strip()))
    report.expect("has an example", bool(spec.example.rows))
    report.expect("is named category.name", "." in spec.name)
    for param in spec.params:
        report.expect(f"setting {param.key} has a label", bool(param.label.strip()))
        if param.kind is ParamKind.SELECT:
            report.expect(f"setting {param.key} has its choices",
                          bool(param.options) and (param.default is None or param.default in param.options))
    if not spec.example.rows:
        return report
    found = {result.name for result in tools.search(spec.title, limit=50)}
    report.expect("can be found by its own title", spec.name in found)
    if spec.needs:
        report.skipped.append(f"running it: it needs {spec.needs}")
        return report

    frame = _frame(spec)
    config = _config(spec, frame)

    def attempt(name: str, run):
        try:
            return run()
        except Exception as exc:  # noqa: BLE001 - a tool failing on a shape is the finding
            report.expect(name, False, f"{type(exc).__name__}: {exc}")
            return None

    result = attempt("runs on its example", lambda: _apply(spec, frame, config))
    if result is not None and spec.example.expect:
        observed = _observed(spec, frame, result)
        actual = None if observed is None else [_normalise(v) for v in observed]
        expected = [_normalise(v) for v in spec.example.expect]
        report.expect("its example gives what it says", actual == expected, f"documented {expected}, gave {actual}")

    empty = attempt("works on no rows", lambda: _apply(spec, frame.iloc[0:0], config))
    if empty is not None:
        report.expect("makes no rows from no rows",
                      spec.adds_rows or spec.describes or len(empty) == 0, f"{len(empty)} rows")

    blank = pd.DataFrame({column: [None] * len(frame) for column in frame.columns})
    nulls = attempt("works on empty values", lambda: _apply(spec, blank, config))
    if nulls is not None and spec.column_scoped and spec.example.output != "__columns__":
        target = spec.example.output or spec.example.column or list(frame.columns)[0]
        if target in nulls.columns and spec.name not in ALLOWED_ON_NULL and not spec.null_answer:
            values = [v for v in nulls[target].tolist() if not pd.isna(v)]
            report.expect("makes no values from empty ones", values == [], f"gave {values}")

    attempt("works on one row", lambda: _apply(spec, frame.iloc[:1], config))

    node = attempt("compiles to a node with columns", lambda: build(frame, config))
    if node is not None and result is not None and not spec.dynamic_columns:
        report.expect("says the columns it makes", list(node.schema()) == list(result.columns),
                      f"says {list(node.schema())}, makes {list(result.columns)}")
        try:
            from service_lineage.columns import build_pipeline_lineage
        except ImportError:
            report.skipped.append("lineage: service-lineage is not installed here")
        else:
            step = build_pipeline_lineage(base_columns=[str(c) for c in frame.columns],
                                          steps=[{"step_type": "tool", "config": config}]).steps[-1]
            report.expect("lineage agrees with the engine", step.output_columns == list(result.columns),
                          f"lineage says {step.output_columns}, the engine made {list(result.columns)}")
            if spec.column_scoped:
                report.expect("lineage records where its output came from",
                              bool(step.edges) and config["column"] in step.named_columns)
    return report
