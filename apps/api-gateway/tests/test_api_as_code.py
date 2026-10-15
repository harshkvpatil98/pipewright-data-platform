"""What managing Pipewright as code needs from the API (Phase 23, X2).

Terraform reads each thing it manages one at a time and deletes what it
made: one connection (its secrets as ***), one check, one token, deleting a
recipe that nothing runs, and a recipe written as YAML whose step names are
its notes.
"""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'code.db'}", connect_args={"check_same_thread": False})
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
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with factory() as db:
        db.add(User(username="ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
        db.commit()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "ann", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    project = _ok(client.post("/api/v1/projects", json={"name": "Shop"}), 201)["id"]
    orders = _ok(client.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]
    yield {"client": client, "project": project, "orders": orders}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_one_connection_reads_back_with_its_secret_hidden(world) -> None:
    client, project = world["client"], world["project"]
    made = _ok(client.post(f"/api/v1/projects/{project}/extraction/connections", json={
        "name": "Warehouse", "connector_type": "postgresql",
        "config": {"host": "db.example.com", "port": 5432, "database": "shop", "username": "reader",
                   "password": "s3cret"}}), 201)
    read = _ok(client.get(f"/api/v1/projects/{project}/extraction/connections/{made['id']}"))
    assert read["name"] == "Warehouse" and read["config_json"]["password"] == "***"
    assert read["config_json"]["host"] == "db.example.com"
    assert client.get(f"/api/v1/projects/{project}/extraction/connections/"
                      "00000000-0000-4000-8000-000000000001").status_code == 404


def test_one_check_reads_back(world) -> None:
    client, project = world["client"], world["project"]
    made = _ok(client.post(f"/api/v1/projects/{project}/data-quality/rules", json={
        "name": "Every order has an amount", "rule_type": "not_null", "dataset_id": world["orders"]["id"],
        "config": {"column": "amount"}}), 201)
    read = _ok(client.get(f"/api/v1/projects/{project}/data-quality/rules/{made['id']}"))
    assert read["rule_type"] == "not_null" and read["config_json"] == {"column": "amount"}


def test_one_token_reads_back_without_its_secret(world) -> None:
    client = world["client"]
    made = _ok(client.post("/api/v1/auth/tokens", json={"name": "Terraform", "scope": "write",
                                                         "project_ids": [world["project"]], "expires_in_days": 90}), 201)
    read = _ok(client.get(f"/api/v1/auth/tokens/{made['token']['id']}"))
    assert read["name"] == "Terraform" and read["project_ids"] == [world["project"]] and "secret" not in read


def test_a_recipe_nothing_runs_is_deleted_and_one_a_schedule_runs_is_not(world) -> None:
    client, project, orders = world["client"], world["project"], world["orders"]
    steps = [{"step_type": "limit_rows", "config": {"count": 5}}]
    kept = _ok(client.post(f"/api/v1/projects/{project}/datasets/{orders['id']}/pipelines",
                           json={"name": "Scheduled", "steps_json": steps}), 201)
    _ok(client.post(f"/api/v1/projects/{project}/schedules", json={
        "name": "Nightly", "schedule_type": "transformation_pipeline_run", "cron_expression": "0 2 * * *",
        "target_config": {"pipeline_id": kept["id"]}}), 201)
    refused = client.delete(f"/api/v1/projects/{project}/pipelines/{kept['id']}")
    assert refused.status_code == 400 and "is run by the schedule “Nightly”" in refused.text
    gone = _ok(client.post(f"/api/v1/projects/{project}/datasets/{orders['id']}/pipelines",
                           json={"name": "Spare", "steps_json": steps}), 201)
    run = _ok(client.post(f"/api/v1/projects/{project}/pipelines/{gone['id']}/run"))
    assert client.delete(f"/api/v1/projects/{project}/pipelines/{gone['id']}").status_code == 204
    assert client.get(f"/api/v1/projects/{project}/pipelines/{gone['id']}").status_code == 404
    # Its result stays.
    _ok(client.get(f"/api/v1/projects/{project}/datasets/{run['dataset']['id']}"))


def test_a_recipe_written_as_yaml_saves_with_its_step_names_as_notes(world) -> None:
    client, project, orders = world["client"], world["project"], world["orders"]
    text = ("version: 1\nname: Top orders\nsteps:\n  - step: sort_rows\n    name: Biggest first\n"
            "    with:\n      columns: [amount]\n      ascending: false\n")
    parsed = _ok(client.post("/api/v1/workbench/recipe/parse", json={"yaml": text}))
    assert parsed["steps"][0]["config"]["_note"] == "Biggest first"
    made = _ok(client.post(f"/api/v1/projects/{project}/datasets/{orders['id']}/pipelines",
                           json={"name": parsed["name"], "steps_json": parsed["steps"]}), 201)
    again = _ok(client.post("/api/v1/workbench/recipe/yaml", json={"steps": made["steps_json"], "name": made["name"]}))
    assert "name: Biggest first" in again["yaml"] and "_note" not in again["yaml"]
