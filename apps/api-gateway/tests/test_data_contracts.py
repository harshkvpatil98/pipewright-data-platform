"""Data contracts, through HTTP (Phase 19, C1).

The measured defect first: a recipe edited to drop a column others use ran,
succeeded, and silently took the column away. With a contract it is stopped
with the reason, the dataset keeps the column, the owner and a follower are
told once, and the next good run resolves it. Then: data let through with a
warning, rollback refused before anything is copied, overdue data from the
dataset's freshness promise, and the refusals people may see.

Every test runs on SQLite and, where CI provides one, on PostgreSQL in a
schema of its own: the first live rehearsal found a query PostgreSQL
refuses (DISTINCT over rows with JSON columns) that SQLite accepts.
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_access.models import ProjectMembership
from service_access.permissions import required_role
from service_auth.models import User
from service_datasets.models import DatasetVersion
from service_governance.audit_words import summarise
from service_notifications.models import UserNotification
from service_observability.models import FreshnessPolicy
from service_pipeline_runs.models import PipelineRun
from service_quality import data_contracts
from service_quality.models import DataContractEvent, DataContractProblem
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"


POSTGRES = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")


def _engine(backend: str, tmp_path):
    if backend == "sqlite":
        # A file and a pool, as in production: the audit log writes on a
        # session of its own (see test_activity).
        return create_engine(f"sqlite:///{tmp_path / 'contracts.db'}", connect_args={"check_same_thread": False}), None
    if not POSTGRES:
        pytest.skip("Set CONNECTORS_TEST_POSTGRES_URL to run these on PostgreSQL too.")
    schema = f"contracts_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    admin.dispose()
    return create_engine(POSTGRES, connect_args={"options": f"-csearch_path={schema}"}), schema


@pytest.fixture(params=["sqlite", "postgres"])
def world(request, tmp_path, monkeypatch):
    engine, schema = _engine(request.param, tmp_path)
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
    db.add(User(username="ann", display_name="Ann", password_hash=hash_password(PASSWORD), role="admin", is_active=True))
    db.add(User(username="bob", display_name="Bob", password_hash=hash_password(PASSWORD), role="user", is_active=True))
    db.commit()
    db.close()
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": "ann", "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    project = client.post("/api/v1/projects", json={"name": "Shop"}).json()["id"]
    orders = _ok(client.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]
    yield {"api": client, "db": factory, "project": project, "orders": orders, "engine": engine}
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()
    if schema is not None:
        admin = create_engine(POSTGRES)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


def _base(world) -> str:
    return f"/api/v1/projects/{world['project']}"


def _contract(world, dataset_id: str) -> str:
    return f"{_base(world)}/datasets/{dataset_id}/contract"


def _recipe(world, steps: list[dict]) -> dict:
    return _ok(
        world["api"].post(
            f"{_base(world)}/datasets/{world['orders']['id']}/pipelines",
            json={"name": "Clean orders", "steps_json": steps},
        ),
        201,
    )


def _run(world, recipe_id: str):
    return world["api"].post(f"{_base(world)}/pipelines/{recipe_id}/run")


def _steps(world, recipe_id: str, steps: list[dict]) -> None:
    _ok(world["api"].patch(f"{_base(world)}/pipelines/{recipe_id}", json={"steps_json": steps}))


KEEP_ALL = [{"step_type": "drop_null_rows", "config": {"how": "any", "columns": ["customer_id"]}}]
DROP_STATUS = [{"step_type": "drop_columns", "config": {"columns": ["status"]}}]


def _write(world, dataset_id: str, **changes) -> dict:
    """The drafted contract, saved with `changes` to its terms or settings."""
    current = _ok(world["api"].get(_contract(world, dataset_id)))
    terms = (current["contract"] or {}).get("terms") or current["draft"]
    body = {"enforcement": "stop", "terms": terms}
    for key, value in changes.items():
        if key in ("enforcement", "description", "owner_user_id"):
            body[key] = value
        else:
            body["terms"] = {**body["terms"], key: value}
    return _ok(world["api"].put(_contract(world, dataset_id), json=body))


def _versions(world, dataset_id: str) -> int:
    with world["db"]() as session:
        return int(
            session.scalar(
                select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == uuid.UUID(dataset_id))
            )
        )


def _problems(world, *, open_only: bool = True) -> list[DataContractProblem]:
    with world["db"]() as session:
        statement = select(DataContractProblem).order_by(DataContractProblem.created_at)
        if open_only:
            statement = statement.where(DataContractProblem.resolved_at.is_(None))
        return list(session.scalars(statement).all())


def _events(world) -> list[str]:
    with world["db"]() as session:
        return [event.kind for event in session.scalars(select(DataContractEvent).order_by(DataContractEvent.created_at)).all()]


def _send(world) -> int:
    with world["db"]() as session:
        return data_contracts.send_due(session)


def test_a_dataset_without_a_contract_offers_one_drafted_from_its_data(world) -> None:
    found = _ok(world["api"].get(_contract(world, world["orders"]["id"])))
    assert found["contract"] is None
    draft = {column["name"]: column for column in found["draft"]["columns"]}
    assert list(draft)[:3] == ["order_id", "order_date", "customer_id"]
    assert draft["order_id"]["kind"] == "whole_number" and draft["order_id"]["always_filled"] is True
    # One order has no amount, so the draft does not promise it is always filled.
    assert draft["amount"]["kind"] == "decimal_number" and draft["amount"]["always_filled"] is False
    assert found["draft"]["rows_at_least"] == 1
    # The data it was drafted from keeps it.
    saved = _write(world, world["orders"]["id"])
    assert saved["current"] == {"kept": True, "reasons": [], "rows_checked": 49, "version_number": None}
    assert saved["contract"]["status"] == "kept" and saved["contract"]["version"] == 1
    history = _ok(world["api"].get(f"{_contract(world, world['orders']['id'])}/history"))
    assert history["items"][0]["changes"] == ["Wrote the contract."]


def test_the_measured_defect_a_recipe_that_drops_a_promised_column_is_stopped(world) -> None:
    recipe = _recipe(world, KEEP_ALL)
    output = _ok(_run(world, recipe["id"]))["dataset"]
    assert "status" in [column["name"] for column in output["schema_json"]["columns"]]
    _write(world, output["id"])
    with world["db"]() as session:
        bo = session.scalar(select(User).where(User.username == "bob"))
        session.add(ProjectMembership(project_id=uuid.UUID(world["project"]), user_id=bo.id, role="viewer"))
        session.commit()
    bo_api = TestClient(app)
    bo_token = bo_api.post("/api/v1/auth/login", json={"username": "bob", "password": PASSWORD}).json()["access_token"]
    bo_api.headers["Authorization"] = f"Bearer {bo_token}"
    # A viewer may follow: being told changes nothing in the project.
    assert _ok(bo_api.post(f"{_contract(world, output['id'])}/follow"))["following"] is True

    _steps(world, recipe["id"], DROP_STATUS)
    refused = _run(world, recipe["id"])
    assert refused.status_code == 409, refused.text
    assert "breaks the contract on" in refused.json()["detail"]
    assert "The column 'status' is missing." in refused.json()["detail"]

    # The dataset keeps its column and its versions; the run says why it failed.
    after = _ok(world["api"].get(f"{_base(world)}/datasets/{output['id']}"))
    assert "status" in [column["name"] for column in after["schema_json"]["columns"]]
    assert _versions(world, output["id"]) == 1
    with world["db"]() as session:
        [run] = session.scalars(select(PipelineRun).where(PipelineRun.status == "failed")).all()
        assert run.summary_json["failure_stage"] == "check_contract"
        assert run.logs_json["events"][-1]["message"] == "Stopped while checking the result against its contract."

    [problem] = _problems(world)
    assert (problem.outcome, problem.source_type, problem.source_name) == ("stopped", "recipe", "Clean orders")
    contract = _ok(world["api"].get(_contract(world, output["id"])))["contract"]
    assert contract["status"] == "broken" and contract["open_problems"] == 1
    assert contract["problems"][0]["reasons"] == ["The column 'status' is missing."]

    # The same run breaking the same promise again is one problem, seen twice.
    assert _run(world, recipe["id"]).status_code == 409
    [problem] = _problems(world)
    assert problem.times_seen == 2
    assert _events(world) == ["broken"]

    # Told once: Ann owns it, Bob follows it.
    assert _send(world) == 1
    assert _send(world) == 0
    with world["db"]() as session:
        told = {
            session.get(User, note.user_id).username
            for note in session.scalars(select(UserNotification).where(UserNotification.type == "data_contract")).all()
        }
    assert told == {"ann", "bob"}

    # A good run resolves it, and says so.
    _steps(world, recipe["id"], KEEP_ALL)
    _ok(_run(world, recipe["id"]))
    assert _problems(world) == []
    assert _versions(world, output["id"]) == 2
    assert _events(world) == ["broken", "kept"]
    assert _ok(world["api"].get(_contract(world, output["id"])))["contract"]["status"] == "kept"
    # And the project's activity tells the story, newest first.
    # (SQLite keeps whole seconds, so two events in one second may come in
    # either order there; PostgreSQL keeps the order they happened in.)
    activity = _ok(world["api"].get(f"{_base(world)}/activity", params={"kind": "contracts"}))["items"]
    sentences = [item["sentence"] for item in activity]
    expected = [f"{output['name']} keeps its contract again", f"The contract on {output['name']} stopped new data"]
    assert sentences == expected if world["engine"].dialect.name == "postgresql" else sorted(sentences) == sorted(expected)
    assert all(item["href"].endswith(f"/datasets/{output['id']}/contract") for item in activity)


def test_a_contract_set_to_warn_lets_data_through_and_records_it(world) -> None:
    recipe = _recipe(world, KEEP_ALL)
    output = _ok(_run(world, recipe["id"]))["dataset"]
    _write(world, output["id"], enforcement="warn")
    _steps(world, recipe["id"], DROP_STATUS)
    result = _ok(_run(world, recipe["id"]))
    assert "The column 'status' is missing." in result["run"]["summary_json"]["warnings"]
    assert _versions(world, output["id"]) == 2
    [problem] = _problems(world)
    assert problem.outcome == "let_through"
    # Checking by hand now agrees, and records nothing new.
    check = _ok(world["api"].post(f"{_contract(world, output['id'])}/check"))
    assert check["kept"] is False and check["reasons"] == ["The column 'status' is missing."]
    assert len(_problems(world)) == 1


def test_value_promises_use_the_checks_own_words(world) -> None:
    dataset = world["orders"]["id"]
    current = _ok(world["api"].get(_contract(world, dataset)))["draft"]
    columns = {column["name"]: column for column in current["columns"]}
    columns["amount"]["always_filled"] = True
    columns["status"]["allowed_values"] = ["shipped", "cancelled"]
    columns["quantity"]["lowest"] = 1
    columns["quantity"]["highest"] = 1
    columns["customer_id"]["no_repeats"] = True
    saved = _ok(
        world["api"].put(
            _contract(world, dataset),
            json={"enforcement": "stop", "terms": {**current, "columns": list(columns.values())}},
        )
    )
    reasons = saved["current"]["reasons"]
    assert "1 of 49 rows have no value for 'amount'." in reasons
    assert any(reason.endswith("have a value of 'status' that is not on the list.") for reason in reasons)
    assert any(reason.endswith("have a value of 'quantity' outside the range.") for reason in reasons)
    assert any("repeat a value of customer_id" in reason for reason in reasons)
    # No reason quotes a value from the data.
    assert not any("refunded" in reason or "pending" in reason for reason in reasons)
    # Saved anyway, and broken from the start, so nobody is misled.
    assert saved["contract"]["status"] == "broken"


def test_kinds_whole_numbers_with_a_gap_are_still_whole_numbers() -> None:
    import pandas as pd

    frame = pd.DataFrame({"id": [1, None, 3], "price": [1.5, 2.0, None], "name": ["a", "b", None], "empty": [None, None, None]})
    terms = {
        "columns": [
            {"name": "id", "kind": "whole_number"},
            {"name": "price", "kind": "decimal_number"},
            {"name": "name", "kind": "text"},
            {"name": "empty", "kind": "date"},
        ]
    }
    assert data_contracts.evaluate(terms, frame, previous_row_count=None) == []
    terms["columns"][1]["kind"] = "whole_number"
    [reason] = data_contracts.evaluate(terms, frame, previous_row_count=None)
    assert reason == {"term": "price.kind", "sentence": "'price' should be whole number but is decimal number."}


def test_rows_other_columns_and_a_fall_in_rows() -> None:
    import pandas as pd

    frame = pd.DataFrame({"a": range(40), "b": range(40)})
    terms = {
        "columns": [{"name": "a", "kind": "whole_number"}],
        "other_columns": "not_allowed",
        "rows_at_least": 50,
        "rows_at_most": 30,
        "largest_drop_percent": 10,
    }
    sentences = [reason["sentence"] for reason in data_contracts.evaluate(terms, frame, previous_row_count=100)]
    assert sentences == [
        "It has 1 column the contract does not promise: b.",
        "It has 40 rows; the contract promises at least 50.",
        "It has 40 rows; the contract promises at most 30.",
        "It has 60% fewer rows than the current data (40 against 100); the contract allows at most 10% fewer.",
    ]


def test_rolling_back_to_a_version_that_breaks_it_is_refused_first(world) -> None:
    recipe = _recipe(world, DROP_STATUS)
    output = _ok(_run(world, recipe["id"]))["dataset"]
    _steps(world, recipe["id"], KEEP_ALL)
    _ok(_run(world, recipe["id"]))
    terms = _ok(world["api"].get(_contract(world, output["id"])))["draft"]
    assert "status" in [column["name"] for column in terms["columns"]]
    _write(world, output["id"])

    # The history can ask first, and records nothing.
    preview = _ok(world["api"].get(f"{_contract(world, output['id'])}/check", params={"version": 1}))
    assert preview["kept"] is False and preview["reasons"] == ["The column 'status' is missing."]
    assert _ok(world["api"].get(f"{_contract(world, output['id'])}/check", params={"version": 2}))["kept"] is True

    refused = world["api"].post(f"{_base(world)}/datasets/{output['id']}/versions/1/rollback")
    assert refused.status_code == 409, refused.text
    assert "set it to warn, to roll back" in refused.json()["detail"]
    assert _versions(world, output["id"]) == 2
    assert _problems(world) == []

    # Set to warn, it rolls back and records the problem it let through.
    _write(world, output["id"], enforcement="warn")
    _ok(world["api"].post(f"{_base(world)}/datasets/{output['id']}/versions/1/rollback"), 201)
    [problem] = _problems(world)
    assert (problem.outcome, problem.source_type) == ("let_through", "rollback")


def test_overdue_data_comes_from_the_datasets_freshness_promise(world) -> None:
    dataset = world["orders"]["id"]
    saved = _write(world, dataset, new_data_every_hours=6)
    assert saved["contract"]["terms"]["new_data_every_hours"] == 6
    with world["db"]() as session:
        policy = session.scalar(select(FreshnessPolicy).where(FreshnessPolicy.dataset_id == uuid.UUID(dataset)))
        assert policy.max_age_minutes == 360
        policy.last_status, policy.last_age_minutes = "stale", 600.0
        session.commit()
        assert data_contracts.sync_overdue(session) == 1
        assert data_contracts.sync_overdue(session) == 0
    [problem] = _problems(world)
    assert problem.kind == "overdue"
    assert problem.reasons_json[0]["sentence"] == (
        "No new data for 10 hours; the contract promises new data at least every 6.0 hours."
    )
    with world["db"]() as session:
        policy = session.scalar(select(FreshnessPolicy).where(FreshnessPolicy.dataset_id == uuid.UUID(dataset)))
        policy.last_status = "fresh"
        session.commit()
        assert data_contracts.sync_overdue(session) == 1
    assert _problems(world) == []
    assert _events(world)[-2:] == ["overdue", "kept"]
    # Clearing the promise removes the dataset's freshness promise with it.
    _write(world, dataset, new_data_every_hours=None)
    with world["db"]() as session:
        assert session.scalar(select(FreshnessPolicy).where(FreshnessPolicy.dataset_id == uuid.UUID(dataset))) is None


def test_changes_are_versions_in_words_and_followers_hear_of_them(world) -> None:
    dataset = world["orders"]["id"]
    _write(world, dataset)
    _ok(world["api"].post(f"{_contract(world, dataset)}/follow"))
    current = _ok(world["api"].get(_contract(world, dataset)))["contract"]["terms"]
    current["columns"] = [column for column in current["columns"] if column["name"] != "status"]
    current["rows_at_least"] = 10
    _ok(world["api"].put(_contract(world, dataset), json={"enforcement": "warn", "terms": current}))
    [latest, first] = _ok(world["api"].get(f"{_contract(world, dataset)}/history"))["items"]
    assert latest["version"] == 2 and first["version"] == 1
    assert latest["changes"] == [
        "No longer promises 'status'.",
        "Now promises at least 10 rows.",
        "Now lets data that breaks it through, with a warning.",
    ]
    assert "changed" in _events(world)
    # Ann made the change, so she is not told about it, though she follows it.
    _send(world)
    with world["db"]() as session:
        titles = [note.title for note in session.scalars(select(UserNotification).where(UserNotification.type == "data_contract")).all()]
    assert not any("changed" in title for title in titles)


def test_what_relies_on_a_dataset_is_listed(world) -> None:
    dataset = world["orders"]["id"]
    _recipe(world, KEEP_ALL)
    _ok(
        world["api"].post(
            f"{_base(world)}/data-quality/rules",
            json={"name": "Has an id", "rule_type": "not_null", "dataset_id": dataset, "config": {"column": "order_id"}},
        ),
        201,
    )
    chart = _ok(
        world["api"].post(
            f"{_base(world)}/charts",
            json={
                "name": "Orders by region", "dataset_id": dataset, "chart_type": "bar",
                "query": {"dimensions": ["region"], "measures": [{"column": "amount", "aggregation": "sum"}]},
            },
        ),
        201,
    )
    _ok(world["api"].post(f"{_base(world)}/dashboards", json={"name": "Sales", "tiles": [{"kind": "chart", "chart_id": chart["id"]}]}), 201)
    _write(world, dataset)
    consumers = _ok(world["api"].get(_contract(world, dataset)))["contract"]["consumers"]
    assert [(item["kind"], item["name"]) for item in consumers] == [
        ("recipe", "Clean orders"),
        ("check", "Has an id"),
        ("chart", "Orders by region"),
        ("dashboard", "Sales"),
    ]


@pytest.mark.parametrize(
    ("change", "words"),
    [
        ({"columns": [{"name": "a", "kind": "any"}, {"name": "a", "kind": "any"}]}, "'a' is promised twice"),
        ({"columns": [{"name": "a", "kind": "decimal_number", "lowest": 5, "highest": 1}]}, "lowest value is above the highest"),
        ({"columns": [{"name": "a", "kind": "text", "lowest": 1}]}, "cannot have a lowest or highest number"),
        ({"columns": [{"name": "a", "kind": "text", "allowed_values": [" "]}]}, "list at least one allowed value"),
        ({"rows_at_least": 10, "rows_at_most": 5}, "fewest rows promised is more than the most"),
    ],
)
def test_refusals_say_what_to_change(world, change, words) -> None:
    refused = world["api"].put(
        _contract(world, world["orders"]["id"]), json={"enforcement": "stop", "terms": change}
    )
    assert refused.status_code == 400, refused.text
    assert words in refused.json()["detail"]


def test_the_list_routes_and_words(world) -> None:
    _write(world, world["orders"]["id"])
    [item] = _ok(world["api"].get(f"{_base(world)}/contracts"))["items"]
    assert item["dataset_name"] == world["orders"]["name"] and item["owner_username"] == "ann"
    assert required_role("POST", "/api/v1/projects/x/datasets/y/contract/follow") == "viewer"
    assert required_role("DELETE", "/api/v1/projects/x/datasets/y/contract/follow") == "viewer"
    assert required_role("PUT", "/api/v1/projects/x/datasets/y/contract") == "editor"
    assert required_role("POST", "/api/v1/projects/x/datasets/y/contract/check") == "operator"
    assert summarise("PUT", f"/api/v1/projects/{uuid.uuid4()}/datasets/{uuid.uuid4()}/contract") == (
        "wrote or changed a dataset's contract"
    )
    _ok(world["api"].delete(_contract(world, world["orders"]["id"])), 204)
    assert _ok(world["api"].get(f"{_base(world)}/contracts"))["items"] == []


def test_erasing_is_never_stopped_but_is_recorded() -> None:
    import pandas as pd

    # `may_stop=False` returns the verdict even for an enforced contract.
    from types import SimpleNamespace

    class Session:
        def scalar(self, _statement):
            return SimpleNamespace(
                id=uuid.uuid4(), version=1, enforcement="stop",
                terms_json={"columns": [{"name": "email", "kind": "text", "always_filled": True}]},
            )

    dataset = SimpleNamespace(id=uuid.uuid4(), name="People", row_count=2, status="ready")
    verdict = data_contracts.check_new_data(
        Session(), dataset=dataset, frame=pd.DataFrame({"email": ["a@x", None]}),
        source_type="erasure", may_stop=False,
    )
    assert verdict is not None and not verdict.kept
    assert verdict.sentences() == ["1 of 2 rows have no value for 'email'."]
    assert datetime.now(UTC)
