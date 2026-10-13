from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from service_pipeline_runs.audit import (
    build_run_audit_summary,
    extract_related_dataset_ids,
)


def test_extract_related_dataset_ids_orders_unique() -> None:
    d1 = str(uuid.uuid4())
    d2 = str(uuid.uuid4())
    summary = {
        "dataset": {"id": d1},
        "base_dataset": {"id": d2},
        "derived_dataset": {"id": d1},
    }
    ids = extract_related_dataset_ids(summary)
    assert len(ids) == 2


def test_build_run_audit_summary_ingestion_success() -> None:
    ds = uuid.uuid4()
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=None,
        run_type="dataset_ingestion",
        status="succeeded",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        summary_json={
            "ingestion_type": "dataset_upload",
            "dataset": {"id": str(ds), "name": "A", "ingestion_status": "succeeded"},
        },
        logs_json={"events": [{"stage": "parse", "message": "ok"}, {"stage": "succeeded", "message": "done"}]},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.status == "succeeded"
    assert audit.highlights.stage_count == 2
    assert ds in audit.related_dataset_ids
    assert "It finished without problems." in audit.warnings
    assert "Some details of this run were not recorded." not in audit.warnings


def test_build_run_audit_summary_partial_logs_and_empty_summary() -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=None,
        run_type="dataset_ingestion",
        status="failed",
        started_at=None,
        completed_at=datetime.now(UTC),
        summary_json={},
        logs_json={"unexpected": True},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.highlights.stage_count == 0
    assert "Some details of this run were not recorded." in audit.warnings


def test_build_run_audit_summary_transformation_derived() -> None:
    base = uuid.uuid4()
    derived = uuid.uuid4()
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=uuid.uuid4(),
        run_type="dataset_transformation",
        status="succeeded",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        summary_json={
            "transformation_type": "dataset_transformation",
            "base_dataset": {"id": str(base), "name": "B"},
            "derived_dataset": {"id": str(derived), "name": "C"},
        },
        logs_json={"events": [{"stage": "succeeded", "message": "Transformation run completed successfully."}]},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.highlights.derived_dataset_created is True
    assert derived in audit.related_dataset_ids
    assert "It made a new dataset." in audit.warnings


def test_build_run_audit_summary_failed_stage_from_summary() -> None:
    run = SimpleNamespace(
        id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        triggered_by_user_id=uuid.uuid4(),
        pipeline_id=None,
        run_type="dataset_ingestion",
        status="failed",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        summary_json={"failure_stage": "parse", "ingestion_type": "dataset_upload"},
        logs_json={"events": []},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    audit = build_run_audit_summary(run=run)
    assert audit.highlights.failed_stage == "parse"
    assert "It stopped while reading the rows." in audit.warnings


def test_the_audit_names_the_person_the_recipe_and_the_datasets() -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import api_gateway.metadata  # noqa: F401
    import service_access  # noqa: F401
    from service_auth.models import User
    from service_auth.schemas import UserRead
    from service_datasets.models import Dataset
    from service_pipeline_runs.models import PipelineRun
    from service_pipeline_runs.service import get_run_audit_summary
    from service_projects.schemas import ProjectCreate
    from service_projects.service import create_project
    from service_transformations.models import TransformationPipeline
    from shared_python.db import Base

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    person = User(username="ann", display_name="Ann Lee", password_hash="x", role="admin", is_active=True)
    db.add(person)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=person.id, username="ann", role="admin", is_active=True, created_at=now, updated_at=now)
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    base = Dataset(project_id=project.id, name="Orders")
    db.add(base)
    db.flush()
    recipe = TransformationPipeline(project_id=project.id, base_dataset_id=base.id, name="Tidy orders", steps_json=[],
                                    created_by_user_id=person.id)
    db.add(recipe)
    db.flush()
    run = PipelineRun(project_id=project.id, triggered_by_user_id=person.id, pipeline_id=recipe.id,
                      run_type="dataset_transformation", status="succeeded",
                      summary_json={"base_dataset": {"id": str(base.id)}}, logs_json={"events": []})
    db.add(run)
    db.commit()

    audit = get_run_audit_summary(db, project.id, run.id, user)

    assert audit.triggered_by_name == "Ann Lee"
    assert audit.pipeline_name == "Tidy orders"
    assert audit.dataset_names == {str(base.id): "Orders"}
    db.close()
