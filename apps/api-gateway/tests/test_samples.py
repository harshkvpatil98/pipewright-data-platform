"""Sample datasets: each lands as an ordinary dataset, and a template fits it.

The samples exist so a newcomer can try the product without a file of their
own. That only works if each one ingests cleanly through the normal upload
path and if the recipe templates offered beside them actually fit them.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from io import BytesIO

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - registers every service's tables
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from api_gateway.samples import SAMPLES, add_sample_to_project, describe, sample_bytes
from service_auth.models import User
from service_auth.schemas import UserRead
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from service_transformations.executor import apply_transformation_steps
from service_transformations.templates import build_steps, get_template, suggest_mapping
from shared_python.db import Base
from shared_python.errors import NotFoundError
from shared_python.storage.local import LocalStorageBackend


@pytest.fixture()
def storage(tmp_path) -> LocalStorageBackend:
    return LocalStorageBackend(str(tmp_path / "storage"))


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
def current_user(db: Session) -> UserRead:
    row = User(username="sampler", password_hash="x", role="user", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    return UserRead(
        id=row.id, username=row.username, role="user", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.mark.parametrize("sample", SAMPLES, ids=lambda sample: sample.id)
def test_each_sample_lands_as_a_dataset(sample, db, current_user, storage) -> None:
    project = create_project(db, ProjectCreate(name="Try it out"), current_user)
    response = add_sample_to_project(
        db,
        project_id=project.id,
        sample_id=sample.id,
        current_user=current_user,
        storage_backend=storage,
        settings=settings,
    )
    described = describe(sample)
    assert response.dataset.name == sample.name
    assert response.dataset.ingestion_status == "succeeded"
    assert response.dataset.row_count == described.row_count
    assert response.dataset.column_count == len(described.columns)


def test_an_unknown_sample_is_not_found(db, current_user, storage) -> None:
    project = create_project(db, ProjectCreate(name="Try it out"), current_user)
    with pytest.raises(NotFoundError):
        add_sample_to_project(
            db, project_id=project.id, sample_id="payroll", current_user=current_user,
            storage_backend=storage, settings=settings,
        )


def _frame_and_types(sample_id: str) -> tuple[pd.DataFrame, dict[str, str]]:
    sample = next(item for item in SAMPLES if item.id == sample_id)
    frame = pd.read_csv(BytesIO(sample_bytes(sample)))
    types = {
        column: "float" if pd.api.types.is_float_dtype(dtype)
        else "int" if pd.api.types.is_integer_dtype(dtype)
        else "string"
        for column, dtype in frame.dtypes.items()
    }
    return frame, types


@pytest.mark.parametrize(
    ("sample_id", "template_id"),
    [("customers", "clean_contacts"), ("orders", "monthly_totals"), ("invoices", "tidy_and_dedupe")],
)
def test_the_template_offered_with_each_sample_fits_and_runs(sample_id, template_id) -> None:
    frame, types = _frame_and_types(sample_id)
    mapping, missing = suggest_mapping(get_template(template_id), list(frame.columns), types)
    assert missing == []
    steps = build_steps(template_id, mapping, list(frame.columns), types)
    result, _ = apply_transformation_steps(frame, steps)
    assert len(result) > 0


def test_the_customers_sample_has_something_to_clean() -> None:
    frame, types = _frame_and_types("customers")
    mapping, _ = suggest_mapping(get_template("clean_contacts"), list(frame.columns), types)
    steps = build_steps("clean_contacts", mapping, list(frame.columns), types)
    result, _ = apply_transformation_steps(frame, steps)
    # A duplicate customer and a missing email are in the file on purpose.
    assert len(result) < len(frame)
    assert (result["email"] == result["email"].str.strip().str.lower()).all()
