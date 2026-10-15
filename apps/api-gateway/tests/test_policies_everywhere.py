"""Row and column policies hold on every read path (adoption-readiness A6, W1).

One dataset, one policy for the reader's role: the `email` column is denied
and only rows in the EU are visible. Every path that hands rows, values or a
column list to a person is then asked for the data, and none may show an
email or a row outside the EU. A new read path belongs in this file.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_enterprise.models import SecurityPolicy
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.contracts import project_role
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

CSV = (
    b"customer,email,region,amount\n"
    b"ann,ann@example.com,EU,10\n"
    b"bo,bo@example.com,US,20\n"
    b"cy,cy@example.com,EU,30\n"
    b"di,di@example.com,US,40\n"
)
SECRET = "@example.com"


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


def _ingest(db: Session, project, user, storage, name: str):
    return ingest_project_file(
        db, project_id=project.id, dataset_name=name,
        upload_file=IngestionUpload(file_name=f"{name}.csv", content_type="text/csv", file_bytes=CSV),
        storage_backend=storage, settings=settings, current_user=user,
    ).dataset


@pytest.fixture()
def world(db: Session, tmp_path) -> dict:
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    storage = LocalStorageBackend(str(tmp_path / "storage"))
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    dataset = _ingest(db, project, user, storage, "Customers")
    other = _ingest(db, project, user, storage, "Customers again")
    role = project_role(db, project.id, user.id)
    for target in (dataset, other):
        for policy_role in {role, "viewer"}:
            db.add(SecurityPolicy(
                project_id=project.id, dataset_id=target.id, name="EU only, no emails", role=policy_role,
                column_rules_json=[{"column": "email", "action": "deny"}],
                row_rules_json=[{"column": "region", "operator": "equals", "value": "EU"}],
                enabled=True,
            ))
    db.commit()
    return {"project": project, "dataset": dataset, "other": other, "user": user, "storage": storage}


def _clean(text: str) -> None:
    assert SECRET not in text, "an email reached the reader"
    # Inside a JSON string a quoted name is escaped: \"email\" (a plan's SQL), so look for that too.
    for named in ("'email'", '"email"', '\\"email\\"'):
        assert named not in text, "the denied column was named"
    for hidden in ('"US"', '"bo"', '"di"'):
        assert hidden not in text, f"a row outside the EU reached the reader ({hidden})"


def test_the_dataset_page_detail_preview_profile_and_audit(db: Session, world: dict) -> None:
    from service_datasets.service import (
        get_dataset_audit_summary,
        get_dataset_by_project,
        get_dataset_preview,
        get_dataset_profile,
        get_dataset_version_preview,
    )

    args = (db, world["project"].id, world["dataset"].id, world["user"])
    detail = get_dataset_by_project(*args)
    _clean(str(detail.preview_json) + str(detail.profile_json) + str(detail.schema_json))
    assert [row["customer"] for row in detail.preview_json["rows"]] == ["ann", "cy"]
    _clean(get_dataset_preview(*args).model_dump_json())
    _clean(get_dataset_profile(*args).model_dump_json())
    _clean(get_dataset_version_preview(db, world["project"].id, world["dataset"].id, 1, world["user"]).model_dump_json())
    assert "email" not in get_dataset_audit_summary(*args).schema_summary.sample_column_names


def test_sql_over_a_version(db: Session, world: dict) -> None:
    from service_workbench.schemas import TemporalQueryRequest
    from service_workbench.temporal import temporal_query
    from shared_python.errors import BadRequestError

    def run(sql: str):
        return temporal_query(
            db, world["project"].id, world["dataset"].id, TemporalQueryRequest(sql=sql), world["user"], world["storage"]
        )

    assert run("SELECT COUNT(*) AS n FROM dataset").rows[0]["n"] == 2
    _clean(run("SELECT * FROM dataset").model_dump_json())
    with pytest.raises(BadRequestError):
        run("SELECT email FROM dataset")


def test_charts_pivots_dashboards_and_public_links(db: Session, world: dict) -> None:
    from service_reporting.schemas import (
        ChartCreate,
        ChartPreviewRequest,
        DashboardCreate,
        MeasureInput,
        PivotRequest,
        QueryInput,
        TileInput,
    )
    from service_reporting.service import (
        create_chart,
        create_dashboard,
        get_shared_dashboard,
        preview_chart,
        run_pivot,
        share_dashboard,
    )

    project, user, storage = world["project"], world["user"], world["storage"]
    query = QueryInput(dimensions=["region"], measures=[MeasureInput(column="amount", aggregation="sum")])
    preview = preview_chart(
        db, project.id, ChartPreviewRequest(dataset_id=world["dataset"].id, query=query), user, storage
    )
    _clean(preview.model_dump_json())
    pivot = run_pivot(
        db, project.id,
        PivotRequest(dataset_id=world["dataset"].id, rows=["region"], columns=[], measure=MeasureInput(column="amount")),
        user, storage,
    )
    _clean(pivot.model_dump_json())

    chart = create_chart(db, project.id, ChartCreate(dataset_id=world["dataset"].id, name="By region", query=query), user)
    dashboard = create_dashboard(db, project.id, DashboardCreate(name="Sales", tiles=[TileInput(chart_id=chart.id)]), user)
    shared = share_dashboard(db, project.id, dashboard.id, user)
    public = get_shared_dashboard(db, token=shared.share_token, storage_backend=storage)
    _clean(public.model_dump_json())


def test_the_studio_preview_and_its_joins(db: Session, world: dict) -> None:
    from service_transformations.preview import preview_dataset_transformations
    from service_transformations.schemas import TransformationPreviewRequest

    result = preview_dataset_transformations(
        db, project_id=world["project"].id, dataset_id=world["dataset"].id,
        payload=TransformationPreviewRequest(steps=[{
            "step_type": "union_datasets", "config": {"other_dataset_id": str(world["other"].id)},
        }]),
        current_user=world["user"], storage_backend=world["storage"],
    )
    _clean(result.model_dump_json())
    assert result.row_count_before == 2
    # Statistics over rows a policy hides would describe them: every estimate is a guess instead.
    estimates = result.execution_plan.estimates
    assert estimates and all(estimate.guessed for estimate in estimates)


def test_the_studio_plan_for_a_database_never_names_a_denied_column(db: Session, world: dict, monkeypatch) -> None:
    """A plan for a dataset read from a database shows the SQL it would send: only columns the reader may know."""
    from service_transformations import preview
    from service_transformations.schemas import TransformationPreviewRequest

    monkeypatch.setattr(preview, "_source_type_of", lambda dataset: "postgresql")
    result = preview.preview_dataset_transformations(
        db, project_id=world["project"].id, dataset_id=world["dataset"].id,
        payload=TransformationPreviewRequest(steps=[{
            "step_type": "filter_rows",
            "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 5}]},
        }]),
        current_user=world["user"], storage_backend=world["storage"],
    )
    assert result.execution_plan is not None and result.execution_plan.sql
    assert "email" not in result.execution_plan.sql
    _clean(result.model_dump_json())


def test_the_assistant_and_comparisons(db: Session, world: dict) -> None:
    from service_comparisons.schemas import DatasetStatisticalTestRequest
    from service_comparisons.service import get_dataset_comparison_summary
    from service_comparisons.testing_service import run_dataset_statistical_test
    from service_intelligence.service import draft_documentation, scan_pii
    from shared_python.errors import BadRequestError

    project, user, storage = world["project"], world["user"], world["storage"]
    scan = scan_pii(db, project.id, world["dataset"].id, user, storage)
    assert all(finding.column != "email" for finding in scan.findings)
    _clean(draft_documentation(db, project.id, world["dataset"].id, user).model_dump_json())
    _clean(get_dataset_comparison_summary(db, project.id, world["dataset"].id, world["other"].id, user).model_dump_json())
    # Only the two EU rows are visible, which is too few for the test: the
    # refusal is the proof that the hidden rows were never read.
    with pytest.raises(BadRequestError, match="at least 3"):
        run_dataset_statistical_test(
            db, project_id=project.id, left_dataset_id=world["dataset"].id, right_dataset_id=world["other"].id,
            payload=DatasetStatisticalTestRequest(test_type="welch_t_test", column_name="amount"),
            current_user=user, storage_backend=storage,
        )


def test_download(db: Session, world: dict) -> None:
    from service_datasets.download import download_dataset

    content, _, _ = download_dataset(db, world["project"].id, world["dataset"].id, world["user"], world["storage"])
    _clean(content.decode())
