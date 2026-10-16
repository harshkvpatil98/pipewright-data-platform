"""The Python client and the `pipewright` command line (adoption-readiness A8, Y3).

Run against the real gateway in-process: the generated module must match
the API's OpenAPI document, and the command line must do what its help says.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from pipewright import Client, PipewrightError
from pipewright import cli
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "pipewright"


def _render():
    spec = importlib.util.spec_from_file_location("_generate_under_test", PACKAGE / "_generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.render


def test_the_generated_operations_match_the_api() -> None:
    """Change the API, run `scripts/generate-client.py`; until then this fails."""
    assert _render()(app.openapi()) == (PACKAGE / "_operations.py").read_text()


def test_the_committed_api_reference_is_the_apis() -> None:
    """docs/api/openapi.json is the reference as of this commit (A9, Z3)."""
    spec = importlib.util.spec_from_file_location("_generate_reference", PACKAGE / "_generate.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = PACKAGE.parents[2] / ".." / "docs" / "api" / "openapi.json"
    assert module.reference(app.openapi()) == committed.resolve().read_text()


def test_every_operation_has_a_name_of_its_own() -> None:
    generated = (PACKAGE / "_operations.py").read_text()
    assert generated.count("    def ") > 300
    assert "_2(self" not in generated, "two routes share a function name; give one its own"


@pytest.fixture()
def gateway(tmp_path, monkeypatch):
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
    monkeypatch.setattr(cli, "CONFIG_FILE", tmp_path / "config.json")
    db = factory()
    db.add(User(username="script", password_hash=hash_password("a-long-enough-password"), role="admin", is_active=True))
    db.commit()
    db.close()
    http = TestClient(app)
    token = http.post("/api/v1/auth/login", json={"username": "script", "password": "a-long-enough-password"}).json()["access_token"]
    yield Client("http://testserver", token, http=http)
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_the_client_reads_and_refuses_in_the_apis_words(gateway) -> None:
    project = gateway.post_project(body={"name": "Scripts"})
    assert gateway.get_project(project["id"])["name"] == "Scripts"
    with pytest.raises(PipewrightError) as refused:
        gateway.get_project("00000000-0000-4000-8000-000000000000")
    assert refused.value.status in (403, 404)


def test_the_command_line_does_what_its_help_says(gateway, tmp_path, capsys) -> None:
    run = lambda *argv: cli.main(list(argv), client=gateway)  # noqa: E731

    gateway.post_project(body={"name": "Shop"})
    assert run("projects") == 0
    assert "Shop" in capsys.readouterr().out

    orders = tmp_path / "orders.csv"
    orders.write_text("order_id,amount\n1,10\n2,20\n2,20\n")
    assert run("upload", "Shop", str(orders), "--name", "Orders", "--wait") == 0
    assert run("datasets", "Shop") == 0
    assert "Orders" in capsys.readouterr().out

    project = gateway.project_id("Shop")
    dataset = gateway.dataset_id(project, "Orders")
    gateway._call("POST", f"/api/v1/projects/{project}/datasets/{dataset}/pipelines",
                  body={"name": "Clean orders", "steps_json": [{"step_type": "remove_duplicates", "config": {}}]})
    assert run("run", "recipe", "Shop", "Clean orders", "--wait") == 0
    assert "Finished: succeeded" in capsys.readouterr().err
    assert run("runs", "Shop") == 0
    listed = capsys.readouterr().out
    assert "Recipe run" in listed and "File upload" in listed and "Succeeded" in listed

    target = tmp_path / "out.csv"
    assert run("download", "Shop", "Orders", "-o", str(target)) == 0
    assert target.read_text().splitlines()[0] == "order_id,amount"

    bundle = tmp_path / "shop.json"
    assert run("bundle", "export", "Shop", "-o", str(bundle)) == 0
    assert json.loads(bundle.read_text())["recipes"][0]["name"] == "Clean orders"
    gateway.post_project(body={"name": "Copy"})
    assert run("bundle", "import", "Copy", str(bundle), "--preview") == 0
    assert "left out recipe “Clean orders”" in capsys.readouterr().out  # Copy has no Orders dataset

    assert run("--json", "api", "GET", "/api/v1/projects") == 0
    assert {item["name"] for item in json.loads(capsys.readouterr().out)["items"]} == {"Shop", "Copy"}

    assert run("datasets", "No such project") == 1
    assert "No project called" in capsys.readouterr().err


def test_convert_previews_then_makes_another_tool_s_work(gateway, tmp_path, capsys) -> None:
    run = lambda *argv: cli.main(list(argv), client=gateway)  # noqa: E731

    gateway.post_project(body={"name": "Convert"})
    raw = tmp_path / "raw_orders.csv"
    raw.write_text("id,amount\n1,10\n2,30\n")
    assert run("upload", "Convert", str(raw), "--name", "Raw orders", "--wait") == 0
    dag = tmp_path / "dag.py"
    dag.write_text(
        "from airflow import DAG\n"
        "from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator\n"
        "with DAG('big_orders', schedule='@daily'):\n"
        "    SQLExecuteQueryOperator(task_id='big', sql='CREATE TABLE big AS SELECT id FROM raw.orders "
        "WHERE amount > 20')\n")
    capsys.readouterr()
    assert run("convert", "Convert", str(dag), "--preview") == 0
    out = capsys.readouterr().out
    assert "reads the table raw.orders: choose one with --choose table:raw.orders=DATASET" in out
    assert "Nothing has changed" in out
    assert run("convert", "Convert", str(dag), "--choose", "table:raw.orders=Raw orders") == 0
    out = capsys.readouterr().out
    assert "made: recipe “big”: Made and run" in out and "made: workflow “big_orders”" in out
    assert run("convert", "Convert", str(dag), "--choose", "nonsense") == 1
