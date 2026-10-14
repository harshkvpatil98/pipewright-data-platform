"""Rule evaluation contracts.

Every rule returns a row-level boolean mask of failures rather than only a
pass/fail verdict. That mask is what makes quarantine possible: failing rows can
be split out of the dataset while the rest continue downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
from shared_python.words import count_of

SEVERITIES: tuple[str, ...] = ("error", "warning")

# Rules that inspect the frame as a whole rather than row by row. These cannot
# quarantine individual rows because no specific row is at fault.
DATASET_LEVEL_RULES: frozenset[str] = frozenset({"row_count", "freshness"})


@dataclass
class RuleEvaluation:
    """Outcome of evaluating one rule against one dataset."""

    status: str  # "passed" | "failed"
    evaluated_rows: int
    failed_rows: int
    message: str
    # None for dataset-level rules, where no individual row is responsible.
    failure_mask: pd.Series | None = None
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def failure_rate(self) -> float:
        if not self.evaluated_rows:
            return 0.0
        return round((self.failed_rows / self.evaluated_rows) * 100, 4)


def passed(evaluated_rows: int, message: str, **details: Any) -> RuleEvaluation:
    return RuleEvaluation(
        status="passed",
        evaluated_rows=evaluated_rows,
        failed_rows=0,
        message=message,
        details=details,
    )


def from_mask(mask: pd.Series, *, message_when_failed: str, message_when_passed: str, **details: Any) -> RuleEvaluation:
    """Build an evaluation from a boolean mask where True marks a failing row."""
    failed_rows = int(mask.sum())
    evaluated_rows = int(len(mask))
    return RuleEvaluation(
        status="failed" if failed_rows else "passed",
        evaluated_rows=evaluated_rows,
        failed_rows=failed_rows,
        # {rows} is the count with its noun ("1 row", "1,200 rows"); {failed}
        # and {total} are the bare numbers.
        message=message_when_failed.format(
            failed=f"{failed_rows:,}", total=f"{evaluated_rows:,}", rows=count_of(evaluated_rows, "row")
        )
        if failed_rows
        else message_when_passed.format(total=f"{evaluated_rows:,}", rows=count_of(evaluated_rows, "row")),
        failure_mask=mask,
        details=details,
    )
