"""Managing recipes through HTTP (E1, T6).

Turning a step off, a note, parameters a run is given, templates a project
saves, branching and merging back, the same steps on another dataset, one
recipe per value, what metadata steps write to the catalogue, a data
dictionary, a thread on one step, the regex tester and revealing a token.

Runs on SQLite and, where CI provides one, on PostgreSQL in a schema of its
own, like test_working_together.
"""

from __future__ import annotations

import io
import os
import uuid

import pandas as pd
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_access.models import ProjectMembership
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"
POSTGRES = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")


def _engine(backend: str, tmp_path):
    if backend == "sqlite":
        return create_engine(f"sqlite:///{tmp_path / 'manage.db'}", connect_args={"check_same_thread": False}), None
    if not POSTGRES:
        pytest.skip("Set CONNECTORS_TEST_POSTGRES_URL to run these on PostgreSQL too.")
    schema = f"manage_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    admin.dispose()
    return create_engine(POSTGRES, connect_args={"options": f"-csearch_path={schema}"}), schema


def _create_tables(engine) -> None:
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        return
    private = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(private)
    private.create_all(engine)


def _client(username: str) -> TestClient:
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json() if response.content and response.headers.get("content-type", "").startswith(
        "application/json") else response


@pytest.fixture(params=["sqlite", "postgres"])
def world(request, tmp_path, monkeypatch):
    engine, schema = _engine(request.param, tmp_path)
    _create_tables(engine)
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
        db.add(User(username="ann", display_name="Ann", password_hash=hash_password(PASSWORD), role="admin",
                    is_active=True))
        db.add(User(username="vic", display_name="Vic", password_hash=hash_password(PASSWORD), role="user",
                    is_active=True))
        db.commit()
    ann = _client("ann")
    project = ann.post("/api/v1/projects", json={"name": "Shop"}).json()["id"]
    with factory() as db:
        vic = db.scalar(select(User).where(User.username == "vic"))
        db.add(ProjectMembership(project_id=uuid.UUID(project), user_id=vic.id, role="viewer"))
        db.commit()
    orders = _ok(ann.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]
    customers = _ok(ann.post(f"/api/v1/projects/{project}/samples/customers"), 201)["dataset"]
    yield {"ann": ann, "vic": _client("vic"), "project": project, "orders": orders, "customers": customers,
           "db": factory}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()
    if schema is not None:
        admin = create_engine(POSTGRES)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _base(world) -> str:
    return f"/api/v1/projects/{world['project']}"


def _recipe(world, steps: list[dict], name: str = "Orders") -> dict:
    return _ok(world["ann"].post(f"{_base(world)}/datasets/{world['orders']['id']}/pipelines",
                                 json={"name": name, "steps_json": steps}), 201)


def _rows(world, run: dict) -> pd.DataFrame:
    response = world["ann"].get(f"{_base(world)}/datasets/{run['dataset']['id']}/download")
    assert response.status_code == 200, response.text
    return pd.read_csv(io.BytesIO(response.content))


SHIPPED = {"step_type": "filter_rows", "config": {"conditions": [{"column": "status", "operator": "equals",
                                                                  "value": "shipped"}]}}
DROP_STATUS = {"step_type": "drop_columns", "config": {"columns": ["status"]}}


def test_a_step_turned_off_passes_its_rows_through_and_keeps_its_note(world) -> None:
    off = {"step_type": "drop_columns", "config": {"columns": ["status"], "_enabled": False,
                                                   "_note": "Keep status until finance agrees"}}
    recipe = _recipe(world, [off, SHIPPED])
    run = _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/run"))
    rows = _rows(world, run)
    assert "status" in rows.columns and set(rows["status"]) == {"shipped"}
    saved = _ok(world["ann"].get(f"{_base(world)}/pipelines/{recipe['id']}"))
    assert saved["steps_json"][0]["config"]["_note"] == "Keep status until finance agrees"
    preview = _ok(world["ann"].post(f"{_base(world)}/datasets/{world['orders']['id']}/pipelines/preview",
                                    json={"steps": [off]}))
    assert "status" in preview["preview_columns"]
    assert preview["step_outcomes"][0]["rows_after"] == preview["step_outcomes"][0]["rows_before"]


