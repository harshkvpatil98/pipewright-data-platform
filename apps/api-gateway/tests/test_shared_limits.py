"""Limits the web states for itself match the API's (adoption-readiness A8, Y8).

The chart builder says a dataset is too large to chart without asking the
API, so its number must be the API's own.
"""

from __future__ import annotations

import re
from pathlib import Path

from service_reporting.service import MAX_SOURCE_ROWS

SHARED = Path(__file__).resolve().parents[3] / "packages" / "shared-types" / "src" / "reporting.ts"


def test_the_chart_row_limit_is_the_apis() -> None:
    [found] = re.findall(r"export const CHART_ROW_LIMIT = ([\d_]+);", SHARED.read_text())
    assert int(found.replace("_", "")) == MAX_SOURCE_ROWS
