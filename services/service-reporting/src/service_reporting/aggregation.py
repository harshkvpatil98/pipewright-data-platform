"""Turning a dataset into the numbers a chart or a pivot draws.

Charts, pivots, and scheduled reports all ask the same question -- group these
columns, aggregate those, maybe filter first -- so they share one implementation.
Three implementations of "group by and sum" is three chances for a dashboard and
the report emailed from it to disagree, which is the kind of discrepancy that
destroys trust in a platform faster than an outage.

Everything here is pure: a frame goes in, a frame comes out. No database, no
storage, no rendering.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

AGGREGATIONS: dict[str, str] = {
    "sum": "sum",
    "avg": "mean",
    "mean": "mean",
    "min": "min",
    "max": "max",
    "count": "count",
    "count_distinct": "nunique",
    "median": "median",
}

# Aggregations that only mean something on numbers. Applying them to text is a
# mistake worth naming rather than a silent NaN.
NUMERIC_ONLY = frozenset({"sum", "avg", "mean", "median"})

FILTER_OPERATORS = (
    "equals",
    "not_equals",
    "greater_than",
    "greater_or_equal",
    "less_than",
    "less_or_equal",
    "contains",
    "in",
    "is_null",
    "not_null",
)

# A chart with more than this many categories is a smear, not a picture.
MAX_CATEGORIES = 500
MAX_GROUP_COLUMNS = 4


@dataclass(frozen=True)
class Measure:
    """One number to compute."""

    column: str
    aggregation: str = "sum"
    label: str | None = None

    @property
    def output_name(self) -> str:
        return self.label or f"{self.column}_{self.aggregation}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "aggregation": self.aggregation,
            "label": self.label,
            "output_name": self.output_name,
        }


@dataclass(frozen=True)
class Filter:
    column: str
    operator: str = "equals"
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "operator": self.operator, "value": self.value}


@dataclass
class Query:
    """What to compute, independent of how it gets drawn."""

    dimensions: list[str] = field(default_factory=list)
    measures: list[Measure] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    sort_by: str | None = None
    descending: bool = True
    limit: int | None = None


@dataclass
class QueryResult:
    frame: pd.DataFrame
    row_count: int
    truncated: bool = False
    warnings: list[str] = field(default_factory=list)


def _require_columns(frame: pd.DataFrame, columns: list[str], *, what: str) -> None:
    missing = [column for column in columns if column not in frame.columns]
    if missing:
        raise BadRequestError(
            f"{what} refers to column(s) this dataset does not have: {', '.join(missing)}."
        )


def apply_filters(frame: pd.DataFrame, filters: list[Filter]) -> pd.DataFrame:
    """Narrow a frame before aggregating it."""
    if not filters:
        return frame

    _require_columns(frame, [item.column for item in filters], what="A filter")
    working = frame

    for item in filters:
        series = working[item.column]
        operator = item.operator

        if operator not in FILTER_OPERATORS:
            raise BadRequestError(
                f"Unknown filter '{operator}'. Try: {', '.join(FILTER_OPERATORS)}."
            )

        if operator == "is_null":
            mask = series.isna()
        elif operator == "not_null":
            mask = series.notna()
        elif operator == "equals":
            mask = series == item.value
        elif operator == "not_equals":
            mask = series != item.value
        elif operator == "contains":
            mask = series.astype("string").str.contains(str(item.value), case=False, na=False)
        elif operator == "in":
            values = item.value if isinstance(item.value, list) else [item.value]
            mask = series.isin(values)
        else:
            numeric = pd.to_numeric(series, errors="coerce")
            threshold = pd.to_numeric(pd.Series([item.value]), errors="coerce").iloc[0]
            if pd.isna(threshold):
                raise BadRequestError(
                    f"'{item.value}' is not a number, so '{operator}' cannot be applied "
                    f"to '{item.column}'."
                )
            comparisons = {
                "greater_than": numeric > threshold,
                "greater_or_equal": numeric >= threshold,
                "less_than": numeric < threshold,
                "less_or_equal": numeric <= threshold,
            }
            mask = comparisons[operator].fillna(False)

        working = working[mask]

    return working


def run_query(frame: pd.DataFrame, query: Query) -> QueryResult:
    """Group, aggregate, sort, and cut a frame down to what a chart needs."""
    if len(query.dimensions) > MAX_GROUP_COLUMNS:
        raise BadRequestError(
            f"Group by at most {MAX_GROUP_COLUMNS} columns; more than that is a table, not a chart."
        )

    warnings: list[str] = []
    working = apply_filters(frame, query.filters)

    if working.empty:
        return QueryResult(
            frame=pd.DataFrame(columns=[*query.dimensions, *(m.output_name for m in query.measures)]),
            row_count=0,
            warnings=["Nothing matched the filters."],
        )

    _require_columns(working, query.dimensions, what="A grouping")
    _require_columns(working, [measure.column for measure in query.measures], what="A measure")

    for measure in query.measures:
        if measure.aggregation not in AGGREGATIONS:
            raise BadRequestError(
                f"Unknown aggregation '{measure.aggregation}'. "
                f"Try: {', '.join(sorted(AGGREGATIONS))}."
            )
        if measure.aggregation in NUMERIC_ONLY:
            numeric = pd.to_numeric(working[measure.column], errors="coerce")
            if numeric.notna().sum() == 0:
                raise BadRequestError(
                    f"'{measure.column}' has no numeric values, so '{measure.aggregation}' "
                    "cannot be computed from it."
                )
            working = working.assign(**{measure.column: numeric})

    if not query.measures:
        # No measure means "how many", which is what a bare count of a
        # dimension is asking for anyway.
        query = Query(
            dimensions=query.dimensions,
            measures=[Measure(column=query.dimensions[0], aggregation="count", label="count")]
            if query.dimensions
            else [],
            filters=query.filters,
            sort_by=query.sort_by,
            descending=query.descending,
            limit=query.limit,
        )

    if query.dimensions:
        grouped = working.groupby(query.dimensions, dropna=False)
        columns: dict[str, pd.Series] = {}
        for measure in query.measures:
            columns[measure.output_name] = grouped[measure.column].agg(
                AGGREGATIONS[measure.aggregation]
            )
        result = pd.DataFrame(columns).reset_index()
    else:
        # No dimension: one row of totals, which is what a KPI tile wants.
        values = {
            measure.output_name: [
                getattr(working[measure.column], AGGREGATIONS[measure.aggregation])()
            ]
            for measure in query.measures
        }
        result = pd.DataFrame(values)

    sort_column = query.sort_by or (
        query.measures[0].output_name if query.measures else query.dimensions[0]
    )
    if sort_column in result.columns:
        result = result.sort_values(sort_column, ascending=not query.descending)
    else:
        warnings.append(f"'{sort_column}' is not in the result, so the default order was kept.")

    truncated = False
    ceiling = min(query.limit or MAX_CATEGORIES, MAX_CATEGORIES)
    if len(result) > ceiling:
        result = result.head(ceiling)
        truncated = True
        warnings.append(
            f"Showing the top {ceiling} of {len(result)} groups; narrow the query to see the rest."
        )

    return QueryResult(
        frame=result.reset_index(drop=True),
        row_count=len(result),
        truncated=truncated,
        warnings=warnings,
    )


def pivot(
    frame: pd.DataFrame,
    *,
    rows: list[str],
    columns: list[str],
    measure: Measure,
    filters: list[Filter] | None = None,
) -> QueryResult:
    """An Excel-style pivot: one measure, laid out across two axes.

    Kept separate from `run_query` because the shape is genuinely different --
    the column headers come from the data, so the result's schema is not known
    until it has been computed.
    """
    working = apply_filters(frame, filters or [])
    _require_columns(working, [*rows, *columns, measure.column], what="The pivot")

    if not rows and not columns:
        raise BadRequestError("A pivot needs at least one row or column field.")

    if measure.aggregation in NUMERIC_ONLY:
        working = working.assign(
            **{measure.column: pd.to_numeric(working[measure.column], errors="coerce")}
        )

    distinct = int(working[columns[0]].nunique()) if columns else 0
    if distinct > 100:
        raise BadRequestError(
            f"'{columns[0]}' has {distinct} distinct values; a pivot with that many "
            "columns is unreadable. Filter it down first."
        )

    table = pd.pivot_table(
        working,
        index=rows or None,
        columns=columns or None,
        values=measure.column,
        aggfunc=AGGREGATIONS[measure.aggregation],
        dropna=False,
    )

    flat = table.reset_index()
    flat.columns = [
        " · ".join(str(part) for part in column if str(part))
        if isinstance(column, tuple)
        else str(column)
        for column in flat.columns
    ]
    return QueryResult(frame=flat, row_count=len(flat))
