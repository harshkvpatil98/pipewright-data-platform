"""Charts, dashboards, reports, catalog, and glossary over real rows."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.models import Project
from service_reporting.models import ReportDelivery
from service_reporting.schemas import (
    AnnotationUpdate,
    ChartCreate,
    ChartPreviewRequest,
    DashboardCreate,
    FilterInput,
    MeasureInput,
    PivotRequest,
    QueryInput,
    ReportCreate,
    TermCreate,
    TileInput,
)
from service_reporting.service import (
    create_chart,
    create_dashboard,
    create_report,
    create_term,
    get_chart_with_data,
    get_shared_dashboard,
    link_term_to_dataset,
    list_dataset_terms,
    list_terms,
    preview_chart,
    run_pivot,
    run_report,
    search_catalog,
    share_dashboard,
    unlink_term_from_dataset,
    unshare_dashboard,
    update_annotation,
    update_dashboard,
)
from shared_python.errors import BadRequestError, NotFoundError

OWNER_ID = uuid.UUID("f0f0f0f0-f0f0-f0f0-f0f0-f0f0f0f0f0f0")

SALES = pd.DataFrame(
    {
        "region": ["north", "south", "north", "east", "south"],
        "channel": ["web", "web", "store", "web", "store"],
        "amount": [100, 250, 80, 120, 300],
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
    Base_metadata_create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def Base_metadata_create(engine) -> None:
    from shared_python.db import Base

    Base.metadata.create_all(engine)


@pytest.fixture()
def storage() -> _Storage:
    return _Storage(SALES.to_csv(index=False).encode())


@pytest.fixture()
def user(db: Session) -> UserRead:
    row = User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.flush()
    now = datetime.now(UTC)
    return UserRead(
        id=OWNER_ID, username="owner", role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def project(db: Session, user: UserRead) -> Project:
    row = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(row)
    db.commit()
    return row


@pytest.fixture()
def dataset(db: Session, project: Project) -> Dataset:
    row = Dataset(
        project_id=project.id,
        name="sales",
        status="ready",
        ingestion_status="succeeded",
        file_path="datasets/sales.csv",
        file_type="csv",
        row_count=len(SALES),
        schema_json={"ordered_columns": ["region", "channel", "amount"]},
    )
    db.add(row)
    db.commit()
    return row


def _query() -> QueryInput:
    return QueryInput(
        dimensions=["region"],
        measures=[MeasureInput(column="amount", aggregation="sum", label="total")],
    )


# ---- charts ----


def test_a_chart_can_be_previewed_before_it_is_saved(db, project, dataset, user, storage):
    data = preview_chart(
        db,
        project.id,
        ChartPreviewRequest(dataset_id=dataset.id, chart_type="bar", query=_query()),
        user,
        storage,
    )
    assert set(data.labels) == {"north", "south", "east"}
    assert data.series[0]["values"][0] == 550  # south, sorted first


def test_a_saved_chart_reads_back_with_its_numbers(db, project, dataset, user, storage):
    chart = create_chart(
        db,
        project.id,
        ChartCreate(dataset_id=dataset.id, name="By region", chart_type="bar", query=_query()),
        user,
    )
    loaded = get_chart_with_data(db, project.id, chart.id, user, storage)
    assert loaded.name == "By region"
    assert loaded.data.row_count == 3


def test_a_chart_whose_type_cannot_draw_the_query_is_refused(db, project, dataset, user):
    with pytest.raises(BadRequestError):
        create_chart(
            db,
            project.id,
            ChartCreate(
                dataset_id=dataset.id,
                name="Bad pie",
                chart_type="pie",
                query=QueryInput(
                    dimensions=["region", "channel"],
                    measures=[MeasureInput(column="amount")],
                ),
            ),
            user,
        )


def test_a_chart_on_another_projects_dataset_is_not_found(db, project, dataset, user):
    other = Project(name="Other", slug="other", owner_user_id=OWNER_ID, status="active")
    db.add(other)
    db.commit()
    with pytest.raises(NotFoundError):
        create_chart(
            db,
            other.id,
            ChartCreate(dataset_id=dataset.id, name="Sneaky", query=_query()),
            user,
        )


def test_extra_filters_narrow_a_saved_chart_without_editing_it(db, project, dataset, user, storage):
    chart = create_chart(
        db,
        project.id,
        ChartCreate(dataset_id=dataset.id, name="By region", query=_query()),
        user,
    )
    filtered = get_chart_with_data(
        db,
        project.id,
        chart.id,
        user,
        storage,
        extra_filters=[FilterInput(column="channel", operator="equals", value="web")],
    )
    assert filtered.data.row_count == 3
    assert sum(filtered.data.series[0]["values"]) == 470


# ---- pivot ----


def test_a_pivot_answers_an_ad_hoc_question(db, project, dataset, user, storage):
    result = run_pivot(
        db,
        project.id,
        PivotRequest(
            dataset_id=dataset.id,
            rows=["region"],
            columns=["channel"],
            measure=MeasureInput(column="amount", aggregation="sum"),
        ),
        user,
        storage,
    )
    assert "region" in result.columns
    assert {"web", "store"} <= set(result.columns)
    assert result.row_count == 3


# ---- dashboards ----


def test_a_dashboard_holds_charts_in_order(db, project, dataset, user):
    first = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="A", query=_query()), user
    )
    second = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="B", query=_query()), user
    )
    dashboard = create_dashboard(
        db,
        project.id,
        DashboardCreate(
            name="Overview",
            tiles=[
                TileInput(chart_id=second.id, position=1),
                TileInput(chart_id=first.id, position=0),
            ],
        ),
        user,
    )
    assert [tile.chart.name for tile in dashboard.tiles] == ["A", "B"]


def test_a_tile_pointing_at_another_projects_chart_is_refused(db, project, dataset, user):
    """It would leak that chart to everyone who can see this dashboard."""
    other = Project(name="Other", slug="other", owner_user_id=OWNER_ID, status="active")
    db.add(other)
    db.commit()
    chart = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="A", query=_query()), user
    )
    with pytest.raises(NotFoundError):
        create_dashboard(
            db, other.id, DashboardCreate(name="Sneaky", tiles=[TileInput(chart_id=chart.id)]), user
        )


def test_a_dashboard_is_not_shareable_until_somebody_shares_it(db, project, user):
    dashboard = create_dashboard(db, project.id, DashboardCreate(name="Overview"), user)
    assert dashboard.share_token is None

    shared = share_dashboard(db, project.id, dashboard.id, user)
    assert shared.share_token is not None
    assert shared.shared_at is not None


def test_sharing_twice_keeps_the_same_link(db, project, user):
    dashboard = create_dashboard(db, project.id, DashboardCreate(name="Overview"), user)
    first = share_dashboard(db, project.id, dashboard.id, user)
    second = share_dashboard(db, project.id, dashboard.id, user)
    assert first.share_token == second.share_token


def test_unsharing_revokes_the_link(db, project, user):
    dashboard = create_dashboard(db, project.id, DashboardCreate(name="Overview"), user)
    share_dashboard(db, project.id, dashboard.id, user)
    assert unshare_dashboard(db, project.id, dashboard.id, user).share_token is None


def test_replacing_tiles_does_not_leave_orphans(db, project, dataset, user):
    from service_reporting.models import DashboardTile

    chart = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="A", query=_query()), user
    )
    dashboard = create_dashboard(
        db, project.id, DashboardCreate(name="Overview", tiles=[TileInput(chart_id=chart.id)]), user
    )
    update_dashboard(db, project.id, dashboard.id, __import__(
        "service_reporting.schemas", fromlist=["DashboardUpdate"]
    ).DashboardUpdate(tiles=[]), user)

    assert db.query(DashboardTile).count() == 0


# ---- reports ----


def test_a_report_from_a_dataset_produces_a_file(db, project, dataset, user, storage):
    report = create_report(
        db,
        project.id,
        ReportCreate(name="Weekly sales", source_kind="dataset", source_id=dataset.id),
        user,
    )
    content, filename, media_type, delivery = run_report(
        db, project.id, report.id, user, storage
    )
    assert len(content) > 0
    assert filename.endswith(".xlsx")
    assert "spreadsheetml" in media_type
    assert delivery.row_count == len(SALES)


def test_a_report_from_a_chart_exports_the_aggregated_numbers(
    db, project, dataset, user, storage
):
    chart = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="By region", query=_query()), user
    )
    report = create_report(
        db,
        project.id,
        ReportCreate(
            name="Region summary", source_kind="chart", source_id=chart.id, file_format="csv"
        ),
        user,
    )
    content, _filename, _media, delivery = run_report(db, project.id, report.id, user, storage)
    assert delivery.row_count == 3  # one row per region, not per sale
    assert b"region" in content


def test_a_report_from_a_dashboard_says_which_chart_each_row_came_from(
    db, project, dataset, user, storage
):
    chart = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="By region", query=_query()), user
    )
    dashboard = create_dashboard(
        db, project.id, DashboardCreate(name="Overview", tiles=[TileInput(chart_id=chart.id)]), user
    )
    report = create_report(
        db,
        project.id,
        ReportCreate(
            name="Everything",
            source_kind="dashboard",
            source_id=dashboard.id,
            file_format="csv",
        ),
        user,
    )
    content, _f, _m, _d = run_report(db, project.id, report.id, user, storage)
    assert b"_chart" in content
    assert b"By region" in content


def test_a_cron_report_gets_a_next_run_time(db, project, dataset, user):
    report = create_report(
        db,
        project.id,
        ReportCreate(
            name="Monday sales",
            source_kind="dataset",
            source_id=dataset.id,
            cron_expression="0 6 * * 1",
            timezone="UTC",
        ),
        user,
    )
    assert report.next_run_at is not None


def test_a_report_with_no_schedule_has_no_next_run(db, project, dataset, user):
    report = create_report(
        db,
        project.id,
        ReportCreate(name="On demand", source_kind="dataset", source_id=dataset.id),
        user,
    )
    assert report.next_run_at is None


def test_running_a_report_records_a_delivery_and_notifies(db, project, dataset, user, storage):
    from service_notifications.models import UserNotification

    report = create_report(
        db,
        project.id,
        ReportCreate(name="Weekly sales", source_kind="dataset", source_id=dataset.id),
        user,
    )
    run_report(db, project.id, report.id, user, storage)

    assert db.query(ReportDelivery).count() == 1
    assert db.query(UserNotification).count() == 1


def test_a_failing_report_records_the_failure_rather_than_hiding_it(
    db, project, dataset, user
):
    class _Missing:
        def read_bytes(self, _path):
            raise FileNotFoundError("gone")

    report = create_report(
        db,
        project.id,
        ReportCreate(name="Weekly sales", source_kind="dataset", source_id=dataset.id),
        user,
    )
    with pytest.raises(BadRequestError):
        run_report(db, project.id, report.id, user, _Missing())

    delivery = db.query(ReportDelivery).one()
    assert delivery.status == "failed"
    assert "missing" in (delivery.message or "").lower()


def test_a_report_pointing_at_nothing_is_refused_at_creation(db, project, user):
    with pytest.raises(NotFoundError):
        create_report(
            db,
            project.id,
            ReportCreate(name="Ghost", source_kind="dataset", source_id=uuid.uuid4()),
            user,
        )


# ---- catalog and glossary ----


def test_the_catalog_finds_a_dataset_by_its_column(db, project, dataset, user):
    result = search_catalog(db, project.id, user, query="channel")
    assert [item["name"] for item in result.items] == ["sales"]


def test_certifying_records_who_and_when(db, project, dataset, user):
    note = update_annotation(
        db,
        project.id,
        dataset.id,
        AnnotationUpdate(certified=True, tags=["Finance", "finance"], description="Sales facts"),
        user,
    )
    assert note.certified is True
    assert note.certified_by_username == "owner"
    assert note.certified_at is not None
    assert note.tags == ["finance"]  # deduplicated and lowercased


def test_certified_datasets_are_counted_and_filterable(db, project, dataset, user):
    update_annotation(db, project.id, dataset.id, AnnotationUpdate(certified=True), user)
    result = search_catalog(db, project.id, user, certified_only=True)
    assert result.certified_count == 1
    assert len(result.items) == 1


def test_a_column_note_makes_a_dataset_findable_by_meaning(db, project, dataset, user):
    update_annotation(
        db,
        project.id,
        dataset.id,
        AnnotationUpdate(column_notes={"amount": "Gross revenue before discounts"}),
        user,
    )
    result = search_catalog(db, project.id, user, query="revenue")
    assert [item["name"] for item in result.items] == ["sales"]


def test_a_term_can_only_be_defined_once(db, project, user):
    create_term(db, project.id, TermCreate(term="Revenue", definition="Money in."), user)
    with pytest.raises(BadRequestError) as caught:
        create_term(db, project.id, TermCreate(term="revenue", definition="Something else."), user)
    assert "already defined" in str(caught.value.detail)


def test_a_term_binds_to_the_columns_it_covers(db, project, dataset, user):
    from service_reporting.schemas import GlossaryBinding

    term = create_term(
        db,
        project.id,
        TermCreate(
            term="Revenue",
            definition="Gross sales before discounts.",
            bindings=[GlossaryBinding(dataset_id=dataset.id, column="amount")],
        ),
        user,
    )
    assert term.bindings[0].column == "amount"
    assert list_terms(db, project.id, user).items[0].term == "Revenue"


def test_a_binding_to_another_projects_dataset_is_refused(db, project, dataset, user):
    from service_reporting.schemas import GlossaryBinding

    other = Project(name="Other", slug="other", owner_user_id=OWNER_ID, status="active")
    db.add(other)
    db.commit()
    with pytest.raises(NotFoundError):
        create_term(
            db,
            other.id,
            TermCreate(
                term="Revenue",
                definition="x",
                bindings=[GlossaryBinding(dataset_id=dataset.id, column="amount")],
            ),
            user,
        )


def test_a_dataset_gets_a_named_steward(db, project, dataset, user):
    steward = User(
        id=uuid.uuid4(), username="dana", password_hash="x", role="editor", is_active=True
    )
    db.add(steward)
    db.commit()

    note = update_annotation(
        db, project.id, dataset.id, AnnotationUpdate(owner_username="Dana"), user
    )
    assert note.owner_username == "dana"

    # An empty string clears the steward; None would leave it unchanged.
    cleared = update_annotation(
        db, project.id, dataset.id, AnnotationUpdate(owner_username=""), user
    )
    assert cleared.owner_username is None


def test_naming_an_unknown_steward_is_refused(db, project, dataset, user):
    with pytest.raises(NotFoundError):
        update_annotation(
            db, project.id, dataset.id, AnnotationUpdate(owner_username="ghost"), user
        )


def test_a_term_links_and_unlinks_from_a_dataset_page(db, project, dataset, user):
    term = create_term(db, project.id, TermCreate(term="Revenue", definition="Money in."), user)
    assert list_dataset_terms(db, project.id, dataset.id, user).items == []

    linked = link_term_to_dataset(db, project.id, dataset.id, term.id, "amount", user)
    assert linked.bindings[0].column == "amount"
    assert [t.term for t in list_dataset_terms(db, project.id, dataset.id, user).items] == [
        "Revenue"
    ]

    # Linking the same column twice does not create a duplicate binding.
    again = link_term_to_dataset(db, project.id, dataset.id, term.id, "amount", user)
    assert len(again.bindings) == 1

    unlink_term_from_dataset(db, project.id, dataset.id, term.id, "amount", user)
    assert list_dataset_terms(db, project.id, dataset.id, user).items == []


def test_linking_a_term_that_does_not_exist_is_refused(db, project, dataset, user):
    with pytest.raises(NotFoundError):
        link_term_to_dataset(db, project.id, dataset.id, uuid.uuid4(), "amount", user)


# ---- public shared dashboard view ----


def test_a_shared_dashboard_renders_its_tiles_with_data(db, project, dataset, user, storage):
    chart = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="Revenue", query=_query()), user
    )
    dashboard = create_dashboard(
        db, project.id, DashboardCreate(name="Overview", tiles=[TileInput(chart_id=chart.id)]), user
    )
    token = share_dashboard(db, project.id, dashboard.id, user).share_token

    view = get_shared_dashboard(db, token=token, storage_backend=storage)
    assert view.name == "Overview"
    assert len(view.tiles) == 1
    tile = view.tiles[0]
    assert tile.name == "Revenue"
    assert tile.data.row_count > 0
    # The public payload carries results only -- no ids, project, or query leak.
    dumped = view.model_dump()
    assert "project_id" not in dumped
    assert all("query" not in t and "dataset_id" not in t for t in dumped["tiles"])


def test_an_unknown_token_is_not_found(db, storage):
    with pytest.raises(NotFoundError):
        get_shared_dashboard(db, token="nope-not-a-real-token", storage_backend=storage)


def test_an_empty_token_is_not_found(db, storage):
    with pytest.raises(NotFoundError):
        get_shared_dashboard(db, token="", storage_backend=storage)


def test_revoking_a_share_makes_the_old_link_stop_working(db, project, dataset, user, storage):
    chart = create_chart(
        db, project.id, ChartCreate(dataset_id=dataset.id, name="Revenue", query=_query()), user
    )
    dashboard = create_dashboard(
        db, project.id, DashboardCreate(name="Overview", tiles=[TileInput(chart_id=chart.id)]), user
    )
    token = share_dashboard(db, project.id, dashboard.id, user).share_token
    assert get_shared_dashboard(db, token=token, storage_backend=storage) is not None

    unshare_dashboard(db, project.id, dashboard.id, user)
    with pytest.raises(NotFoundError):
        get_shared_dashboard(db, token=token, storage_backend=storage)
