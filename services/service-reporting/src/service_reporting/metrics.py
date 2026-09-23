"""The semantic layer: metrics defined once, resolved everywhere.

A metric is one definition of a number: an aggregation over a column or a
row-level formula, the filters that are part of its meaning, and the
dimensions it may honestly be cut by. It is defined on the IR -- the formula
compiles to an IR expression and the pandas backend evaluates it; the same
definition renders to SQL in a source's dialect for the workbench -- and a
chart that names a metric takes its measure and filters from the metric at
compute time, so changing the definition changes every chart at once. Each
change bumps the version and records a snapshot in the governance history,
and the usage endpoint says what will move before it moves.
"""

from __future__ import annotations

import uuid
from typing import Any

import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.contracts import ensure_owned_project
from service_reporting.aggregation import AGGREGATIONS, Filter, Measure, Query, apply_filters, run_query
from service_reporting.catalog import slugify
from service_reporting.models import Dashboard, DashboardTile, Metric, SavedChart
from service_reporting.schemas import (
    FilterInput,
    MeasureInput,
    MetricCreate,
    MetricListResponse,
    MetricPreviewRequest,
    MetricPreviewResponse,
    MetricRead,
    MetricSqlResponse,
    MetricUpdate,
    MetricUsageChart,
    MetricUsageResponse,
    QueryInput,
)
from shared_python.errors import BadRequestError, ConflictError, NotFoundError
from shared_python.logging import get_logger

logger = get_logger(__name__)

RESOURCE_TYPE = "metric"
#: The column a formula metric's per-row value lives in before aggregation.
FORMULA_COLUMN = "__metric_value__"
#: What the rendered SQL reads from; the person replaces it with their table.
SOURCE_PLACEHOLDER = "your_table"


# ------------------------------------------------------------------ reads


def _get_metric(db: Session, project_id: uuid.UUID, metric_id: uuid.UUID) -> Metric:
    metric = db.scalar(
        select(Metric).where(Metric.id == metric_id, Metric.project_id == project_id)
    )
    if metric is None:
        raise NotFoundError("Metric not found.")
    return metric