def test_parameters_are_given_per_run_and_typed(world) -> None:
    steps = [{"step_type": "filter_rows", "config": {"conditions": [
        {"column": "amount", "operator": "greater_or_equal", "value": "{{least}}"}]}}]
    recipe = _recipe(world, steps)
    url = f"{_base(world)}/pipelines/{recipe['id']}"
    _ok(world["ann"].put(f"{url}/parameters", json={"parameters": [
        {"name": "least", "label": "Smallest order", "kind": "number", "default": 100}]}))
    default = _rows(world, _ok(world["ann"].post(f"{url}/run")))
    given = _rows(world, _ok(world["ann"].post(f"{url}/run", json={"parameters": {"least": 300}})))
    assert default["amount"].min() >= 100 and given["amount"].min() >= 300 and len(given) < len(default)
    refused = world["ann"].post(f"{url}/run", json={"parameters": {"least": "lots"}})
    assert refused.status_code == 400 and "Smallest order is a number" in refused.text
    unknown = world["ann"].post(f"{url}/run", json={"parameters": {"most": 1}})
    assert unknown.status_code == 400 and "no parameter called most" in unknown.text
    preview = _ok(world["ann"].post(f"{_base(world)}/datasets/{world['orders']['id']}/pipelines/preview", json={
        "steps": steps, "parameters": [{"name": "least", "kind": "number"}], "parameter_values": {"least": 350}}))
    assert preview["preview_rows"] and all(row["amount"] >= 350 for row in preview["preview_rows"])


def test_changing_parameters_keeps_unsaved_edits_and_the_revision(world) -> None:
    """Parameters touch no step: the shared copy, with unsaved changes in it, stays, and so does the
    revision a Studio save names. A new recipe can carry its parameters from its first save."""
    recipe = _ok(world["ann"].post(f"{_base(world)}/datasets/{world['orders']['id']}/pipelines", json={
        "name": "Orders", "steps_json": [{"step_type": "limit_rows", "config": {"count": "{{n}}"}}],
        "parameters": [{"name": "n", "kind": "whole number", "default": 2}]}), 201)
    assert recipe["parameters"][0]["default"] == 2
    url = f"{_base(world)}/pipelines/{recipe['id']}"
    copy = _ok(world["ann"].get(f"{url}/shared"))
    after = _ok(world["ann"].put(f"{url}/parameters", json={"parameters": [
        {"name": "n", "kind": "whole number", "default": 3}]}))
    assert after["revision"] == recipe["revision"]
    again = _ok(world["ann"].get(f"{url}/shared"))
    assert again["epoch"] == copy["epoch"] and not again.get("reset_reason")
    assert len(_rows(world, _ok(world["ann"].post(f"{url}/run")))) == 3
    history = _ok(world["ann"].get(f"{_base(world)}/history/pipeline/{recipe['id']}"))
    assert any("Changes its parameters" in (item.get("change_summary") or "") for item in history["items"])
    bad = world["ann"].post(f"{_base(world)}/datasets/{world['orders']['id']}/pipelines", json={
        "name": "Orders", "steps_json": [], "parameters": [{"name": "1st"}]})
    assert bad.status_code in (400, 422) and "starting with a letter" in bad.text


def test_an_undeclared_parameter_is_named(world) -> None:
    recipe = _recipe(world, [{"step_type": "limit_rows", "config": {"count": "{{n}}"}}])
    refused = world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/run")
    assert refused.status_code == 400 and "{{n}}" in refused.text and "Add it under Parameters" in refused.text


def test_saved_templates(world) -> None:
    url = f"{_base(world)}/recipe-templates"
    made = _ok(world["ann"].post(url, json={"name": "Shipped only", "steps_json": [SHIPPED]}), 201)
    assert made["step_count"] == 1
    clash = world["ann"].post(url, json={"name": "Shipped only", "steps_json": [SHIPPED]})
    assert clash.status_code == 400
    assert [item["name"] for item in _ok(world["ann"].get(url))["items"]] == ["Shipped only"]
    assert world["vic"].post(url, json={"name": "Mine", "steps_json": [SHIPPED]}).status_code == 403
    _ok(world["ann"].delete(f"{url}/{made['id']}"), 204)
    assert _ok(world["ann"].get(url))["items"] == []


