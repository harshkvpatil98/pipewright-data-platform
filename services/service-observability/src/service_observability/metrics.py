"""Turning a dataset profile into a time series.

Profiles are already computed on every ingestion and every transformation run;
until now each one overwrote the last, so "was this normal?" had no answer. This
module pulls the handful of numbers worth tracking out of a profile and names
them consistently, which is all a chart or a baseline needs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Dataset-wide metrics.
ROW_COUNT = "row_count"
COLUMN_COUNT = "column_count"
DUPLICATE_PERCENTAGE = "duplicate_row_percentage"
COMPLETENESS = "completeness_score"

# Per-column metrics.
NULL_PERCENTAGE = "null_percentage"
DISTINCT_COUNT = "unique_count"
MEAN_VALUE = "mean_value"

DATASET_METRICS = (ROW_COUNT, COLUMN_COUNT, DUPLICATE_PERCENTAGE, COMPLETENESS)
COLUMN_METRICS = (NULL_PERCENTAGE, DISTINCT_COUNT, MEAN_VALUE)
ALL_METRICS = (*DATASET_METRICS, *COLUMN_METRICS)

# How each metric reads in a sentence, and which direction is bad news.
METRIC_LABELS: dict[str, str] = {
    ROW_COUNT: "row count",
    COLUMN_COUNT: "column count",
    DUPLICATE_PERCENTAGE: "duplicate rows",
    COMPLETENESS: "completeness",
    NULL_PERCENTAGE: "null rate",
    DISTINCT_COUNT: "distinct values",
    MEAN_VALUE: "average",
}

METRIC_UNITS: dict[str, str] = {
    DUPLICATE_PERCENTAGE: "%",
    COMPLETENESS: "%",
    NULL_PERCENTAGE: "%",
}

# Tracking every column of a 400-column dataset would bury the useful signal
# and the table under it.
MAX_TRACKED_COLUMNS = 40


@dataclass(frozen=True)
class MetricSample:
    metric_key: str
    value: float
    column_name: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"metric_key": self.metric_key, "value": self.value, "column_name": self.column_name}


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        as_float = float(value)
        # NaN and infinity survive JSON round-trips as floats and would poison
        # every baseline computed from them.
        if as_float != as_float or as_float in (float("inf"), float("-inf")):
            return None
        return as_float
    return None


def metrics_from_profile(
    profile: dict[str, Any] | None, *, max_columns: int = MAX_TRACKED_COLUMNS
) -> list[MetricSample]:
    """Every metric worth charting, read out of one profile."""
    if not isinstance(profile, dict):
        return []

    samples: list[MetricSample] = []
    for key in DATASET_METRICS:
        value = _number(profile.get(key))
        if value is not None:
            samples.append(MetricSample(metric_key=key, value=value))

    columns = profile.get("columns")
    if isinstance(columns, list):
        for entry in columns[:max_columns]:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not isinstance(name, str) or not name:
                continue
            for key in COLUMN_METRICS:
                value = _number(entry.get(key))
                if value is not None:
                    samples.append(MetricSample(metric_key=key, value=value, column_name=name))

    return samples


def format_value(metric_key: str, value: float) -> str:
    """A number as a person would write it, so explanations read naturally."""
    unit = METRIC_UNITS.get(metric_key, "")
    if unit == "%":
        return f"{value:.1f}%"
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def describe(metric_key: str, column_name: str | None = None) -> str:
    label = METRIC_LABELS.get(metric_key, metric_key.replace("_", " "))
    return f"{label} of '{column_name}'" if column_name else label
