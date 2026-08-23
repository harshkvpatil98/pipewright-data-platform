"""Derive a pipeline's output columns from the IR rather than per step.

``columns.py`` symbolically executes each of the twenty step types, which works
but means every new step needs an entry there before lineage knows about it --
and a step whose entry is missing fails a test rather than being handled.

Walking the IR instead gets that for free: every step already compiles to the
algebra, and every node already reports the schema it produces. A step added
later is covered the moment it has an IR mapping.

The two are kept side by side and proven equal by ``test_matches_ir.py``. This
is the derived answer; ``columns.py`` remains the one the API serves until the
cutover is made deliberately.
"""

from __future__ import annotations

from typing import Any

from shared_python.types import PWType, UNKNOWN
from service_transformations.ir.from_steps import compile_pipeline
from service_transformations.ir.nodes import IRError, Node, Scan


def _scan_for(base_columns: list[str]) -> Scan:
    # Lineage cares about names and order, not types; UNKNOWN is the honest
    # placeholder when the caller has not told us what the columns hold.
    return Scan("__source__", tuple((name, UNKNOWN) for name in base_columns))


def output_columns(
    base_columns: list[str],
    steps: list[dict[str, Any]],
    *,
    column_types: dict[str, PWType] | None = None,
) -> list[str]:
    """The columns a pipeline produces, read off the IR."""
    return list(build_tree(base_columns, steps, column_types=column_types).schema())


def build_tree(
    base_columns: list[str],
    steps: list[dict[str, Any]],
    *,
    column_types: dict[str, PWType] | None = None,
) -> Node:
    """Compile a pipeline to IR, starting from a scan of the source columns."""
    if column_types:
        scan = Scan(
            "__source__",
            tuple((name, column_types.get(name, UNKNOWN)) for name in base_columns),
        )
    else:
        scan = _scan_for(base_columns)
    return compile_pipeline(scan, steps)


def can_derive(base_columns: list[str], steps: list[dict[str, Any]]) -> bool:
    """Whether the IR can describe this pipeline at all.

    False for a pipeline whose shape the algebra does not model -- a pivot
    produces columns from *data*, so no static analysis can name them. Saying so
    is the point; guessing would put invented column names into lineage.
    """
    try:
        build_tree(base_columns, steps)
    except (IRError, ValueError, KeyError):
        return False
    return True