def test_a_branch_merges_back_what_changed_on_each_side(world) -> None:
    recipe = _recipe(world, [SHIPPED, {"step_type": "sort_rows", "config": {"columns": ["amount"],
                                                                           "ascending": False}}])
    branch = _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/branch", json={}), 201)
    assert branch["branched_from_id"] == recipe["id"] and branch["name"] == "Orders: branch"
    # The branch adds a step; the recipe changes the sort.
    _ok(world["ann"].patch(f"{_base(world)}/pipelines/{branch['id']}", json={
        "steps_json": [*branch["steps_json"], {"step_type": "limit_rows", "config": {"count": 5}}],
        "step_ids": [*branch["step_ids"], "added-on-branch"]}))
    current = _ok(world["ann"].get(f"{_base(world)}/pipelines/{recipe['id']}"))
    changed = [current["steps_json"][0], {"step_type": "sort_rows", "config": {"columns": ["amount"],
                                                                            "ascending": True}}]
    _ok(world["ann"].patch(f"{_base(world)}/pipelines/{recipe['id']}",
                           json={"steps_json": changed, "step_ids": current["step_ids"]}))
    preview = _ok(world["ann"].post(f"{_base(world)}/pipelines/{branch['id']}/merge/preview", json={}))
    assert not preview["applied"] and preview["added"] == 1 and not preview["conflicts"]
    merged = _ok(world["ann"].post(f"{_base(world)}/pipelines/{branch['id']}/merge", json={}))
    assert merged["applied"]
    after = _ok(world["ann"].get(f"{_base(world)}/pipelines/{recipe['id']}"))
    assert [step["step_type"] for step in after["steps_json"]] == ["filter_rows", "sort_rows", "limit_rows"]
    assert after["steps_json"][1]["config"]["ascending"] is True


def test_a_setting_both_sides_changed_is_a_conflict_until_a_side_is_chosen(world) -> None:
    recipe = _recipe(world, [{"step_type": "limit_rows", "config": {"count": 10}}])
    branch = _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/branch", json={"name": "Try 3"}), 201)
    for target, count in ((branch, 3), (recipe, 20)):
        current = _ok(world["ann"].get(f"{_base(world)}/pipelines/{target['id']}"))
        _ok(world["ann"].patch(f"{_base(world)}/pipelines/{target['id']}", json={
            "steps_json": [{"step_type": "limit_rows", "config": {"count": count}}], "step_ids": current["step_ids"]}))
    held = _ok(world["ann"].post(f"{_base(world)}/pipelines/{branch['id']}/merge/preview", json={}))
    assert not held["applied"] and held["conflicts"][0]["what"] == "both changed count"
    refused = world["ann"].post(f"{_base(world)}/pipelines/{branch['id']}/merge", json={})
    assert refused.status_code == 409 and "Say whose side wins" in refused.text
    taken = _ok(world["ann"].post(f"{_base(world)}/pipelines/{branch['id']}/merge", json={"prefer": "branch"}))
    assert taken["applied"]
    after = _ok(world["ann"].get(f"{_base(world)}/pipelines/{recipe['id']}"))
    assert after["steps_json"][0]["config"]["count"] == 3


def test_merging_a_recipe_that_is_not_a_branch_says_so(world) -> None:
    recipe = _recipe(world, [SHIPPED])
    refused = world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/merge", json={})
    assert refused.status_code == 400 and "not a branch" in refused.text


def test_the_same_steps_on_another_dataset_say_what_it_lacks(world) -> None:
    recipe = _recipe(world, [SHIPPED, DROP_STATUS])
    copied = _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/copy",
                                   json={"base_dataset_id": world["customers"]["id"]}), 201)
    assert copied["name"].startswith("Orders on ")
    assert any("status" in warning for warning in copied["warnings"])


def test_one_recipe_per_value(world) -> None:
    recipe = _recipe(world, [DROP_STATUS], name="By status")
    made = _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/split", json={"column": "status",
                                                                                        "values": ["shipped",
                                                                                                   "cancelled"]}),
               201)
    names = [item["name"] for item in made["created"]]
    assert names == ["By status: shipped", "By status: cancelled"]
    recipes = _ok(world["ann"].get(f"{_base(world)}/pipelines"))["items"]
    shipped = next(item for item in recipes if item["name"] == "By status: shipped")
    assert shipped["steps_json"][-1]["config"]["conditions"][0]["value"] == "shipped"
    from_data = _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/split",
                                      json={"column": "region"}), 201)
    # The sample's regions are untidy on purpose (" North ", "north"): one recipe per value as written.
    from pathlib import Path

    import api_gateway

    sample = pd.read_csv(Path(api_gateway.__file__).parent / "sample_data" / "orders.csv")
    assert len(from_data["created"]) == sample["region"].dropna().nunique()


