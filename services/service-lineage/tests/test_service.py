"""Lineage over real rows: ownership, tracing, and impact end to end."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_projects.models import Project
from service_quality.models import DataQualityRule
from service_transformations.models import TransformationPipeline
from shared_python.db import Base
from shared_python.errors import BadRequestError, NotFoundError

from service_lineage.schemas import ImpactRequest
from service_lineage.service import (
    analyse_impact,
    dataset_columns,
    get_dataset_lineage,
    trace_dataset_column,
)

OWNER_ID = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")


@pytest.fixture()
def db() -> Iterator[Session]:
    import api_gateway.metadata  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(user_id: uuid.UUID = OWNER_ID) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user_id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now
    )


def _schema(*columns: str) -> dict:
    return {
        "columns": [{"name": name, "inferred_type": "string", "nullable": False} for name in columns],
        "ordered_columns": list(columns),
    }


@pytest.fixture()
def world(db: Session) -> dict:
    """A raw dataset, a pipeline that reshapes it, and the dataset it produced."""
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.flush()

    raw = Dataset(
        project_id=project.id,
        name="orders_raw",
        status="ready",
        ingestion_status="succeeded",
        schema_json=_schema("id", "region", "amount", "notes"),
    )
    db.add(raw)
    db.flush()

    pipeline = TransformationPipeline(
        project_id=project.id,
        base_dataset_id=raw.id,
        name="Summarise by region",
        status="ready",
        steps_json=[
            {"step_type": "rename_columns", "config": {"mappings": {"amount": "revenue"}}},
            {
                "step_type": "aggregate",
                "config": {
                    "group_by": ["region"],
                    "aggregations": [{"column": "revenue", "function": "sum", "alias": "total"}],
                },
            },
        ],
    )
    db.add(pipeline)
    db.flush()

    derived = Dataset(
        project_id=project.id,
        name="orders_by_region",
        status="ready",
        ingestion_status="succeeded",
        is_derived=True,
        parent_dataset_id=raw.id,
        created_from_pipeline_id=pipeline.id,
        schema_json=_schema("region", "total"),
    )
    db.add(derived)
    db.commit()

    return {"project": project, "raw": raw, "pipeline": pipeline, "derived": derived}


def test_another_users_project_is_not_found(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        get_dataset_lineage(db, world["project"].id, world["raw"].id, _user(uuid.uuid4()))


def test_a_raw_dataset_reports_its_columns_as_sources(db: Session, world: dict):
    response = get_dataset_lineage(db, world["project"].id, world["raw"].id, _user())
    assert [summary.column for summary in response.columns] == ["id", "region", "amount", "notes"]
    assert all(summary.derived is False for summary in response.columns)
    assert any("loaded rather than computed" in note for note in response.notes)


def test_a_derived_dataset_traces_its_columns_to_the_source(db: Session, world: dict):
    response = get_dataset_lineage(db, world["project"].id, world["derived"].id, _user())
    by_column = {summary.column: summary for summary in response.columns}
    assert set(by_column) == {"region", "total"}

    total = by_column["total"]
    assert total.derived is True
    assert [origin.column for origin in total.origins] == ["amount"]
    assert total.origins[0].dataset_name == "orders_raw"


def test_the_graph_places_the_producing_pipeline_upstream(db: Session, world: dict):
    response = get_dataset_lineage(db, world["project"].id, world["derived"].id, _user())
    kinds = {(node.kind, node.name): node.depth for node in response.nodes}
    assert kinds[("dataset", "orders_by_region")] == 0
    assert kinds[("pipeline", "Summarise by region")] < 0
    assert kinds[("dataset", "orders_raw")] < 0


def test_tracing_one_column_returns_a_sentence_a_person_can_read(db: Session, world: dict):
    trace = trace_dataset_column(db, world["project"].id, world["derived"].id, "total", _user())
    assert trace.summary == "'total' is computed from 'amount' in orders_raw."
    assert trace.unresolved is False
    assert [edge.kind for edge in trace.edges] == ["aggregate", "rename"]


def test_tracing_a_column_that_is_not_there_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        trace_dataset_column(db, world["project"].id, world["derived"].id, "nope", _user())


def test_impact_finds_the_pipeline_that_names_the_column(db: Session, world: dict):
    response = analyse_impact(
        db, world["project"].id, world["raw"].id, ImpactRequest(columns=["amount"]), _user()
    )
    assert response.breaks_count == 1
    assert response.findings[0].kind == "pipeline"
    assert response.findings[0].name == "Summarise by region"
    assert "breaks" in response.summary


def test_impact_on_an_unused_column_says_it_is_safe(db: Session, world: dict):
    response = analyse_impact(
        db, world["project"].id, world["raw"].id, ImpactRequest(columns=["notes"]), _user()
    )
    assert response.breaks_count == 0
    assert response.changes_count == 0
    assert "safe to drop" in response.summary


def test_impact_includes_quality_rules_on_the_dataset(db: Session, world: dict):
    db.add(
        DataQualityRule(
            project_id=world["project"].id,
            dataset_id=world["raw"].id,
            name="Region present",
            rule_type="not_null",
            severity="error",
            config_json={"column": "region"},
            enabled=True,
        )
    )
    db.commit()

    response = analyse_impact(
        db, world["project"].id, world["raw"].id, ImpactRequest(columns=["region"]), _user()
    )
    kinds = {finding.kind for finding in response.findings}
    assert kinds == {"pipeline", "quality_rule"}
    assert response.breaks_count == 2


def test_impact_rejects_a_column_the_dataset_does_not_have(db: Session, world: dict):
    with pytest.raises(BadRequestError) as caught:
        analyse_impact(
            db, world["project"].id, world["raw"].id, ImpactRequest(columns=["ghost"]), _user()
        )
    assert "no column(s) named" in str(caught.value.detail)


def test_findings_are_ordered_worst_first(db: Session, world: dict):
    response = analyse_impact(
        db,
        world["project"].id,
        world["raw"].id,
        ImpactRequest(columns=["amount", "notes"]),
        _user(),
    )
    severities = [finding.severity for finding in response.findings]
    assert severities == sorted(severities, key=lambda value: {"breaks": 0, "changes": 1}[value])


def test_dataset_columns_reads_the_stored_schema(db: Session, world: dict):
    assert dataset_columns(db, world["project"].id, world["raw"].id, _user()) == [
        "id",
        "region",
        "amount",
        "notes",
    ]


def test_columns_fall_back_to_the_preview_when_no_schema_was_stored(db: Session, world: dict):
    dataset = Dataset(
        project_id=world["project"].id,
        name="just_uploaded",
        status="registered",
        ingestion_status="pending",
        preview_json={"columns": ["a", "b"], "rows": []},
    )
    db.add(dataset)
    db.commit()
    assert dataset_columns(db, world["project"].id, dataset.id, _user()) == ["a", "b"]


def test_column_types_come_back_for_callers_that_must_choose_a_default(
    db: Session, world: dict
):
    """A chart builder picking a text column to sum is an error on first sight."""
    from service_lineage.service import dataset_column_types

    types = dataset_column_types(db, world["project"].id, world["raw"].id, _user())
    assert set(types) == {"id", "region", "amount", "notes"}
    assert all(value for value in types.values())


def test_column_types_are_empty_rather_than_missing_when_nothing_was_inferred(
    db: Session, world: dict
):
    from service_datasets.models import Dataset
    from service_lineage.service import dataset_column_types

    bare = Dataset(
        project_id=world["project"].id,
        name="bare",
        status="registered",
        ingestion_status="pending",
    )
    db.add(bare)
    db.commit()
    assert dataset_column_types(db, world["project"].id, bare.id, _user()) == {}
