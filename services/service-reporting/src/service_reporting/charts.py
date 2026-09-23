"""What each chart type needs, and whether a query can actually draw it.

A chart builder that lets you pick "pie" and then hands you nine hundred slices
has not helped anybody. Each type declares the shape it requires -- how many
dimensions, how many measures, whether a category ceiling applies -- and a query
is checked against that *before* it runs, so the message is "a pie chart needs
one grouping column" rather than an unreadable picture.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from shared_python.errors import BadRequestError

from service_reporting.aggregation import Query, QueryResult, apply_filters


@dataclass(frozen=True)
class ChartType:
    name: str
    label: str
    description: str
    min_dimensions: int
    max_dimensions: int
    min_measures: int
    max_measures: int
    # Above this many categories the chart stops communicating anything.
    max_categories: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "label": self.label,
            "description": self.description,
            "min_dimensions": self.min_dimensions,
            "max_dimensions": self.max_dimensions,
            "min_measures": self.min_measures,
            "max_measures": self.max_measures,
            "max_categories": self.max_categories,
        }


CHART_TYPES: tuple[ChartType, ...] = (
    ChartType("bar", "Bar", "Compare a number across categories.", 1, 2, 1, 4, 60),
    ChartType("column", "Column", "The same as bar, standing up.", 1, 2, 1, 4, 40),
    ChartType("line", "Line", "A number over time or another ordered axis.", 1, 2, 1, 4, 400),
    ChartType("area", "Area", "A line with the space beneath it filled.", 1, 2, 1, 4, 400),
    ChartType("scatter", "Scatter", "Two numbers against each other, to see a relationship.", 0, 1, 2, 2, 2000),
    ChartType("pie", "Pie", "Parts of a whole. Only readable with a handful of slices.", 1, 1, 1, 1, 12),
    ChartType("donut", "Donut", "A pie with the total in the middle. Same rules, same limits.", 1, 1, 1, 1, 12),
    ChartType("kpi", "KPI", "One number, large. No grouping.", 0, 0, 1, 1),
    ChartType("table", "Table", "The numbers themselves.", 0, 4, 0, 6),
)

CHART_TYPES_BY_NAME = {chart.name: chart for chart in CHART_TYPES}


def validate_chart(chart_type: str, query: Query) -> list[str]:
    """Check a query can draw this chart. Returns advisory warnings."""
    spec = CHART_TYPES_BY_NAME.get(chart_type)
    if spec is None:
        raise BadRequestError(
            f"Unknown chart type '{chart_type}'. Try: {', '.join(CHART_TYPES_BY_NAME)}."
        )

    dimensions, measures = len(query.dimensions), len(query.measures)

    if dimensions < spec.min_dimensions:
        raise BadRequestError(
            f"A {spec.label.lower()} chart needs at least "
            f"{spec.min_dimensions} grouping column(s); this has {dimensions}."
        )
    if dimensions > spec.max_dimensions:
        raise BadRequestError(
            f"A {spec.label.lower()} chart takes at most "
            f"{spec.max_dimensions} grouping column(s); this has {dimensions}."
        )
    if measures < spec.min_measures:
        raise BadRequestError(
            f"A {spec.label.lower()} chart needs at least {spec.min_measures} measure(s); "
            f"this has {measures}."
        )
    if measures > spec.max_measures:
        raise BadRequestError(
            f"A {spec.label.lower()} chart takes at most {spec.max_measures} measure(s); "
            f"this has {measures}."
        )

    warnings: list[str] = []
    if spec.max_categories and query.limit and query.limit > spec.max_categories:
        warnings.append(
            f"A {spec.label.lower()} chart stops being readable past about "
            f"{spec.max_categories} categories."
        )
    return warnings


@dataclass
class ChartData:
    """A computed chart, in the shape a renderer wants."""

    chart_type: str
    labels: list[Any]
    series: list[dict[str, Any]]
    row_count: int
    truncated: bool
    warnings: list[str]
    #: Renderer facts beyond the series: a KPI's period comparison lives here.
    meta: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "chart_type": self.chart_type,
            "labels": self.labels,
            "series": self.series,
            "row_count": self.row_count,
            "truncated": self.truncated,
            "warnings": self.warnings,
            "meta": self.meta,
        }


#: Periods a KPI can be compared over, and the pandas frequency for each.
KPI_PERIODS: dict[str, str] = {"day": "D", "week": "W", "month": "M", "quarter": "Q", "year": "Y"}


def kpi_with_period_delta(
    frame: pd.DataFrame, query: Query, compare: dict[str, Any], *, run
) -> tuple[ChartData, list[str]]:
    """A KPI that reads "this period vs the one before".

    The headline becomes the LATEST period's value (the period containing the
    newest date in the data after the chart's own filters), and `meta.delta`
    carries the previous period, the change and the percentage. Stated in the
    labels, because "up 12%" is meaningless without "September vs August".
    An unusable configuration -- no such column, no parseable dates -- degrades
    to the plain all-time KPI with a warning, never to a silent zero.
    """
    column = str(compare.get("date_column") or "")
    period = str(compare.get("period") or "month")
    warnings: list[str] = []
    plain = to_chart_data("kpi", query, run(frame, query))
    if period not in KPI_PERIODS:
        warnings.append(f"Unknown comparison period '{period}'; showing the all-time value.")
        return plain, warnings
    if column not in frame.columns:
        warnings.append(f"Comparison column '{column}' is not in the dataset; showing the all-time value.")
        return plain, warnings
    scoped = apply_filters(frame, list(query.filters)) if query.filters else frame
    dates = pd.to_datetime(scoped[column], errors="coerce")
    if dates.notna().sum() == 0:
        warnings.append(f"'{column}' holds no dates to compare by; showing the all-time value.")
        return plain, warnings
    freq = KPI_PERIODS[period]
    periods = dates.dt.to_period(freq)
    current_period = periods.max()
    previous_period = current_period - 1
    measure_query = Query(dimensions=[], measures=list(query.measures), filters=[])
    measure_name = query.measures[0].output_name

    def value_for(mask) -> Any:
        subset = scoped[mask.fillna(False)]
        if subset.empty:
            return None
        result = run(subset, measure_query)
        return _value(result.frame[measure_name].iloc[0]) if not result.frame.empty else None

    current = value_for(periods == current_period)
    previous = value_for(periods == previous_period)
    change = None
    change_pct = None
    if isinstance(current, (int, float)) and isinstance(previous, (int, float)):
        change = current - previous
        change_pct = (change / abs(previous)) if previous not in (0, 0.0) else None
    data = ChartData(
        "kpi",
        labels=[],
        series=[{"name": measure_name, "values": [current]}],
        row_count=1,
        truncated=False,
        warnings=[],
        meta={
            "delta": {
                "period": period,
                "date_column": column,
                "current_label": str(current_period),
                "previous_label": str(previous_period),
                "current": current,
                "previous": previous,
                "change": change,
                "change_pct": change_pct,
            }
        },
    )
    if previous is None:
        warnings.append(
            f"No data for {previous_period} to compare {current_period} with."
        )
    return data, warnings


def to_chart_data(chart_type: str, query: Query, result: QueryResult) -> ChartData:
    """Reshape an aggregation result into labels and series.

    Done here rather than in the browser so a chart, a PDF of the same chart,
    and the spreadsheet emailed from it all read the same numbers.
    """
    spec = CHART_TYPES_BY_NAME[chart_type]
    frame = result.frame
    warnings = list(result.warnings)

    if frame.empty:
        return ChartData(chart_type, [], [], 0, result.truncated, warnings)

    if spec.max_categories and len(frame) > spec.max_categories:
        warnings.append(
            f"Showing {spec.max_categories} of {len(frame)} categories; "
            f"a {spec.label.lower()} chart cannot show more legibly."
        )
        frame = frame.head(spec.max_categories)

    measure_names = [measure.output_name for measure in query.measures]

    if chart_type == "kpi":
        name = measure_names[0]
        return ChartData(
            chart_type,
            labels=[],
            series=[{"name": name, "values": [_value(frame[name].iloc[0])]}],
            row_count=1,
            truncated=result.truncated,
            warnings=warnings,
        )

    if chart_type == "table":
        return ChartData(
            chart_type,
            labels=[str(column) for column in frame.columns],
            series=[
                {"name": str(column), "values": [_value(item) for item in frame[column]]}
                for column in frame.columns
            ],
            row_count=len(frame),
            truncated=result.truncated,
            warnings=warnings,
        )

    if chart_type == "scatter":
        x_name, y_name = measure_names[0], measure_names[1]
        return ChartData(
            chart_type,
            labels=[_value(item) for item in frame[x_name]],
            series=[
                {"name": y_name, "values": [_value(item) for item in frame[y_name]]},
            ],
            row_count=len(frame),
            truncated=result.truncated,
            warnings=warnings,
        )

    label_column = query.dimensions[0]
    labels = [_value(item) for item in frame[label_column]]

    if len(query.dimensions) == 2 and len(measure_names) == 1:
        # A second dimension becomes one series per distinct value, which is
        # what "revenue by month, split by region" means.
        split_column = query.dimensions[1]
        series = []
        for value in frame[split_column].dropna().unique():
            subset = frame[frame[split_column] == value]
            series.append(
                {
                    "name": str(value),
                    "values": [_value(item) for item in subset[measure_names[0]]],
                }
            )
        labels = [_value(item) for item in frame[label_column].unique()]
    else:
        series = [
            {"name": name, "values": [_value(item) for item in frame[name]]}
            for name in measure_names
        ]

    return ChartData(
        chart_type,
        labels=labels,
        series=series,
        row_count=len(frame),
        truncated=result.truncated,
        warnings=warnings,
    )


def _value(item: Any) -> Any:
    """A value JSON can hold, without pandas' own types leaking through."""
    import math

    if item is None:
        return None
    if hasattr(item, "item"):
        item = item.item()
    if isinstance(item, float) and (math.isnan(item) or math.isinf(item)):
        return None
    if isinstance(item, (str, int, float, bool)):
        return item
    return str(item)
