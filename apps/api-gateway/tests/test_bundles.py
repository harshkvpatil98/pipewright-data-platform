"""Project bundles through the API (adoption-readiness A8, Y2).

A project with one of everything is exported and imported into another
project, by HTTP, the way a partner would script it; then imported again
(everything skipped by name), and into a project that lacks the dataset
(skipped with the reason, then made once the person chooses one).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


@pytest.fixture()
def api(tmp_path, monkeypatch):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
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
    db = factory()
    db.add(User(username="partner", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
    db.commit()
    db.close()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "partner", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    yield client
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json()


def _project_with_orders(api, name: str) -> tuple[str, str]:
    project = _ok(api.post("/api/v1/projects", json={"name": name}), 201)["id"]
    dataset = _ok(api.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]["id"]
    return project, dataset


def _one_of_everything(api, project: str, dataset: str) -> None:
    recipe = _ok(api.post(f"/api/v1/projects/{project}/datasets/{dataset}/pipelines", json={
        "name": "Clean orders", "steps_json": [{"step_type": "remove_duplicates", "config": {}}],
    }), 201)["id"]
    check = _ok(api.post(f"/api/v1/projects/{project}/data-quality/rules", json={
        "name": "Order id is filled in", "rule_type": "not_null", "dataset_id": dataset, "config": {"column": "order_id"},
    }), 201)["id"]
    metric = _ok(api.post(f"/api/v1/projects/{project}/metrics", json={
        "name": "Revenue", "dataset_id": dataset, "aggregation": "sum", "column": "amount",
    }), 201)["id"]
    chart = _ok(api.post(f"/api/v1/projects/{project}/charts", json={
        "name": "Revenue by region", "dataset_id": dataset, "chart_type": "bar", "metric_id": metric,
        "query": {"dimensions": ["region"]},
    }), 201)["id"]
    _ok(api.post(f"/api/v1/projects/{project}/dashboards", json={
        "name": "Sales", "tiles": [{"kind": "chart", "chart_id": chart}, {"kind": "text", "title": "Notes", "body": "Weekly."}],
    }), 201)
    _ok(api.post(f"/api/v1/projects/{project}/workflows", json={
        "name": "Nightly", "nodes": [
            {"node_key": "clean", "name": "Clean", "node_type": "transformation", "config": {"pipeline_id": recipe}},
            {"node_key": "check", "name": "Check", "node_type": "quality_gate",
             "config": {"dataset_from": "clean", "rule_ids": [check]}},
        ], "edges": [{"from_node_key": "clean", "to_node_key": "check"}],
    }), 201)
    _ok(api.post(f"/api/v1/projects/{project}/schedules", json={
        "name": "Every morning", "schedule_type": "transformation_pipeline_run", "cron_expression": "0 7 * * *",
        "target_config": {"pipeline_id": recipe},
    }), 201)


def test_a_project_moves_to_another_by_bundle(api) -> None:
    source, dataset = _project_with_orders(api, "Source")
    _one_of_everything(api, source, dataset)

    exported = api.get(f"/api/v1/projects/{source}/bundle")
    assert "attachment" in exported.headers["content-disposition"]
    bundle = exported.json()
    assert bundle["format"] == "pipewright.bundle" and bundle["needs"] == {"dataset": ["Sample orders"]}
    assert dataset not in exported.text, "no ids travel, only names"
    assert bundle["recipes"][0]["base_dataset"] == {"$ref": "dataset", "name": "Sample orders"}

    target, target_dataset = _project_with_orders(api, "Target")
    preview = _ok(api.post(f"/api/v1/projects/{target}/bundle/preview", json={"bundle": bundle}))
    assert preview["creates"] == 7 and preview["skips"] == 0
    [orders] = [ref for ref in preview["references"] if ref["kind"] == "dataset"]
    assert orders["status"] == "matched" and orders["id"] == target_dataset

    result = _ok(api.post(f"/api/v1/projects/{target}/bundle/import", json={"bundle": bundle}))
    assert {made["section"] for made in result["made"]} == {
        "metrics", "recipes", "checks", "charts", "dashboards", "workflows", "schedules",
    }
    recipes = _ok(api.get(f"/api/v1/projects/{target}/datasets/{target_dataset}/pipelines"))["items"]
    assert [recipe["name"] for recipe in recipes] == ["Clean orders"]
    [workflow] = _ok(api.get(f"/api/v1/projects/{target}/workflows"))["items"]
    detail = _ok(api.get(f"/api/v1/projects/{target}/workflows/{workflow['id']}"))
    tasks = {node["node_key"]: node["config_json"] for node in detail["nodes"]}
    assert tasks["clean"]["pipeline_id"] == recipes[0]["id"], "the task runs the imported recipe"
    [check] = _ok(api.get(f"/api/v1/projects/{target}/data-quality/rules"))["items"]
    assert tasks["check"]["rule_ids"] == [check["id"]]

    again = _ok(api.post(f"/api/v1/projects/{target}/bundle/import", json={"bundle": bundle}))
    assert again["made"] == [] and again["skips"] == 7
    assert all("already has" in item["reason"] for item in again["items"])


def test_a_missing_dataset_is_named_and_can_be_chosen(api) -> None:
    source, dataset = _project_with_orders(api, "Source")
    _one_of_everything(api, source, dataset)
    bundle = api.get(f"/api/v1/projects/{source}/bundle").json()

    target = _ok(api.post("/api/v1/projects", json={"name": "Elsewhere"}), 201)["id"]
    other = _ok(api.post(f"/api/v1/projects/{target}/samples/customers"), 201)["dataset"]["id"]
    preview = _ok(api.post(f"/api/v1/projects/{target}/bundle/preview", json={"bundle": bundle}))
    reasons = {item["name"]: item["reason"] for item in preview["items"] if item["action"] == "skip"}
    assert "Sample orders" in reasons["Clean orders"]
    assert [choice["id"] for choice in preview["choices"]["dataset"]] == [other]

    chosen = _ok(api.post(f"/api/v1/projects/{target}/bundle/preview", json={
        "bundle": bundle, "mapping": {"dataset:Sample orders": other},
    }))
    assert {ref["status"] for ref in chosen["references"] if ref["kind"] == "dataset"} == {"chosen"}
    # Customers has no "amount" or "region": what reads them is skipped, saying so,
    # rather than made and broken when opened.
    reasons = {item["name"]: item["reason"] for item in chosen["items"] if item["action"] == "skip"}
    assert "no column “amount”" in reasons["Revenue"]
    assert "“region”" in reasons["Revenue by region"]
    assert "Clean orders" not in reasons, "a recipe's steps are checked when it runs, as in the Studio"


def test_something_that_is_not_a_bundle_is_refused_in_words(api) -> None:
    project = _ok(api.post("/api/v1/projects", json={"name": "Any"}), 201)["id"]
    answer = api.post(f"/api/v1/projects/{project}/bundle/preview", json={"bundle": {"hello": "world"}})
    assert answer.status_code == 400 and "not a Pipewright bundle" in answer.json()["detail"]
