from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from service_auth import models as _auth_models  # noqa: F401
from service_auth.schemas import UserRead
from service_datasets import models as _dataset_models  # noqa: F401
from service_pipeline_runs import models as _pipeline_run_models  # noqa: F401
from service_projects import models as _project_models  # noqa: F401
from service_transformations.router import build_router
from shared_python.errors import NotFoundError, UnauthorizedError, register_exception_handlers


class FakeDb:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, instance: object) -> None:
        self.added.append(instance)

    def commit(self) -> None:
        now = datetime.now(UTC)
        for instance in self.added:
            if getattr(instance, "id", None) is None:
                instance.id = uuid.uuid4()
            if getattr(instance, "created_at", None) is None:
                instance.created_at = now
            instance.updated_at = now

    def refresh(self, _instance: object) -> None:
        return None


def _build_test_client() -> tuple[TestClient, FakeDb, UserRead]:
    current_user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db = FakeDb()

    def get_db() -> FakeDb:
        return db

    def get_current_user() -> UserRead:
        return current_user

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user))
    return TestClient(app), db, current_user


def _build_unauthorized_client() -> TestClient:
    def get_db() -> FakeDb:
        return FakeDb()

    def get_current_user() -> UserRead:
        raise UnauthorizedError("Authentication required.")

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(get_db, get_current_user))
    return TestClient(app)


@patch("service_transformations.service.get_dataset_model_for_project")
@patch("service_transformations.service.ensure_owned_project")
def test_create_pipeline_accepts_valid_steps(
    _ensure_owned_project,
    get_dataset_model_for_project,
) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    get_dataset_model_for_project.return_value = object()
    client, db, current_user = _build_test_client()

    response = client.post(
        f"/projects/{project_id}/datasets/{dataset_id}/pipelines",
        json={
            "name": "Normalize customers",
            "description": "Baseline cleanup pipeline",
            "status": "draft",
            "steps_json": [
                {
                    "step_type": "rename_columns",
                    "config": {"mappings": {"customer_name": "name"}},
                }
            ],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["project_id"] == str(project_id)
    assert body["base_dataset_id"] == str(dataset_id)
    assert body["created_by_user_id"] == str(current_user.id)
    assert body["step_count"] == 1
    assert body["steps_json"][0]["step_type"] == "rename_columns"
    assert db.added[0].name == "Normalize customers"


@patch("service_transformations.service.get_dataset_model_for_project")
@patch("service_transformations.service.ensure_owned_project")
def test_create_pipeline_rejects_invalid_step_type(
    _ensure_owned_project,
    get_dataset_model_for_project,
) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    get_dataset_model_for_project.return_value = object()
    client, _db, _current_user = _build_test_client()

    response = client.post(
        f"/projects/{project_id}/datasets/{dataset_id}/pipelines",
        json={
            "name": "Normalize customers",
            "steps_json": [
                {
                    "step_type": "merge_rows",
                    "config": {"mode": "dedupe"},
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "unsupported step_type" in response.json()["detail"]


@patch("service_transformations.service.get_dataset_model_for_project")
@patch("service_transformations.service.ensure_owned_project")
def test_create_pipeline_rejects_invalid_structure(
    _ensure_owned_project,
    get_dataset_model_for_project,
) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    get_dataset_model_for_project.return_value = object()
    client, _db, _current_user = _build_test_client()

    response = client.post(
        f"/projects/{project_id}/datasets/{dataset_id}/pipelines",
        json={
            "name": "Normalize customers",
            "steps_json": [
                {
                    "step_type": "rename_columns",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "missing required field" in response.json()["detail"]


@patch(
    "service_transformations.service.ensure_owned_project",
    side_effect=NotFoundError("Project not found."),
)
def test_create_pipeline_rejects_non_owned_project(_ensure_owned_project) -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    client, _db, _current_user = _build_test_client()

    response = client.post(
        f"/projects/{project_id}/datasets/{dataset_id}/pipelines",
        json={
            "name": "Normalize customers",
            "steps_json": [],
        },
    )

    assert response.status_code == 404
    assert response.json() == {"detail": "Project not found."}


def test_create_pipeline_rejects_unauthenticated_access() -> None:
    project_id = uuid.uuid4()
    dataset_id = uuid.uuid4()
    client = _build_unauthorized_client()

    response = client.post(
        f"/projects/{project_id}/datasets/{dataset_id}/pipelines",
        json={
            "name": "Normalize customers",
            "steps_json": [],
        },
    )

    assert response.status_code == 401
    assert response.json() == {"detail": "Authentication required."}
