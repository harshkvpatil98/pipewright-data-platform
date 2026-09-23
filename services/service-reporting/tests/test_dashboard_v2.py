"""Dashboard builder v2: text tiles, one-call tile data with global filters,
auto-refresh cadence, donut, and a KPI that compares periods (P8)."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from pydantic import ValidationError
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.models import Project
from service_reporting.charts import CHART_TYPES_BY_NAME
from service_reporting.schemas import (
    ChartCreate,
    ChartPreviewRequest,
    DashboardCreate,
    DashboardDataRequest,
    DashboardUpdate,
    FilterInput,
    MeasureInput,
    QueryInput,
    TileInput,
)
from service_reporting.service import (
    compute_dashboard_data,
    create_chart,
    create_dashboard,
    get_dashboard,
    get_shared_dashboard,
    preview_chart,
    share_dashboard,
    update_dashboard,
)
from shared_python.db import Base

OWNER_ID = uuid.UUID("f0f0f0f0-f0f0-f0f0-f0f0-f0f0f0f0f0f0")

ORDERS = pd.DataFrame(
    {
        "region": ["north", "south", "north", "east", "south", "north"],
        "ordered_on": ["2026-07-03", "2026-07-20", "2026-08-02", "2026-08-15", "2026-09-01", "2026-09-09"],
        "amount": [100, 250, 80, 120, 300, 60],
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
                  file_path="datasets/orders.csv", file_type="csv", row_count=len(ORDERS))
    db.add(row)
    db.commit()
    return row


def _by_region() -> QueryInput:
    return QueryInput(dimensions=["region"],
                      measures=[MeasureInput(column="amount", aggregation="sum", label="total")])


def _total() -> QueryInput:
    return QueryInput(dimensions=[], measures=[MeasureInput(column="amount", aggregation="sum", label="total")])


# ---- tiles ----


def test_a_text_tile_needs_no_chart_and_a_chart_tile_needs_a_chart():
    TileInput(kind="text", title="Notes", body="Numbers refresh nightly.")
    with pytest.raises(ValidationError):
        TileInput(kind="chart")  # no chart_id
    with pytest.raises(ValidationError):
        TileInput(kind="text")  # nothing to show


def test_text_tiles_are_stored_read_back_and_shared(db, project, dataset, user, storage):
    chart = create_chart(db, project.id, ChartCreate(dataset_id=dataset.id, name="By region", query=_by_region()), user)
    dashboard = create_dashboard(
        db, project.id,
        DashboardCreate(name="Ops", tiles=[
            TileInput(kind="text", title="Read me", body="Figures are gross.", width=12, position=0),
            TileInput(chart_id=chart.id, position=1, width=6),
        ]),
        user,
    )
    kinds = [(tile.kind, tile.title, tile.body, tile.chart_id) for tile in dashboard.tiles]
    assert kinds == [("text", "Read me", "Figures are gross.", None), ("chart", None, None, chart.id)]
    assert dashboard.tiles[1].chart is not None and dashboard.tiles[1].chart.name == "By region"

    share_dashboard(db, project.id, dashboard.id, user)
    token = get_dashboard(db, project.id, dashboard.id, user).share_token
    public = get_shared_dashboard(db, token=token, storage_backend=storage)
    assert [tile.kind for tile in public.tiles] == ["text", "chart"]
    assert public.tiles[0].body == "Figures are gross." and public.tiles[0].data is None
    assert public.tiles[1].data is not None and public.tiles[1].data.row_count == 3


# ---- data in one call, with global filters ----


def test_dashboard_data_applies_saved_filters_and_ad_hoc_overrides(db, project, dataset, user, storage):
    chart = create_chart(db, project.id, ChartCreate(dataset_id=dataset.id, name="By region", query=_by_region()), user)
    dashboard = create_dashboard(
        db, project.id,
        DashboardCreate(
            name="Ops",
            tiles=[TileInput(chart_id=chart.id), TileInput(kind="text", body="hello")],
            filters=[FilterInput(column="region", operator="equals", value="north")],
        ),
        user,
    )

    saved = compute_dashboard_data(db, project.id, dashboard.id, DashboardDataRequest(), user, storage)
    chart_tile = next(tile for tile in saved.tiles if tile.kind == "chart")
    assert [f.value for f in saved.filters_applied] == ["north"]
    assert chart_tile.data.labels == ["north"]
    assert chart_tile.data.series[0]["values"] == [240]
    text_tile = next(tile for tile in saved.tiles if tile.kind == "text")
    assert text_tile.body == "hello" and text_tile.data is None

    # An ad-hoc set replaces the saved one for this computation only.
    adhoc = compute_dashboard_data(
        db, project.id, dashboard.id,
        DashboardDataRequest(filters=[FilterInput(column="region", operator="equals", value="south")]),
        user, storage,
    )
    assert next(t for t in adhoc.tiles if t.kind == "chart").data.labels == ["south"]
    # An empty list means "no filters" -- everything.
    everything = compute_dashboard_data(db, project.id, dashboard.id, DashboardDataRequest(filters=[]), user, storage)
    assert sorted(next(t for t in everything.tiles if t.kind == "chart").data.labels) == ["east", "north", "south"]
    # Saved filters untouched.
    assert [f.value for f in get_dashboard(db, project.id, dashboard.id, user).filters] == ["north"]


def test_one_broken_tile_does_not_blank_the_dashboard(db, project, dataset, user, storage):
    good = create_chart(db, project.id, ChartCreate(dataset_id=dataset.id, name="Good", query=_by_region()), user)
    bad = create_chart(
        db, project.id,
        ChartCreate(dataset_id=dataset.id, name="Bad",
                    query=QueryInput(dimensions=["nope"], measures=[MeasureInput(column="amount", aggregation="sum")])),
        user,
    )
    dashboard = create_dashboard(
        db, project.id, DashboardCreate(name="Ops", tiles=[TileInput(chart_id=bad.id), TileInput(chart_id=good.id)]), user
    )
    data = compute_dashboard_data(db, project.id, dashboard.id, DashboardDataRequest(), user, storage)
    by_name = {tile.chart_name: tile for tile in data.tiles}
    assert by_name["Bad"].data is None and "nope" in (by_name["Bad"].error or "")
    assert by_name["Good"].data is not None and by_name["Good"].data.row_count == 3


# ---- refresh cadence ----


def test_refresh_cadence_is_one_of_the_allowed_values(db, project, user):
    dashboard = create_dashboard(db, project.id, DashboardCreate(name="Ops", refresh_seconds=300), user)
    assert dashboard.refresh_seconds == 300
    with pytest.raises(ValidationError):
        DashboardCreate(name="x", refresh_seconds=1)
    # Leaving the field out keeps it; sending null turns it off.
    assert update_dashboard(db, project.id, dashboard.id, DashboardUpdate(name="Ops 2"), user).refresh_seconds == 300
    assert update_dashboard(db, project.id, dashboard.id, DashboardUpdate(refresh_seconds=None), user).refresh_seconds is None


# ---- chart types ----


def test_donut_is_a_pie_with_the_same_limits():
    assert CHART_TYPES_BY_NAME["donut"].max_categories == CHART_TYPES_BY_NAME["pie"].max_categories


def test_a_kpi_can_compare_the_latest_period_with_the_one_before(db, project, dataset, user, storage):
    data = preview_chart(
        db, project.id,
        ChartPreviewRequest(dataset_id=dataset.id, chart_type="kpi", query=_total(),
                            options={"compare": {"date_column": "ordered_on", "period": "month"}}),
        user, storage,
    )
    # Headline = September (300 + 60); previous = August (80 + 120).
    assert data.series[0]["values"] == [360]
    delta = data.meta["delta"]
    assert delta["current_label"] == "2026-09" and delta["previous_label"] == "2026-08"
    assert delta["previous"] == 200 and delta["change"] == 160
    assert delta["change_pct"] == pytest.approx(0.8)
    assert data.warnings == []


def test_a_kpi_comparison_degrades_honestly_when_it_cannot_be_computed(db, project, dataset, user, storage):
    data = preview_chart(
        db, project.id,
        ChartPreviewRequest(dataset_id=dataset.id, chart_type="kpi", query=_total(),
                            options={"compare": {"date_column": "no_such_column", "period": "month"}}),
        user, storage,
    )
    assert data.series[0]["values"] == [910]  # the all-time value
    assert data.meta is None
    assert any("not in the dataset" in w for w in data.warnings)


def test_a_kpi_comparison_respects_the_charts_own_filters(db, project, dataset, user, storage):
    query = QueryInput(dimensions=[], measures=[MeasureInput(column="amount", aggregation="sum", label="total")],
                       filters=[FilterInput(column="region", operator="equals", value="north")])
    data = preview_chart(
        db, project.id,
        ChartPreviewRequest(dataset_id=dataset.id, chart_type="kpi", query=query,
                            options={"compare": {"date_column": "ordered_on", "period": "month"}}),
        user, storage,
    )
    # north: July 100, August 80, September 60.
    assert data.series[0]["values"] == [60]
    assert data.meta["delta"]["previous"] == 80 and data.meta["delta"]["change"] == -20
