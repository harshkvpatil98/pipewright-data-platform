"""A run's log is kept to its last line, failed or not.

Found while building contracts (C1): every failed recipe run and import kept
only "Waiting to start.", because each write of the log was the same list
as the last, so SQLAlchemy never saw it change.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from service_pipeline_runs.models import PipelineRun
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'runs.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(dependencies, "storage_backend", LocalStorageBackend(str(tmp_path / "storage")))
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    with factory() as db:
        db.add(User(username="ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
        db.commit()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "ann", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    project = client.post("/api/v1/projects", json={"name": "Shop"}).json()["id"]
    orders = client.post(f"/api/v1/projects/{project}/samples/orders").json()["dataset"]
    yield {"api": client, "db": factory, "project": project, "orders": orders}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _recipe(world, steps: list[dict]) -> dict:
    response = world["api"].post(
        f"/api/v1/projects/{world['project']}/datasets/{world['orders']['id']}/pipelines",
        json={"name": "Clean orders", "steps_json": steps},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _run(world, recipe_id: str):
    return world["api"].post(f"/api/v1/projects/{world['project']}/pipelines/{recipe_id}/run")


def test_a_failed_run_keeps_its_whole_log(world) -> None:
    """The log goes up to the step it stopped at, not only its first line."""
    recipe = _recipe(world, [{"step_type": "drop_columns", "config": {"columns": ["nope"]}}])
    assert _run(world, recipe["id"]).status_code == 400
    with world["db"]() as session:
        [run] = session.scalars(select(PipelineRun).where(PipelineRun.status == "failed")).all()
    messages = [event["message"] for event in run.logs_json["events"]]
    assert messages[:3] == ["Waiting to start.", "Run started.", "Reading the input dataset."]
    assert messages[-1].startswith("Stopped while applying step 1")
