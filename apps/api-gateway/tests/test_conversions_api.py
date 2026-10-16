"""Converting a dbt project through the API, into a real project (E2, X3).

The preview changes nothing and says what the import will make; the import
makes the seeds, the recipes (run, in order), the checks (run) and the
workflow through each service, and the recipes' results are the rows SQLite
gives for the models. Running the workflow builds it all again, as dbt
build does. A second import skips what is already there, a viewer may look
but not import, and every audited route says what it did.
"""

from __future__ import annotations

import io
import json

import pandas as pd
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

from conversion_harness import dbt_project_zip, dbt_sqlite_model, sorted_rows

PASSWORD = "a-long-enough-password"


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'convert.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    storage = LocalStorageBackend(str(tmp_path / "storage"))
    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(dependencies, "storage_backend", storage)
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with factory() as db:
        db.add(User(username="ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
        db.add(User(username="vic", password_hash=hash_password(PASSWORD), role="viewer", is_active=True))
        db.commit()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "ann", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    project = _ok(client.post("/api/v1/projects", json={"name": "Shop"}), 201)["id"]
    segments = b"customer_id,segment\n1,gold\n2,silver\n3,gold\n4,bronze\n"
    _ok(client.post(f"/api/v1/projects/{project}/datasets/upload", params={"dataset_name": "crm_segments"},
                    files={"file": ("crm_segments.csv", segments, "text/csv")}), 201)
    yield {"client": client, "project": project, "factory": factory, "storage": storage}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _upload(mapping: dict | None = None):
    data = {"mapping": json.dumps(mapping)} if mapping else {}
    return {"files": {"file": ("shop.zip", dbt_project_zip(), "application/zip")}, "data": data}


def _rows_of(client, project: str, dataset_id: str) -> pd.DataFrame:
    response = client.get(f"/api/v1/projects/{project}/datasets/{dataset_id}/download")
    assert response.status_code == 200, response.text
    return pd.read_csv(io.BytesIO(response.content), keep_default_na=False, na_values=[""])


def test_the_preview_changes_nothing_and_says_what_it_will_make(world) -> None:
    client, project = world["client"], world["project"]
    preview = _ok(client.post(f"/api/v1/projects/{project}/conversions/preview", **_upload()))
    assert preview["format"] == "dbt" and preview["title"] == "the dbt project shop"
    assert [(n["name"], n["status"]) for n in preview["needs"]] == [("crm_segments", "matched")]
    assert {s["name"] for s in preview["seeds"]} == {"raw_customers", "raw_orders", "raw_payments", "country_codes"}
    assert {"stg_orders", "customers", "orders", "big_orders"} <= {r["name"] for r in preview["recipes"]}
    assert preview["counts"]["not_converted"] >= 5
    assert not _ok(client.get(f"/api/v1/projects/{project}/pipelines"))["items"]


def test_the_import_makes_and_runs_it_all_and_the_rows_are_the_warehouse_s(world) -> None:
    client, project = world["client"], world["project"]
    result = _ok(client.post(f"/api/v1/projects/{project}/conversions", **_upload()))
    made = {(item["kind"], item["name"]): item for item in result["made"]}
    failed = [item for item in result["made"] if item["status"] == "failed"]
    assert not failed, failed
    assert made[("dataset", "raw_orders")]["status"] == "made"
    for name in ("stg_customers", "stg_orders", "stg_payments", "orders", "customers", "big_orders",
                 "customers · customer_payments"):
        assert made[("recipe", name)]["status"] == "made" and "Made and run" in made[("recipe", name)]["detail"]
    checks = [item for item in result["made"] if item["kind"] == "check"]
    assert checks and all("it passes" in item["detail"] for item in checks), checks
    assert made[("workflow", "dbt build: shop")]["status"] == "made"

    # Each model's result, read back from the platform, is what SQLite gives for the model.
    pipelines = {p["name"]: p for p in _ok(client.get(f"/api/v1/projects/{project}/pipelines"))["items"]}
    for model in ("stg_orders", "orders", "customers", "big_orders"):
        output = pipelines[model]["output_dataset_id"]
        ours, theirs = _rows_of(client, project, output), dbt_sqlite_model(model)
        assert list(ours.columns) == list(theirs.columns), model
        assert sorted_rows(ours) == sorted_rows(theirs.astype(ours.dtypes.to_dict(), errors="ignore")), model

    # The var is a parameter of its recipe, with dbt's default.
    big = _ok(client.get(f"/api/v1/projects/{project}/pipelines/{pipelines['big_orders']['id']}"))
    assert big["parameters"] == [{"name": "min_order_amount", "label": "Min order amount", "kind": "whole number",
                                  "default": 15, "description": None}]


def test_the_workflow_builds_it_again_as_dbt_build_does(world) -> None:
    from service_workflows.queue import run_next

    client, project = world["client"], world["project"]
    result = _ok(client.post(f"/api/v1/projects/{project}/conversions", **_upload()))
    workflow = next(item for item in result["made"] if item["kind"] == "workflow")
    _ok(client.post(f"/api/v1/projects/{project}/workflows/{workflow['id']}/run"), 202)
    with world["factory"]() as db:
        run = run_next(db, storage_backend=world["storage"], settings=dependencies.settings)
        assert run is not None
        assert run.status == "succeeded", [(n.node_key, n.status, n.message) for n in run.node_runs]
        assert run.nodes_failed == 0 and run.nodes_skipped == 0 and run.nodes_succeeded == run.nodes_total


def test_a_second_import_skips_what_is_already_there(world) -> None:
    client, project = world["client"], world["project"]
    _ok(client.post(f"/api/v1/projects/{project}/conversions", **_upload()))
    again = _ok(client.post(f"/api/v1/projects/{project}/conversions", **_upload()))
    by_kind = {}
    for item in again["made"]:
        by_kind.setdefault(item["kind"], set()).add(item["status"])
    assert by_kind["dataset"] == {"used"}
    assert by_kind["recipe"] == {"skipped"} and by_kind["check"] == {"skipped"}
    assert by_kind["workflow"] == {"skipped"}


def test_a_dataset_it_reads_can_be_chosen(world) -> None:
    client, project = world["client"], world["project"]
    datasets = _ok(client.get(f"/api/v1/projects/{project}/datasets"))
    segments = next(d for d in (datasets.get("items") or datasets) if d["name"] == "crm_segments")
    _ok(client.patch(f"/api/v1/projects/{project}/datasets/{segments['id']}", json={"name": "Customer segments"}))
    missing = _ok(client.post(f"/api/v1/projects/{project}/conversions/preview", **_upload()))
    assert missing["needs"][0]["status"] == "missing" and "choose" in missing["needs"][0]["reason"]
    # The source's .yml names its columns, so the model converts from them; it waits for the dataset.
    entries = {e["subject"]: e for s in missing["sections"] for e in s["entries"]}
    assert entries["model customers"]["status"] == "converted"
    skipped = _ok(client.post(f"/api/v1/projects/{project}/conversions", **_upload()))
    customers = next(item for item in skipped["made"] if item["name"] == "customers")
    assert customers["status"] == "skipped" and "no dataset here is chosen" in customers["detail"]
    chosen = _ok(client.post(f"/api/v1/projects/{project}/conversions/preview",
                             **_upload({"source:crm.segments": segments["id"]})))
    assert chosen["needs"][0]["status"] == "chosen" and chosen["needs"][0]["dataset_name"] == "Customer segments"


def test_a_viewer_may_look_but_not_import(world) -> None:
    client, project = world["client"], world["project"]
    _ok(client.post(f"/api/v1/projects/{project}/members", json={"username": "vic", "role": "viewer"}), 201)
    viewer = TestClient(app)
    token = viewer.post("/api/v1/auth/login", json={"username": "vic", "password": PASSWORD}).json()["access_token"]
    viewer.headers["Authorization"] = f"Bearer {token}"
    _ok(viewer.post(f"/api/v1/projects/{project}/conversions/preview", **_upload()))
    refused = viewer.post(f"/api/v1/projects/{project}/conversions", **_upload())
    assert refused.status_code == 403, refused.text


def test_a_file_it_does_not_convert_is_refused_with_what_it_does(world) -> None:
    client, project = world["client"], world["project"]
    response = client.post(f"/api/v1/projects/{project}/conversions/preview",
                           files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400 and "a dbt project" in response.json()["detail"]
    formats = _ok(client.get("/api/v1/conversions/formats"))
    assert formats[0]["key"] == "dbt"


# Every format, imported into a real project: each recipe runs, and its result,
# read back from the platform, is the rows the same recipe gives here.
FORMATS = {
    "airflow": ("airflow/orders_daily.py", {"orders": "id,customer_id,status,amount,order_date\n1,10,paid,1250,2026-01-01\n"
                                                      "2,11,test,990,2026-01-01\n3,10,paid,300,2026-01-02\n"}),
    "alteryx": ("alteryx/region_totals.yxmd", {"orders": "order_id,customer,region,amount,status,order_date\n"
                                                         "1,ann,North,120.5,paid,2026-01-02\n2,bo,South,80,paid,2026-01-02\n"
                                                         "3,cy,,45,paid,2026-01-03\n4,ann,North,200,test,2026-01-03\n"}),
    "informatica": ("informatica/m_orders.xml", {
        "ORDERS": "order_id,customer_id,amount,status,region\n1,10,150,paid,North\n2,11,80,paid,South\n4,99,120,paid,\n",
        "CUSTOMERS": "customer_id,name\n10,Ann\n11,Bo\n"}),
    "ssis": ("ssis/LoadOrders.dtsx", {
        "orders": "order_id,customer_id,amount,status,region\n1,10,150,paid,North\n2,11,80,paid,South\n3,12,0,refunded,\n",
        "customers": "customer_id,name,active\n10,Ann,1\n11,Bo,0\n12,Cy,1\n"}),
    "talend": ("talend/orders_job_0.1.item", {
        "orders": "order_id,customer_id,amount,status,region\n1,10,150,paid,North\n2,11,80,paid,South\n5,13,60,refund,\n",
        "customers": "customer_id,name\n10,Ann\n11,Bo\n10,Annabel\n"}),
    "power_query": ("power_query/sales.pq", {
        "customers": "customer_id,name,tier\n1,Ann,gold\n2,Bo,silver\n3,Cy,\n",
        "Orders": "order_id,customer_id,amount,status\n10,1,120,shipped\n11,2,40,shipped\n12,3,75.5,returned\n"}),
}


@pytest.mark.parametrize("format_key", sorted(FORMATS))
def test_every_format_imports_and_its_recipes_give_what_they_give_here(world, format_key: str) -> None:
    from pathlib import Path

    from api_gateway.conversions import formats
    from api_gateway.conversions.apply import Resolver
    from conversion_harness import rows as plain_rows
    from conversion_harness import run_recipes
    from service_ingestion.read_copy import parse as parse_file

    client, project = world["client"], world["project"]
    path, datasets = FORMATS[format_key]
    fixture = Path(__file__).parent / "fixtures" / "conversions" / path
    frames = {}
    for name, text in datasets.items():
        _ok(client.post(f"/api/v1/projects/{project}/datasets/upload", params={"dataset_name": name},
                        files={"file": (f"{name}.csv", text.encode(), "text/csv")}), 201)
        frames[name] = parse_file(text.encode(), file_type="csv", spec=None)
    upload = {"file": (fixture.name, fixture.read_bytes(), "application/octet-stream")}
    preview = _ok(client.post(f"/api/v1/projects/{project}/conversions/preview", files=upload))
    assert preview["format"] == format_key
    assert all(need["status"] == "matched" for need in preview["needs"]), preview["needs"]
    result = _ok(client.post(f"/api/v1/projects/{project}/conversions", files=upload))
    failed = [item for item in result["made"] if item["status"] == "failed"]
    assert not failed, failed
    recipes = [item for item in result["made"] if item["kind"] == "recipe" and item["status"] == "made"]
    assert recipes

    # The same conversion run here, on the same rows as the platform read them.
    with world["factory"]() as db:
        from service_auth.models import User
        from service_auth.schemas import UserRead

        user = UserRead.model_validate(db.query(User).filter_by(username="ann").one(), from_attributes=True)
        resolver = Resolver(db, __import__("uuid").UUID(project), user, {})
        conversion = formats()[format_key].convert({fixture.name: fixture.read_bytes()}, resolver)
        here = run_recipes(conversion, {key: frames[found[1].name] for key, found in resolver.found.items()
                                        if found[1] is not None})
    pipelines = {p["id"]: p for p in _ok(client.get(f"/api/v1/projects/{project}/pipelines"))["items"]}
    for item in recipes:
        if "draft" in (item["detail"] or ""):
            continue
        output = pipelines[item["id"]]["output_dataset_id"]
        theirs = _rows_of(client, project, output)
        ours = here[item["key"]]
        assert list(theirs.columns) == list(ours.columns), item["name"]
        normal = lambda frame: sorted((tuple("" if v is None else str(v).removesuffix(".0") for v in row)  # noqa: E731
                                       for row in plain_rows(frame)), key=repr)
        assert normal(theirs) == normal(ours), item["name"]
