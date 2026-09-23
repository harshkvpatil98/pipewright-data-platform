"""The semantic layer (P9 / product Phase 19): metrics defined once on the IR.

Pins: a metric evaluates through the same aggregation engine charts use, with
its own filters and formula applied first; a chart that names a metric takes
its measure and filters from it, so changing the metric changes the chart; the
definition renders to SQL from the same IR; usage says what moves; deleting a
metric under a chart is refused; every definition change is a new version in
the governance history.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from pydantic import ValidationError
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_governance.models import ResourceVersion
from service_projects.models import Project
from service_reporting.metrics import (
    create_metric,
    delete_metric,
    metric_sql,
    metric_usage,
    preview_metric,
    update_metric,
)
from service_reporting.schemas import (
    ChartCreate,
    ChartPreviewRequest,
    DashboardCreate,
    FilterInput,
    MetricCreate,
    MetricPreviewRequest,
    MetricUpdate,
    QueryInput,
    TileInput,
)
from service_reporting.service import create_chart, create_dashboard, get_chart_with_data, preview_chart
from shared_python.db import Base
from shared_python.errors import BadRequestError, ConflictError

OWNER_ID = uuid.UUID("0c0c0c0c-0c0c-0c0c-0c0c-0c0c0c0c0c0c")
ORDERS = pd.DataFrame(
    {
        "customer_id": ["c1", "c2", "c1", "c3", "c2", "c4"],
        "region": ["north", "south", "north", "east", "south", "north"],
        "status": ["paid", "paid", "refunded", "paid", "paid", "paid"],
        "gross": [100.0, 250.0, 80.0, 120.0, 300.0, 60.0],
        "discount": [10.0, 0.0, 5.0, 20.0, 0.0, 0.0],
    }
)


class _Storage:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read_bytes(self, _path: str) -> bytes:
        return self._payload


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def storage() -> _Storage:
    return _Storage(ORDERS.to_csv(index=False).encode())


@pytest.fixture()
def user(db: Session) -> UserRead:
    db.add(User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True))
    db.add(User(username="revenue", password_hash="x", role="viewer", is_active=True))
    db.flush()
    now = datetime.now(UTC)
    return UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)


@pytest.fixture()
def project(db: Session, user: UserRead) -> Project:
    row = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def dataset(db: Session, project: Project) -> Dataset:
    row = Dataset(project_id=project.id, name="orders", status="ready", ingestion_status="succeeded",
                  file_path="datasets/orders.csv", file_type="csv", row_count=len(ORDERS),
                  schema_json={"ordered_columns": list(ORDERS.columns)})
    db.add(row)
    db.commit()
    return row


def _net_revenue(db, project, dataset, user):
    return create_metric(
        db, project.id,
        MetricCreate(
            dataset_id=dataset.id, name="Net revenue", description="Gross less discount, paid orders only.",
            owner_username="revenue", aggregation="sum", formula="[gross] - [discount]",
            filters=[FilterInput(column="status", operator="equals", value="paid")],
            dimensions=["region"],
        ),
        user,
    )


def test_a_metric_evaluates_with_its_own_filters_and_formula(db, project, dataset, user, storage):
    metric = _net_revenue(db, project, dataset, user)
    assert metric.slug == "net-revenue" and metric.owner_username == "revenue" and metric.version_number == 1

    total = preview_metric(db, project.id, metric.id, MetricPreviewRequest(), user, storage)
    # paid orders: 90 + 250 + 100 + 300 + 60 = 800 (the refund is excluded)
    assert total.columns == ["net-revenue"] and total.rows[0]["net-revenue"] == 800.0

    by_region = preview_metric(db, project.id, metric.id, MetricPreviewRequest(dimensions=["region"]), user, storage)
    values = {row["region"]: row["net-revenue"] for row in by_region.rows}
    assert values == {"north": 150.0, "south": 550.0, "east": 100.0}

    with pytest.raises(BadRequestError, match="may be cut by region only"):
        preview_metric(db, project.id, metric.id, MetricPreviewRequest(dimensions=["status"]), user, storage)


def test_a_chart_that_names_a_metric_follows_the_definition(db, project, dataset, user, storage):
    metric = _net_revenue(db, project, dataset, user)
    chart = create_chart(
        db, project.id,
        ChartCreate(dataset_id=dataset.id, name="Net by region", chart_type="bar",
                    query=QueryInput(dimensions=["region"]), metric_id=metric.id),
        user,
    )
    assert chart.metric_id == metric.id and chart.metric_name == "Net revenue"
    before = get_chart_with_data(db, project.id, chart.id, user, storage).data
    assert dict(zip(before.labels, before.series[0]["values"])) == {"south": 550.0, "north": 150.0, "east": 100.0}
    assert before.series[0]["name"] == "net-revenue"

    # Change the definition: gross, not net. Every chart moves with it.
    updated = update_metric(db, project.id, metric.id, MetricUpdate(formula="[gross]"), user)
    assert updated.version_number == 2
    after = get_chart_with_data(db, project.id, chart.id, user, storage).data
    assert dict(zip(after.labels, after.series[0]["values"])) == {"south": 550.0, "north": 160.0, "east": 120.0}

    # A chart cannot loosen the metric's filters: its own filters only narrow.
    narrowed = preview_chart(
        db, project.id,
        ChartPreviewRequest(dataset_id=dataset.id, chart_type="kpi", metric_id=metric.id,
                            query=QueryInput(filters=[FilterInput(column="region", operator="equals", value="north")])),
        user, storage,
    )
    assert narrowed.series[0]["values"] == [160.0]


def test_a_description_edit_is_not_a_new_version_but_a_definition_change_is(db, project, dataset, user):
    metric = _net_revenue(db, project, dataset, user)
    same = update_metric(db, project.id, metric.id, MetricUpdate(description="Now with a clearer sentence."), user)
    assert same.version_number == 1
    changed = update_metric(db, project.id, metric.id, MetricUpdate(aggregation="avg"), user)
    assert changed.version_number == 2
    versions = db.scalars(select(ResourceVersion).where(ResourceVersion.resource_id == metric.id)).all()
    assert len(versions) >= 2 and all(v.resource_type == "metric" for v in versions)


def test_the_definition_renders_to_sql_from_the_same_ir(db, project, dataset, user):
    metric = _net_revenue(db, project, dataset, user)
    rendered = metric_sql(db, project.id, metric.id, user, dialect="postgres", dimensions=["region"])
    assert rendered.sql is not None
    assert '"status" = \'paid\'' in rendered.sql.replace("(", "").replace(")", "")
    assert '"gross" - "discount"' in rendered.sql and 'GROUP BY "region"' in rendered.sql
    assert "SUM(" in rendered.sql.upper() and rendered.source_placeholder in rendered.sql
    sqlite = metric_sql(db, project.id, metric.id, user, dialect="sqlite")
    assert sqlite.sql is not None
    # Null tests are part of many definitions ("rows that have an amount");
    # they must render, not refuse -- found live on the first metric defined.
    present = create_metric(
        db, project.id,
        MetricCreate(dataset_id=dataset.id, name="Priced orders", aggregation="count", column="gross",
                     filters=[FilterInput(column="discount", operator="not_null", value=None)]),
        user,
    )
    rendered_null = metric_sql(db, project.id, present.id, user, dialect="postgres")
    assert rendered_null.sql is not None and '"discount" IS NOT NULL' in rendered_null.sql
    nonsense = metric_sql(db, project.id, metric.id, user, dialect="cobol")
    assert nonsense.sql is None and "cannot express" in (nonsense.reason or "")


def test_usage_says_what_moves_and_deletion_under_a_chart_is_refused(db, project, dataset, user):
    metric = _net_revenue(db, project, dataset, user)
    chart = create_chart(db, project.id, ChartCreate(dataset_id=dataset.id, name="Net", chart_type="kpi",
                                                     query=QueryInput(), metric_id=metric.id), user)
    create_dashboard(db, project.id, DashboardCreate(name="Revenue", tiles=[TileInput(chart_id=chart.id)]), user)
    usage = metric_usage(db, project.id, metric.id, user)
    assert [(c.chart_name, c.dashboards) for c in usage.charts] == [("Net", ["Revenue"])]
    with pytest.raises(ConflictError, match="resolve through"):
        delete_metric(db, project.id, metric.id, user)


def test_definitions_are_checked_at_save_time(db, project, dataset, user):
    with pytest.raises(ValidationError):
        MetricCreate(dataset_id=dataset.id, name="x", column="gross", formula="[gross]")
    with pytest.raises(BadRequestError, match="not in 'orders'"):
        create_metric(db, project.id, MetricCreate(dataset_id=dataset.id, name="x", column="nope"), user)
    with pytest.raises(BadRequestError, match="does not parse"):
        create_metric(db, project.id, MetricCreate(dataset_id=dataset.id, name="x", formula="[gross] +"), user)
    with pytest.raises(BadRequestError, match="No account"):
        create_metric(db, project.id, MetricCreate(dataset_id=dataset.id, name="x", column="gross", owner_username="ghost"), user)
    create_metric(db, project.id, MetricCreate(dataset_id=dataset.id, name="Gross", column="gross"), user)
    with pytest.raises(ConflictError, match="already exists"):
        create_metric(db, project.id, MetricCreate(dataset_id=dataset.id, name="gross", column="gross"), user)


def test_a_chart_may_only_name_a_metric_on_its_own_dataset(db, project, dataset, user):
    other = Dataset(project_id=project.id, name="other", status="ready", ingestion_status="succeeded",
                    file_path="datasets/other.csv", file_type="csv")
    db.add(other)
    db.commit()
    metric = _net_revenue(db, project, dataset, user)
    with pytest.raises(BadRequestError, match="different dataset"):
        create_chart(db, project.id, ChartCreate(dataset_id=other.id, name="x", chart_type="kpi", query=QueryInput(), metric_id=metric.id), user)
