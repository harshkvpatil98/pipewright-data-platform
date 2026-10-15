"""Plugins through the gateway (Phase 23, X1).

A plugin written outside the repository, in a folder of its own, adds a tool,
a formula function, a chart type and two connectors (one written in Python,
one a REST manifest); each works where Pipewright's own do, and passes the
suites they pass. A plugin that fails any check is refused with its reason
and leaves nothing behind; one that is installed and not enabled is never
imported.
"""

from __future__ import annotations

import pathlib
import textwrap

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies, plugins
from api_gateway.config import settings
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_auth.models import User
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"

GOOD = '''
from pipewright_plugin_sdk import (ChartType, Connector, Example, Field, Function, Mark, Param, Plugin,
                                   RestManifest, Tool)


class Weather(Connector):
    name = "weather"
    label = "Acme weather"
    description = "Readings from Acme's weather stations."
    category = "api"
    fields = (Field("station", "Station"),)

    def test(self, config):
        return (config.get("station") == "kew", "Reached the Kew station." if config.get("station") == "kew"
                else "No such station.")

    def streams(self, config):
        return ["readings"]

    def read(self, config, stream, limit):
        for hour in range(min(limit, 24)):
            yield {"hour": hour, "celsius": 10 + hour / 2}


plugin = Plugin(
    name="acme",
    version="1.2.0",
    publisher="Acme Ltd",
    description="Acme's everyday tools.",
    tools=(Tool(name="shout", title="Shout", summary="Capitals and an exclamation mark.",
                transform=lambda value, settings: str(value).upper() + (settings.get("mark") or "!"),
                accepts="text", returns="text", params=(Param("mark", "Ends with", required=False, default="!"),),
                example=Example(values=("hi", "ok"), expect=("HI!", "OK!"))),),
    functions=(Function(name="acme_double", summary="Twice the number.", implementation=lambda x: x * 2,
                        returns="number", examples=(((2,), 4),)),),
    chart_types=(ChartType(name="lollipop", label="Lollipop", description="A stem and a dot for each category.",
                           marks=(Mark("rule"), Mark("point", size=5))),),
    connectors=(Weather(), RestManifest({
        "key": "acme_status", "label": "Acme status", "description": "Acme's status page components.",
        "category": "api", "base_url": "https://status.acme.example/api", "auth": {"kind": "none"},
        "streams": [{"name": "components", "path": "/components", "records_path": "components"}]})),
)
'''


def _plugin_folder(root: pathlib.Path, name: str, body: str) -> pathlib.Path:
    folder = root / name
    folder.mkdir(parents=True)
    (folder / "plugin.py").write_text(textwrap.dedent(body), encoding="utf-8")
    return folder


def _client(username: str) -> TestClient:
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json()


@pytest.fixture()
def world(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'plugins.db'}", connect_args={"check_same_thread": False})
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
        db.add(User(username="vic", password_hash=hash_password(PASSWORD), role="user", is_active=True))
        db.commit()
    # Outside the repository: a folder of its own, as a customer's plugin is.
    folders = tmp_path / "plugins"
    folders.mkdir()
    monkeypatch.setattr(settings, "plugins_path", str(folders))
    plugins.unload_all()

    def load(enabled: str) -> list[plugins.PluginStatus]:
        plugins.unload_all()
        monkeypatch.setattr(settings, "plugins_enabled", enabled)
        return plugins.load_enabled(settings)

    yield {"folders": folders, "load": load, "ann": _client("ann"), "vic": _client("vic")}
    plugins.unload_all()
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _status(statuses, name):
    return next(status for status in statuses if status.name == name)


def test_a_plugin_from_outside_adds_a_tool_a_function_a_chart_type_and_connectors(world) -> None:
    _plugin_folder(world["folders"], "acme", GOOD)
    status = _status(world["load"]("acme"), "acme")
    assert status.state == "loaded", status.reason
    assert {c["kind"] for c in status.contributions} == {"tool", "function", "chart type", "connector"}
    suites = {check["suite"] for check in status.checks}
    assert {"the plugin SDK", "the tool library's structural checks", "the function catalogue's checks",
            "the chart validator", "the connector conformance suite"} <= suites
    assert all(check["passed"] for check in status.checks)

    ann = world["ann"]
    project = _ok(ann.post("/api/v1/projects", json={"name": "Shop"}), 201)["id"]
    orders = _ok(ann.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]
    # The tool: found by search, previewed and run like any.
    found = _ok(ann.get("/api/v1/transformations/tools", params={"query": "shout"}))["items"]
    assert found[0]["name"] == "acme.shout" and found[0]["category"] == "From plugins"
    steps = [{"step_type": "tool", "config": {"tool": "acme.shout", "column": "status", "mark": "?"}},
             {"step_type": "derive_column", "config": {"target_column": "twice", "formula": "ACME_DOUBLE([amount])"}}]
    preview = _ok(ann.post(f"/api/v1/projects/{project}/datasets/{orders['id']}/pipelines/preview",
                           json={"steps": steps}))
    row = preview["preview_rows"][0]
    assert row["status"] == "SHIPPED?" and row["twice"] == 798.0
    recipe = _ok(ann.post(f"/api/v1/projects/{project}/datasets/{orders['id']}/pipelines",
                          json={"name": "Loud orders", "steps_json": steps}), 201)
    run = _ok(ann.post(f"/api/v1/projects/{project}/pipelines/{recipe['id']}/run"))
    assert run["run"]["status"] == "succeeded"
    # The chart type: in the builder's list with its marks, and drawn from a query.
    types = {item["name"]: item for item in _ok(ann.get("/api/v1/charts/types"))["items"]}
    assert types["acme_lollipop"]["plugin"] == "acme"
    assert [mark["kind"] for mark in types["acme_lollipop"]["declared"]["marks"]] == ["rule", "point"]
    chart = _ok(ann.post(f"/api/v1/projects/{project}/charts/preview", json={
        "dataset_id": orders["id"], "chart_type": "acme_lollipop",
        "query": {"dimensions": ["region"], "measures": [{"column": "amount", "aggregation": "sum"}]}}))
    assert chart["chart_type"] == "acme_lollipop" and chart["labels"] and chart["series"]
    # The connectors: in the catalogue, not yet tested here, and the Python one tests and reads.
    catalogue = {item["type"]: item for item in _ok(ann.get("/api/v1/connectors"))["items"]}
    assert catalogue["acme_weather"]["tier"] == 4 and catalogue["acme_status"]["tier"] == 4
    tested = _ok(ann.post("/api/v1/connectors/test", json={"connector_type": "acme_weather",
                                                          "config": {"station": "kew"}}))
    assert tested["success"] is True and tested["message"].startswith("Reached the Kew station.")
    streams = _ok(ann.post("/api/v1/connectors/acme_weather/streams", json={"connector_type": "acme_weather",
                                                                            "config": {"station": "kew"}}))
    assert [item["name"] for item in streams["items"]] == ["readings"]
    # Administration lists it; nobody else sees it.
    listed = _ok(ann.get("/api/v1/plugins"))
    assert listed["sdk"] == 1 and _status_dict(listed, "acme")["state"] == "loaded"
    assert world["vic"].get("/api/v1/plugins").status_code == 403


