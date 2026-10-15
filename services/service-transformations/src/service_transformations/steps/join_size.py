"""How many rows a join will make, counted before it is made (D2, O5).

A join on a key repeated on both sides multiplies: 3,000 rows matching
3,000 on one value are 9,000,000 rows, and 30,000 on 30,000 are
900,000,000, which no worker holds. The output is counted exactly from each
side's key counts (one row per distinct key, so cheap), using the same merge
the join itself uses so keys match the same way (types, and pandas matching
empty keys with each other). A join that would pass the row cap or the
run's memory ceiling stops before allocating, with the numbers.
"""

from __future__ import annotations

import pandas as pd

from shared_python.errors import BadRequestError
from shared_python.memory import frame_bytes, megabytes, run_memory_limit_bytes

# A many-to-many join can multiply row counts without warning, so results are
# capped and the operator is told rather than silently handed a huge frame.
MAX_JOIN_RESULT_ROWS = 5_000_000


def join_output_rows(left: pd.DataFrame, right: pd.DataFrame, left_on: list[str], right_on: list[str],
                     how: str, *, nulls_match: bool = True) -> int:
    """Exactly how many rows `left.merge(right, how, left_on, right_on)` makes.

    `nulls_match=False` counts as SQL joins: an empty key matches nothing (the
    IR's backends); True as pandas merges, an empty key matching another (the
    Join another dataset step).
    """
    if how == "cross":
        return len(left) * len(right)
    if not len(left) or not len(right):
        if how == "inner":
            return 0
        return {"left": len(left), "right": len(right), "outer": len(left) + len(right)}.get(how, 0)
    lefts = left.groupby(left_on, dropna=not nulls_match, sort=False).size().reset_index(name="__left_rows")
    rights = right.groupby(right_on, dropna=not nulls_match, sort=False).size().reset_index(name="__right_rows")
    # Key columns named alike on both sides would clash in the merge of the counts.
    rights = rights.rename(columns={name: f"__right_{name}" for name in right_on})
    pairs = lefts.merge(rights, left_on=left_on, right_on=[f"__right_{name}" for name in right_on], how="inner")
    matched = int((pairs["__left_rows"] * pairs["__right_rows"]).sum())
    rows = matched
    if how in ("left", "outer"):
        found = pairs.drop_duplicates(subset=left_on)["__left_rows"].sum()
        rows += len(left) - int(found)
    if how in ("right", "outer"):
        found = pairs.drop_duplicates(subset=[f"__right_{name}" for name in right_on])["__right_rows"].sum()
        rows += len(right) - int(found)
    return rows


def check_join(left: pd.DataFrame, right: pd.DataFrame, left_on: list[str], right_on: list[str], how: str, *,
               max_rows: int = MAX_JOIN_RESULT_ROWS, nulls_match: bool = True) -> int:
    """The join's output rows, or a refusal before it is built."""
    rows = join_output_rows(left, right, left_on, right_on, how, nulls_match=nulls_match)
    per_row = (frame_bytes(left) / max(len(left), 1)) + (frame_bytes(right) / max(len(right), 1))
    size = rows * per_row
    if rows > max_rows:
        raise BadRequestError(
            f"This join would make {rows:,} rows, above the {max_rows:,}-row limit, so it was not built. "
            "Keys repeated on both sides multiply: check the key columns line up, or remove duplicates or "
            "group one side first."
        )
    if size > run_memory_limit_bytes():
        raise BadRequestError(
            f"This join would make {rows:,} rows, about {megabytes(size)}, past this run's ceiling of "
            f"{megabytes(run_memory_limit_bytes())} (RUN_MEMORY_LIMIT_MB), so it was not built. Filter or group "
            "one side first, or ask an admin to raise the ceiling."
        )
    return rows