def test_metadata_steps_write_the_output_s_catalogue_entry(world) -> None:
    _ok(world["ann"].post(f"{_base(world)}/glossary", json={"term": "Order value",
                                                           "definition": "What the customer pays."}), 201)
    steps = [
        {"step_type": "tool", "config": {"tool": "meta.describe_column", "column": "amount",
                                         "description": "What the customer pays, in pounds"}},
        {"step_type": "tool", "config": {"tool": "meta.tag_column", "column": "amount", "tags": ["finance", "KPI"]}},
        {"step_type": "tool", "config": {"tool": "meta.classify_column", "column": "customer_id",
                                         "level": "confidential"}},
        {"step_type": "tool", "config": {"tool": "meta.mark_personal", "column": "customer_id",
                                         "kind": "online identifier"}},
        {"step_type": "tool", "config": {"tool": "meta.glossary_term", "column": "amount", "term": "Order value"}},
        {"step_type": "tool", "config": {"tool": "meta.owner", "owner": "nobody"}},
        {"step_type": "tool", "config": {"tool": "meta.describe_dataset", "description": "Orders, cleaned"}},
    ]
    recipe = _recipe(world, steps)
    run = _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/run"))
    output = run["dataset"]["id"]
    entry = _ok(world["ann"].get(f"{_base(world)}/catalog/{output}"))
    assert entry["column_notes"]["amount"] == "What the customer pays, in pounds"
    assert entry["column_tags"]["amount"] == ["finance", "kpi"]
    assert entry["column_classes"]["customer_id"] == {"classification": "confidential",
                                                       "personal": "online identifier"}
    assert entry["description"] == "Orders, cleaned"
    runs = _ok(world["ann"].get(f"{_base(world)}/runs/{run['run']['id']}"))
    assert any("'nobody' as the owner, who is not a user here" in w for w in runs["summary_json"]["warnings"])
    dictionary = world["ann"].get(f"{_base(world)}/catalog/{output}/dictionary")
    assert dictionary.status_code == 200 and "attachment" in dictionary.headers["content-disposition"]
    assert "| amount |" in dictionary.text and "Order value" in dictionary.text and "finance, kpi" in dictionary.text
    as_csv = world["ann"].get(f"{_base(world)}/catalog/{output}/dictionary?format=csv")
    assert pd.read_csv(io.StringIO(as_csv.text)).set_index("column").loc["customer_id", "classification"] == \
        "confidential"


def test_a_thread_on_one_step(world) -> None:
    recipe = _recipe(world, [SHIPPED])
    step = recipe["step_ids"][0]
    made = _ok(world["ann"].post(f"{_base(world)}/discussion", json={
        "target_type": "pipeline", "target_id": recipe["id"], "body": "Why only shipped?", "step_id": step}), 201)
    assert made["step_id"] == step
    wrong = world["ann"].post(f"{_base(world)}/discussion", json={
        "target_type": "pipeline", "target_id": recipe["id"], "body": "x", "step_id": "not-a-step"})
    assert wrong.status_code == 400 and "not in the recipe" in wrong.text
    on_dataset = world["ann"].post(f"{_base(world)}/discussion", json={
        "target_type": "dataset", "target_id": world["orders"]["id"], "body": "x", "step_id": step})
    assert on_dataset.status_code == 400


def test_the_regex_tester_uses_the_engine_s_own_expressions(world) -> None:
    answer = _ok(world["vic"].post("/api/v1/transformations/tools/regex/test", json={
        "pattern": r"(?P<area>[A-Z]{2})-(\d+)", "values": ["GB-12 and FR-3", "none"], "replacement": r"\2"}))
    assert answer["valid"] and answer["results"][0]["spans"] == [[0, 5], [10, 14]]
    assert answer["results"][0]["groups"] == ["GB", "12"] and answer["results"][0]["replaced"] == "12 and 3"
    assert not answer["results"][1]["matched"]
    broken = _ok(world["vic"].post("/api/v1/transformations/tools/regex/test", json={"pattern": "(", "values": []}))
    assert not broken["valid"] and "will not compile" in broken["error"]


def test_a_token_reveals_for_an_administrator_only(world) -> None:
    recipe = _recipe(world, [{"step_type": "tool", "config": {"tool": "privacy.tokenise", "column": "customer_id",
                                                              "key_name": "customers"}}])
    rows = _rows(world, _ok(world["ann"].post(f"{_base(world)}/pipelines/{recipe['id']}/run")))
    token = rows["customer_id"].iloc[0]
    assert token.startswith("tok_")
    revealed = _ok(world["ann"].post("/api/v1/transformations/tokens/reveal",
                                     json={"token": token, "key_name": "customers"}))
    assert revealed["value"].startswith("C1")
    refused = world["vic"].post("/api/v1/transformations/tokens/reveal", json={"token": token, "key_name": "customers"})
    assert refused.status_code == 403


def test_a_viewer_cannot_branch(world) -> None:
    recipe = _recipe(world, [SHIPPED])
    assert world["vic"].post(f"{_base(world)}/pipelines/{recipe['id']}/branch", json={}).status_code == 403