def _status_dict(listed, name):
    return next(item for item in listed["items"] if item["name"] == name)


def test_a_plugin_that_fails_a_check_is_refused_and_leaves_nothing(world) -> None:
    from service_connectors import registry
    from service_reporting.charts import CHART_TYPES_BY_NAME
    from service_transformations.ir.expressions import FUNCTIONS
    from service_transformations.tools import TOOLS

    wrong_example = GOOD.replace('expect=("HI!", "OK!")', 'expect=("HI!", "NO!")').replace('name="acme"', 'name="wrong"')
    _plugin_folder(world["folders"], "wrong", wrong_example)
    # Passes the SDK's checks; its manifest is refused by the catalogue's own manifest rules.
    bad_manifest = GOOD.replace('"auth": {"kind": "none"}', '"auth": {"kind": "telepathy"}').replace(
        'name="acme"', 'name="late"').replace("acme_status", "late_status")
    _plugin_folder(world["folders"], "late", bad_manifest)
    clash = GOOD.replace('name="acme_double"', 'name="upper"').replace('name="acme"', 'name="clash"').replace(
        "acme_status", "clash_status")
    _plugin_folder(world["folders"], "clash", clash)
    statuses = world["load"]("wrong,late,clash")

    wrong = _status(statuses, "wrong")
    assert wrong.state == "refused" and "tool wrong.shout does not pass: its example gives what it says" in wrong.reason
    assert "'ok' gave 'OK!', not 'NO!'" in wrong.reason
    late = _status(statuses, "late")
    assert late.state == "refused" and "auth.kind" in late.reason
    clashed = _status(statuses, "clash")
    assert clashed.state == "refused" and "UPPER is a function Pipewright has already" in clashed.reason
    # Nothing of any of them is left: the late one's tool, function and chart were added before its manifest.
    for prefix in ("wrong", "late", "clash"):
        assert not [name for name in TOOLS if name.startswith(f"{prefix}.")]
        assert f"{prefix}_lollipop" not in CHART_TYPES_BY_NAME
        assert not [name for name in registry.known_types() if name.startswith(f"{prefix}_")]
    assert "upper" in FUNCTIONS and FUNCTIONS["upper"].sql, "the built-in UPPER is untouched"
    assert "acme_double" not in FUNCTIONS


def test_a_plugin_installed_but_not_enabled_is_listed_and_never_imported(world) -> None:
    marker = world["folders"] / "imported.txt"
    _plugin_folder(world["folders"], "quiet", f"open({str(marker)!r}, 'w').write('imported')\n" + GOOD.replace(
        'name="acme"', 'name="quiet"'))
    statuses = world["load"]("")
    quiet = _status(statuses, "quiet")
    assert quiet.state == "not enabled" and "PLUGINS_ENABLED" in quiet.reason
    assert not marker.exists()


def test_what_is_named_and_not_there_or_not_itself_is_refused(world) -> None:
    _plugin_folder(world["folders"], "renamed", GOOD)  # calls itself acme
    _plugin_folder(world["folders"], "future", GOOD.replace('name="acme"', 'name="future", sdk=2'))
    _plugin_folder(world["folders"], "broken", "import nowhere_to_be_found\n")
    statuses = world["load"]("renamed,future,broken,ghost")
    assert "installed as renamed but calls itself acme" in _status(statuses, "renamed").reason
    assert "written for SDK 2" in _status(statuses, "future").reason
    assert "could not be imported: ModuleNotFoundError" in _status(statuses, "broken").reason
    ghost = _status(statuses, "ghost")
    assert ghost.state == "not found" and "PLUGINS_PATH" in ghost.reason
    assert all(status.state != "loaded" for status in statuses)