def _usernames(db: Session, ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    wanted = [item for item in ids if item is not None]
    if not wanted:
        return {}
    rows = db.execute(select(User.id, User.username).where(User.id.in_(wanted))).all()
    return {user_id: username for user_id, username in rows}


def _usage_counts(db: Session, metric_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not metric_ids:
        return {}
    rows = db.execute(
        select(SavedChart.metric_id, func.count(SavedChart.id))
        .where(SavedChart.metric_id.in_(metric_ids))
        .group_by(SavedChart.metric_id)
    ).all()
    return {metric_id: int(count) for metric_id, count in rows}


def _read(metric: Metric, *, owner: str | None, dataset_name: str | None, used_by: int) -> MetricRead:
    return MetricRead(
        id=metric.id,
        project_id=metric.project_id,
        dataset_id=metric.dataset_id,
        dataset_name=dataset_name,
        name=metric.name,
        slug=metric.slug,
        description=metric.description,
        owner_username=owner,
        aggregation=metric.aggregation,
        column=metric.column,
        formula=metric.formula,
        filters=[FilterInput.model_validate(item) for item in (metric.filters_json or [])],
        dimensions=list(metric.dimensions_json or []),
        valid_from=metric.valid_from,
        version_number=metric.version_number,
        used_by_charts=used_by,
        created_at=metric.created_at,
        updated_at=metric.updated_at,
    )


def _reads(db: Session, metrics: list[Metric]) -> list[MetricRead]:
    owners = _usernames(db, [metric.owner_user_id for metric in metrics])
    names = {
        row.id: row.name
        for row in db.scalars(
            select(Dataset).where(Dataset.id.in_([m.dataset_id for m in metrics] or [uuid.uuid4()]))
        ).all()
    }
    usage = _usage_counts(db, [metric.id for metric in metrics])
    return [
        _read(
            metric,
            owner=owners.get(metric.owner_user_id) if metric.owner_user_id else None,
            dataset_name=names.get(metric.dataset_id),
            used_by=usage.get(metric.id, 0),
        )
        for metric in metrics
    ]


def list_metrics(db: Session, project_id: uuid.UUID, current_user: UserRead) -> MetricListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    metrics = list(
        db.scalars(select(Metric).where(Metric.project_id == project_id).order_by(Metric.name)).all()
    )
    return MetricListResponse(items=_reads(db, metrics))


def get_metric(db: Session, project_id: uuid.UUID, metric_id: uuid.UUID, current_user: UserRead) -> MetricRead:
    ensure_owned_project(db, project_id, current_user.id)
    return _reads(db, [_get_metric(db, project_id, metric_id)])[0]


# ------------------------------------------------------------------ writes


def _resolve_owner(db: Session, username: str | None) -> uuid.UUID | None:
    if username is None or not username.strip():
        return None
    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if user is None:
        raise BadRequestError(f"No account is named '{username.strip()}'.")
    return user.id


def _check_definition(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, *, column: str | None,
                      formula: str | None, aggregation: str, filters: list[FilterInput], dimensions: list[str]) -> None:
    dataset = db.scalar(select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id))
    if dataset is None:
        raise NotFoundError("Dataset not found in this project.")
    if aggregation not in AGGREGATIONS:
        raise BadRequestError(f"Unknown aggregation '{aggregation}'. Try: {', '.join(sorted(AGGREGATIONS))}.")
    known = [str(name) for name in (dataset.schema_json or {}).get("ordered_columns", [])]
    if known:
        missing = [name for name in [column, *(f.column for f in filters), *dimensions] if name and name not in known]
        if missing:
            raise BadRequestError(
                f"Column(s) not in '{dataset.name}': {', '.join(sorted(set(missing)))}. "
                f"Known columns: {', '.join(known[:12])}{'…' if len(known) > 12 else ''}."
            )
    if formula:
        from service_transformations.formula.parser import parse_formula

        try:
            parse_formula(formula, columns=known or None)
        except Exception as exc:  # noqa: BLE001 - the message is the point
            raise BadRequestError(f"The formula does not parse: {exc}") from exc


def _unique_slug(db: Session, project_id: uuid.UUID, name: str, *, exclude: uuid.UUID | None = None) -> str:
    slug = slugify(name)
    clash = db.scalar(
        select(Metric).where(Metric.project_id == project_id, Metric.slug == slug, Metric.id != (exclude or uuid.uuid4()))
    )
    if clash is not None:
        raise ConflictError(f"A metric named '{clash.name}' already exists here; pick a different name.")
    return slug


def _snapshot(metric: Metric) -> dict[str, Any]:
    return {
        "name": metric.name,
        "description": metric.description,
        "dataset_id": str(metric.dataset_id),
        "aggregation": metric.aggregation,
        "column": metric.column,
        "formula": metric.formula,
        "filters": list(metric.filters_json or []),
        "dimensions": list(metric.dimensions_json or []),
        "valid_from": metric.valid_from.isoformat() if metric.valid_from else None,
        "version_number": metric.version_number,
    }


def _record_version(db: Session, metric: Metric, actor: UserRead) -> None:
    """Best effort, like every other versioned definition: a save that failed
    because history could not be written would be worse than a gap."""
    try:
        from service_governance.versions import record_version

        record_version(
            db, project_id=metric.project_id, resource_type=RESOURCE_TYPE, resource_id=metric.id,
            name=metric.name, snapshot=_snapshot(metric), actor_user_id=actor.id,
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("metric_version_record_failed id=%s", metric.id)


def create_metric(db: Session, project_id: uuid.UUID, payload: MetricCreate, current_user: UserRead) -> MetricRead:
    ensure_owned_project(db, project_id, current_user.id)
    column = (payload.column or "").strip() or None
    formula = (payload.formula or "").strip() or None
    _check_definition(db, project_id, payload.dataset_id, column=column, formula=formula,
                      aggregation=payload.aggregation, filters=payload.filters, dimensions=payload.dimensions)
    metric = Metric(
        project_id=project_id,
        dataset_id=payload.dataset_id,
        name=payload.name.strip(),
        slug=_unique_slug(db, project_id, payload.name),
        description=payload.description,
        owner_user_id=_resolve_owner(db, payload.owner_username),
        aggregation=payload.aggregation,
        column=column,
        formula=formula,
        filters_json=[item.model_dump(mode="json") for item in payload.filters] or None,
        dimensions_json=list(payload.dimensions) or None,
        valid_from=payload.valid_from,
        version_number=1,
        created_by_user_id=current_user.id,
    )
    db.add(metric)
    db.flush()
    _record_version(db, metric, current_user)
    db.commit()
    db.refresh(metric)
    return _reads(db, [metric])[0]


def update_metric(db: Session, project_id: uuid.UUID, metric_id: uuid.UUID, payload: MetricUpdate,
                  current_user: UserRead) -> MetricRead:
    ensure_owned_project(db, project_id, current_user.id)
    metric = _get_metric(db, project_id, metric_id)
    fields = payload.model_fields_set

    column = metric.column
    formula = metric.formula
    if "column" in fields:
        column = (payload.column or "").strip() or None
        if column:
            formula = None
    if "formula" in fields:
        formula = (payload.formula or "").strip() or None
        if formula:
            column = None
    if bool(column) == bool(formula):
        raise BadRequestError("A metric needs either a column or a formula, not both and not neither.")
    aggregation = payload.aggregation or metric.aggregation
    filters = payload.filters if payload.filters is not None else [
        FilterInput.model_validate(item) for item in (metric.filters_json or [])
    ]
    dimensions = payload.dimensions if payload.dimensions is not None else list(metric.dimensions_json or [])
    _check_definition(db, project_id, metric.dataset_id, column=column, formula=formula,
                      aggregation=aggregation, filters=filters, dimensions=dimensions)

    definition_changed = (
        column != metric.column or formula != metric.formula or aggregation != metric.aggregation
        or [f.model_dump(mode="json") for f in filters] != list(metric.filters_json or [])
        or list(dimensions) != list(metric.dimensions_json or [])
        or ("valid_from" in fields and payload.valid_from != metric.valid_from)
    )
    if payload.name is not None and payload.name.strip() != metric.name:
        metric.slug = _unique_slug(db, project_id, payload.name, exclude=metric.id)
        metric.name = payload.name.strip()
    if "description" in fields:
        metric.description = payload.description
    if "owner_username" in fields:
        metric.owner_user_id = _resolve_owner(db, payload.owner_username)
    metric.column = column
    metric.formula = formula
    metric.aggregation = aggregation
    metric.filters_json = [f.model_dump(mode="json") for f in filters] or None
    metric.dimensions_json = list(dimensions) or None
    if "valid_from" in fields:
        metric.valid_from = payload.valid_from
    if definition_changed:
        # Only a change to what the number MEANS is a new version; a
        # description edit is not.
        metric.version_number += 1
    db.flush()
    _record_version(db, metric, current_user)
    db.commit()
    db.refresh(metric)
    return _reads(db, [metric])[0]


def delete_metric(db: Session, project_id: uuid.UUID, metric_id: uuid.UUID, current_user: UserRead) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    metric = _get_metric(db, project_id, metric_id)
    using = _usage_counts(db, [metric.id]).get(metric.id, 0)
    if using:
        raise ConflictError(
            f"{using} chart(s) resolve through '{metric.name}'. Point them at another metric or "
            "delete them first; removing the definition underneath them would silently change "
            "what they show."
        )
    db.delete(metric)
    db.commit()


# --------------------------------------------------------------- evaluation


def measure_for(metric: Metric) -> Measure:
    column = metric.column or FORMULA_COLUMN
    return Measure(column=column, aggregation=metric.aggregation, label=metric.slug)


def prepare_frame(metric: Metric, frame: pd.DataFrame) -> pd.DataFrame:
    """The frame a metric aggregates over: its own filters applied, and its
    formula (when it has one) evaluated per row into FORMULA_COLUMN through the
    IR, so the number is the same one the SQL rendering computes."""
    working = apply_filters(frame, [Filter(**item) for item in (metric.filters_json or [])])
    if metric.formula:
        from service_transformations.formula.parser import parse_formula
        from service_transformations.ir.pandas_backend import evaluate

        expression = parse_formula(metric.formula, columns=[str(c) for c in working.columns])
        working = working.copy()
        working[FORMULA_COLUMN] = evaluate(expression, working)
    return working


def effective_query(metric: Metric, stored: QueryInput) -> QueryInput:
    """A metric-backed chart's query: the chart's dimensions, extra filters,
    sort and limit; the metric's measure. The metric's own filters are applied
    to the frame in `prepare_frame`, not merged here, so a chart cannot loosen
    them."""
    allowed = list(metric.dimensions_json or [])
    if allowed:
        outside = [d for d in stored.dimensions if d not in allowed]
        if outside:
            raise BadRequestError(
                f"'{metric.name}' may be cut by {', '.join(allowed)} only, not by {', '.join(outside)}."
            )
    measure = measure_for(metric)
    return stored.model_copy(update={
        "measures": [MeasureInput(column=measure.column, aggregation=measure.aggregation, label=measure.label)],
    })


def preview_metric(db: Session, project_id: uuid.UUID, metric_id: uuid.UUID, payload: MetricPreviewRequest,
                   current_user: UserRead, storage_backend) -> MetricPreviewResponse:
    """Compute the metric now, cut by the requested dimensions. A read (viewer):
    `preview` is a read-only segment in the central matrix."""
    from service_reporting.service import _load_frame, _records

    ensure_owned_project(db, project_id, current_user.id)
    metric = _get_metric(db, project_id, metric_id)
    query = effective_query(metric, QueryInput(dimensions=payload.dimensions, filters=payload.filters, limit=payload.limit))
    frame = prepare_frame(metric, _load_frame(db, project_id, metric.dataset_id, storage_backend))
    result = run_query(
        frame,
        Query(
            dimensions=list(query.dimensions),
            measures=[measure_for(metric)],
            filters=[Filter(column=f.column, operator=f.operator, value=f.value) for f in query.filters],
            limit=query.limit,
        ),
    )
    return MetricPreviewResponse(
        metric_id=metric.id,
        columns=[str(c) for c in result.frame.columns],
        rows=_records(result.frame),
        row_count=result.row_count,
        truncated=result.truncated,
        warnings=result.warnings,
    )


# ------------------------------------------------------------------ SQL


def metric_sql(db: Session, project_id: uuid.UUID, metric_id: uuid.UUID, current_user: UserRead, *,
               dialect: str = "postgres", dimensions: list[str] | None = None) -> MetricSqlResponse:
    """The definition as one SELECT in a dialect: what the workbench inserts.
    Built from the same IR the evaluation uses -- scan, the metric's filters,
    the formula as a projection, the aggregation -- so it is the definition
    rendered, not a second one."""
    ensure_owned_project(db, project_id, current_user.id)
    metric = _get_metric(db, project_id, metric_id)
    dataset = db.get(Dataset, metric.dataset_id)
    columns = [str(name) for name in ((dataset.schema_json if dataset else None) or {}).get("ordered_columns", [])]
    dims = list(dimensions or [])
    try:
        sql = render_metric_sql(metric, columns, dims, dialect)
        return MetricSqlResponse(metric_id=metric.id, dialect=dialect, sql=sql, source_placeholder=SOURCE_PLACEHOLDER)
    except Exception as exc:  # noqa: BLE001 - the dialect's refusal is the answer
        return MetricSqlResponse(
            metric_id=metric.id, dialect=dialect, sql=None,
            reason=f"{dialect} cannot express this metric: {exc}", source_placeholder=SOURCE_PLACEHOLDER,
        )


def render_metric_sql(metric: Metric, columns: list[str], dimensions: list[str], dialect: str) -> str:
    from service_transformations.ir.expressions import Call, Column
    from service_transformations.ir.from_steps import compile_step
    from service_transformations.ir.nodes import Aggregate, Node, Project, Scan
    from service_transformations.ir.sql_backend import to_sql
    from shared_python.types import UNKNOWN

    names = columns or sorted({metric.column or "", *dimensions, *(f["column"] for f in (metric.filters_json or []))} - {""})
    node: Node = Scan(SOURCE_PLACEHOLDER, tuple((name, UNKNOWN) for name in names))
    if metric.filters_json:
        node = compile_step(node, "filter_rows", {"conditions": list(metric.filters_json)})
    value_column = metric.column
    if metric.formula:
        from service_transformations.formula.parser import parse_formula

        expression = parse_formula(metric.formula, columns=list(node.schema()))
        node = Project(node, tuple([*((name, Column(name)) for name in node.schema()), (FORMULA_COLUMN, expression)]))
        value_column = FORMULA_COLUMN
    ir_function = {"mean": "avg", "count_distinct": "count_distinct"}.get(metric.aggregation, metric.aggregation)
    node = Aggregate(
        node,
        group_by=tuple((name, Column(name)) for name in dimensions),
        aggregates=((metric.slug, Call(ir_function, (Column(value_column or ""),))),),
    )
    return to_sql(node, dialect)


# ---------------------------------------------------------------- usage


def metric_usage(db: Session, project_id: uuid.UUID, metric_id: uuid.UUID, current_user: UserRead) -> MetricUsageResponse:
    ensure_owned_project(db, project_id, current_user.id)
    metric = _get_metric(db, project_id, metric_id)
    charts = list(db.scalars(select(SavedChart).where(SavedChart.metric_id == metric.id).order_by(SavedChart.name)).all())
    if not charts:
        return MetricUsageResponse(metric_id=metric.id, charts=[])
    tiles = db.execute(
        select(DashboardTile.chart_id, Dashboard.name)
        .join(Dashboard, Dashboard.id == DashboardTile.dashboard_id)
        .where(DashboardTile.chart_id.in_([c.id for c in charts]))
    ).all()
    on_dashboards: dict[uuid.UUID, list[str]] = {}
    for chart_id, name in tiles:
        on_dashboards.setdefault(chart_id, []).append(name)
    return MetricUsageResponse(
        metric_id=metric.id,
        charts=[
            MetricUsageChart(chart_id=c.id, chart_name=c.name, chart_type=c.chart_type,
                             dashboards=sorted(set(on_dashboards.get(c.id, []))))
            for c in charts
        ],
    )
