"""Execute a split plan: the source runs its part, we run the rest.

Deliberately small. The interesting decisions all happened in the planner; this
just carries them out, and the differential test compares its output against
running the same tree entirely locally.
"""

from __future__ import annotations

from dataclasses import replace
from typing import Callable

import pandas as pd

from service_transformations.ir.nodes import Node, Scan
from service_transformations.ir.pandas_backend import execute
from service_transformations.ir.planner import ExecutionPlan

#: Runs a SQL string against the source and returns the rows.
SqlRunner = Callable[[str], pd.DataFrame]

_PUSHED_SOURCE = "__pushed__"


def execute_plan(
    plan: ExecutionPlan,
    *,
    run_sql: SqlRunner | None = None,
    frames: dict[str, pd.DataFrame] | None = None,
) -> pd.DataFrame:
    """Run a plan and return the result.

    ``run_sql`` executes the pushed query at the source. ``frames`` supplies the
    tables for anything that runs locally -- including the whole pipeline, when
    nothing could be pushed.
    """
    frames = frames or {}

    if plan.pushed is None:
        node = _rebuild_local(plan, base=None)
        return execute(node, frames)

    if plan.sql is not None:
        if run_sql is None:
            raise ValueError(
                "The plan pushes work to the source but no SQL runner was supplied."
            )
        result = run_sql(plan.sql)
    else:
        # A non-SQL surface that still ran part of the tree, or a test that
        # wants the pushed part evaluated locally.
        result = execute(plan.pushed, frames)

    if not plan.local:
        return result.reset_index(drop=True)

    node = _rebuild_local(plan, base=result)
    return execute(node, {**frames, _PUSHED_SOURCE: result})


def _rebuild_local(plan: ExecutionPlan, base: pd.DataFrame | None) -> Node:
    """Re-root the local nodes onto whatever the source returned.

    The local nodes still point at the original tree, so their `input` has to be
    replaced with a scan of the pushed result -- otherwise the local half would
    re-read the source and the pushed work would be done twice.
    """
    if base is None:
        # Nothing was pushed, so the local chain is already correctly rooted and
        # its last node IS the tree. It always contains at least the scan.
        if not plan.local:
            raise ValueError(
                "The plan pushes nothing and has no local nodes, so there is "
                "nothing to execute. This is a planner bug, not a pipeline one."
            )
        return plan.local[-1]

    columns = tuple((str(name), _pw_type_of(base[name])) for name in base.columns)
    node: Node = Scan(_PUSHED_SOURCE, columns)
    for step in plan.local:
        node = replace(step, input=node)  # type: ignore[arg-type]
    return node


def _pw_type_of(series: pd.Series):
    from shared_python.types import infer_pw_type

    return infer_pw_type(series)
