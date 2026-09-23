"""Shape rows at the source: Phase 12 pushdown, wired into extraction runs.

An extraction job may carry transformation steps. When it runs, the steps are
compiled to the relational IR over a scan of the job's query, the planner
splits the tree against the connection's surface, and:

* the pushable prefix is compiled to SQL in the connection's dialect and
  wrapped around the job's own query -- the source does that work and hands
  back fewer, narrower rows;
* everything after the first step the source cannot run happens here, on the
  rows that came back, through the same IR executor every other run uses.

The differential gate is `test_shaping.py`: for every job it plans, running
the pushed split must equal reading everything and running the steps locally.
Pushdown rewrites the user's computation, so equality is the bar, not speed.

Incremental loads read a *slice* of the source per run and merge it into what
was loaded before. Row-wise steps mean the same thing on a slice as on the
whole (a filter is a filter), but steps that change the grain -- aggregate,
pivot, unpivot, remove_duplicates, limit -- would compute per slice what the
person meant per table, so a job refuses them unless it is a full refresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import pandas as pd

from service_transformations.executor import apply_transformation_steps
from service_transformations.ir.from_steps import compile_pipeline
from service_transformations.ir.nodes import IRError, Scan
from service_transformations.ir.planner import ExecutionPlan, plan as build_plan
from service_transformations.ir.run_plan import execute_plan
from service_transformations.ir.surfaces import surface_for
from service_transformations.validators import validate_steps_json
from shared_python.errors import BadRequestError
from shared_python.types import UNKNOWN

#: The name the job's own query is bound to inside the IR.
SOURCE = "__extract__"

#: Steps that change the grain of the data and therefore cannot be applied to
#: an incremental slice without changing what the job means.
GRAIN_CHANGING: frozenset[str] = frozenset(
    {"aggregate", "pivot", "unpivot", "remove_duplicates", "limit_rows", "sort_rows"}
)

SqlReader = Callable[[str], pd.DataFrame]


@dataclass
class ShapingOutcome:
    frame: pd.DataFrame
    warnings: list[str] = field(default_factory=list)
    #: What the source ran and what ran here, for the run record and the UI.
    plan: dict[str, Any] | None = None


def validate_job_steps(steps: Any, *, load_mode: str) -> list[dict[str, Any]]:
    """Normalise and check a job's steps at save time, so a run never discovers
    a broken recipe. Returns plain `{step_type, config}` dicts."""
    if steps is None:
        return []
    if not isinstance(steps, list):
        raise BadRequestError("steps must be a list of transformation steps.")
    validated = validate_steps_json(steps)
    if load_mode != "full_refresh":
        offending = [step.step_type for step in validated if step.step_type in GRAIN_CHANGING]
        if offending:
            raise BadRequestError(
                f"{', '.join(sorted(set(offending)))} cannot be applied to an incremental load: "
                "each run reads only a slice of the source, so a step that changes the grain "
                "would compute per slice what you meant per table. Use full_refresh, or keep "
                "row-wise steps (filter, select, rename, cast, derive) here and aggregate in a pipeline."
            )
    return [{"step_type": step.step_type, "config": dict(step.config or {})} for step in validated]


def plan_job_steps(
    steps: list[dict[str, Any]], *, connector_type: str, columns: list[str] | None = None
) -> ExecutionPlan:
    """Split the steps against the connection's surface. Column types are
    unknown until the source answers, which is fine for planning: the planner
    decides by node shape and the dialect decides by expression."""
    scan_columns = tuple((name, UNKNOWN) for name in (columns or [])) or (("*", UNKNOWN),)
    tree = compile_pipeline(Scan(SOURCE, scan_columns), [
        {"type": step["step_type"], "config": step.get("config") or {}} for step in steps
    ])
    return build_plan(tree, connector_type)


def wrap_pushed_sql(pushed_sql: str, base_query: str, *, dialect_quote: Callable[[str], str]) -> str:
    """The compiled prefix reads `FROM "__extract__"`; the job's own query
    stands in for that table as a subquery. String substitution rather than a
    new node type because the compiler quotes the scan name with the dialect's
    own quoting, so the token is exact and unique."""
    token = f"FROM {dialect_quote(SOURCE)}"
    if token not in pushed_sql:
        raise IRError("The compiled SQL does not read from the extraction source.")
    return pushed_sql.replace(token, f"FROM ({base_query}) AS {dialect_quote(SOURCE)}", 1)


def shape_rows(
    *,
    steps: list[dict[str, Any]],
    connector_type: str,
    base_query: str,
    read_sql: SqlReader,
    read_all: Callable[[], pd.DataFrame],
) -> ShapingOutcome:
    """Run the job's steps, pushing what the source can run.

    `read_sql(sql)` reads an arbitrary statement from the source; `read_all()`
    reads the job's plain query. When nothing can be pushed, or the source
    refuses the pushed statement, everything runs here on the plain read --
    and the plan says so. A refusal is never silent and never a failed run:
    the source's error becomes a warning and the local path produces the same
    answer the pushed one would have.
    """
    if not steps:
        return ShapingOutcome(frame=read_all())

    warnings: list[str] = []
    columns: list[str] | None = None
    if surface_for(connector_type).is_sql:
        # The IR needs the source's column names to compile a filter or a
        # projection, and the job's query only reveals them when it runs. A
        # zero-row probe asks the source for the shape without the rows.
        try:
            columns = [str(name) for name in read_sql(f"SELECT * FROM ({base_query}) AS __probe__ WHERE 1 = 0").columns]
        except Exception as exc:  # noqa: BLE001 - the local path is the fallback, stated
            frame, step_warnings = apply_transformation_steps(read_all(), steps)
            return ShapingOutcome(
                frame=frame,
                warnings=[
                    f"The source refused the pushed statement ({str(exc)[:200]}); every step ran here instead.",
                    *step_warnings,
                ],
                plan={"surface": connector_type, "pushed_steps": 0, "local_steps": len(steps),
                      "sql": None, "placements": [],
                      "note": "source refused the column probe; ran locally"},
            )
    try:
        execution = plan_job_steps(steps, connector_type=connector_type, columns=columns)
    except (IRError, ValueError, KeyError) as exc:
        # A recipe the IR cannot describe still runs -- locally, through the
        # same executor the Studio uses -- with the reason recorded.
        frame, step_warnings = apply_transformation_steps(read_all(), steps)
        return ShapingOutcome(
            frame=frame,
            warnings=[*step_warnings, f"Shaping ran locally: the planner could not describe it ({exc})."],
            plan={"surface": connector_type, "pushed_steps": 0, "local_steps": len(steps),
                  "sql": None, "placements": [], "note": f"planner could not describe the recipe: {exc}"},
        )

    plan_dict = _plan_dict(execution, connector_type)

    if execution.pushed is not None and execution.sql and execution.surface and execution.surface.dialect:
        from service_transformations.ir.sql_backend import get_dialect

        dialect_quote = get_dialect(execution.surface.dialect).quote
        wrapped = wrap_pushed_sql(execution.sql, base_query, dialect_quote=dialect_quote)
        plan_dict["sql"] = wrapped
        try:
            pushed_result = read_sql(wrapped)
        except Exception as exc:  # noqa: BLE001 - the local path is the fallback, stated
            warnings.append(
                f"The source refused the pushed statement ({str(exc)[:200]}); every step ran here instead."
            )
            frame, step_warnings = apply_transformation_steps(read_all(), steps)
            plan_dict.update({"pushed_steps": 0, "local_steps": len(steps),
                              "note": "source refused the pushed statement; ran locally"})
            return ShapingOutcome(frame=frame, warnings=[*warnings, *step_warnings], plan=plan_dict)
        frame = execute_plan(execution, run_sql=lambda _sql: pushed_result, frames={})
        return ShapingOutcome(frame=frame.reset_index(drop=True), warnings=warnings, plan=plan_dict)

    # Nothing pushed: read it all and run the steps here, through the one executor.
    frame, step_warnings = apply_transformation_steps(read_all(), steps)
    return ShapingOutcome(frame=frame, warnings=step_warnings, plan=plan_dict)


def _plan_dict(execution: ExecutionPlan, connector_type: str) -> dict[str, Any]:
    return {
        "surface": execution.surface.name if execution.surface else connector_type,
        # A scan is a read, not a step -- the planner counts it among its pushed
        # decisions; people count steps.
        "pushed_steps": sum(
            1 for d in execution.decisions if d.pushed and not d.node.startswith("Scan(")
        ),
        "local_steps": execution.local_count,
        "sql": execution.sql,
        "placements": [
            {"node": d.node, "pushed": d.pushed, "reason": d.reason} for d in execution.decisions
        ],
        "note": execution.surface.note if execution.surface else "",
        "rewrites": [str(applied) for applied in execution.rewrites],
    }
