"""Live sources (D1): reading, storing once, saving, tables kept current, live recipes.

Runs on SQLite with no network: a fake kind stands in for a source, so the
lifecycle (position saved with the events, acknowledged only after, handed
back on failure, backing off) is tested apart from any one broker. The
round trips against real servers are in `test_live_change_capture.py` and
`test_live_queues.py`.
"""

from __future__ import annotations

import io
import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pandas as pd
import pytest
from sqlalchemy import MetaData, create_engine, func, select, text
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_extraction import live_recipes, streams
from service_extraction.live import KINDS
from service_extraction.live.base import Batch, ChangeCaptureKind, LiveField, LiveKind, Message, Outcome
from service_extraction.models import LiveRecipe, LiveRecipeResult, LiveTable, StreamEvent, StreamSource
from service_extraction.schemas import (
    LiveRecipeCreate,
    LiveRecipeUpdate,
    StreamSourceCreate,
    StreamSourceUpdate,
    StreamTestRequest,
)
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError
from shared_python.storage.local import LocalStorageBackend

import live_servers

OWNER_ID = uuid.UUID("0e0e0e0e-0e0e-0e0e-0e0e-0e0e0e0e0e0e")
SETTINGS = SimpleNamespace(max_upload_size_bytes=50 * 1024 * 1024, preview_row_limit=50, profile_sample_value_limit=5)


POSTGRES = os.environ.get("CONNECTORS_TEST_POSTGRES_URL") or (live_servers.POSTGRES_URL if live_servers.ENABLED else None)


@pytest.fixture(params=["sqlite", "postgres"])
def db(request) -> Iterator[Session]:
    """SQLite, and PostgreSQL when one is set: SQLite does not enforce foreign
    keys, and a feed created with its tables in one flush broke one (D1)."""
    if request.param == "sqlite":
        engine = create_engine("sqlite://")
        Base.metadata.create_all(engine)
        schema = None
    else:
        if not POSTGRES:
            pytest.skip("Set CONNECTORS_TEST_POSTGRES_URL to run these on PostgreSQL too.")
        schema = f"live_{uuid.uuid4().hex[:12]}"
        admin = create_engine(POSTGRES)
        with admin.begin() as connection:
            connection.execute(text(f'CREATE SCHEMA "{schema}"'))
        admin.dispose()
        engine = create_engine(POSTGRES, connect_args={"options": f"-csearch_path={schema}"})
        # A private copy: create_all on PostgreSQL changes the shared definitions (C1).
        private = MetaData()
        for table in Base.metadata.tables.values():
            table.to_metadata(private)
        private.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()
        if schema:
            admin = create_engine(POSTGRES)
            with admin.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.fixture()
def storage(tmp_path) -> LocalStorageBackend:
    return LocalStorageBackend(str(tmp_path / "storage"))


@pytest.fixture()
def world(db: Session) -> dict:
    db.add(User(id=OWNER_ID, username="owner", password_hash="x", role="admin", is_active=True))
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=OWNER_ID, status="active")
    db.add(project)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    return {"project": project, "user": user}


class FakeQueue(LiveKind):
    """A queue whose messages a test hands it; it owns its position like Kafka."""

    key = "kafka"  # stands in for a real kind's key so the schemas accept it
    label = "Fake queue"
    fields = (LiveField("topic", "Topic"), LiveField("password", "Password", kind="secret", required=False))
    guarantee = "position"

    def __init__(self) -> None:
        self.waiting: list[dict[str, Any]] = []
        self.acked: list[int] = []
        self.handed_back: list[int] = []
        self.fail_with: Exception | None = None

    def test(self, settings):
        return Outcome(True, "ok")

    def read(self, settings, cursor, *, limit):
        if self.fail_with is not None:
            raise self.fail_with
        start = int((cursor or {}).get("next", 0))
        taken = self.waiting[start:start + limit]
        positions = list(range(start, start + len(taken)))
        return Batch(
            messages=[Message("message", {"value": value, "format": "json"}, position=f"0:{p}")
                      for p, value in zip(positions, taken, strict=True)],
            cursor={"next": start + len(taken)},
            after_commit=lambda: self.acked.extend(positions),
            abandon=lambda: self.handed_back.extend(positions),
            more=start + len(taken) < len(self.waiting),
        )


@pytest.fixture()
def fake(monkeypatch) -> FakeQueue:
    kind = FakeQueue()
    monkeypatch.setitem(KINDS, "kafka", kind)
    return kind


def _queue(db, world, name="orders", **extra) -> uuid.UUID:
    created = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=name, kind="kafka", settings={"topic": "orders", "password": "s3cret"}, **extra), world["user"])
    return created.id


def _pass(db, source_id, storage, owner="test-runner"):
    return streams.run_pass(db, source_id, owner=owner, storage_backend=storage, settings=SETTINGS)


def _frame(storage, db, dataset_id) -> pd.DataFrame:
    dataset = db.get(Dataset, dataset_id)
    return pd.read_csv(io.BytesIO(storage.read_bytes(dataset.file_path)), dtype=str, keep_default_na=False)


# ---------------------------------------------------------------- kinds


def test_every_kind_says_what_it_needs_and_how_sure_it_is():
    kinds = {k["key"]: k for k in streams.list_kinds()}
    assert set(kinds) == {"webhook", "postgres_cdc", "mysql_cdc", "mongodb_cdc", "sqlserver_cdc", "kafka", "event_hubs",
                          "kinesis", "pubsub", "pulsar", "rabbitmq", "nats", "mqtt"}
    assert kinds["kafka"]["guarantee"] == "position" and kinds["mqtt"]["guarantee"] == "at_least_once"
    assert kinds["pubsub"]["guarantee"] == "message_id"
    for kind in kinds.values():
        assert kind["guarantee_title"] and kind["tier"] == 2 and kind["verified_by"], kind["key"]
        assert "—" not in kind["guarantee_detail"] + kind["description"]
    assert {f["key"] for f in kinds["kafka"]["fields"] if f["kind"] == "secret"} == {"password"}
    assert kinds["postgres_cdc"]["connection_types"] == ["postgresql"]


# ------------------------------------------------------- settings, secrets


def test_secrets_are_encrypted_at_rest_and_never_shown(db, world, fake):
    source_id = _queue(db, world)
    stored = db.get(StreamSource, source_id).config_json["settings"]
    assert stored["topic"] == "orders" and stored["password"] != "s3cret"
    shown = streams.get_source(db, world["project"].id, source_id, world["user"])
    assert shown.settings == {"topic": "orders", "password": True}
    # A blank secret keeps the saved one.
    streams.update_source(db, world["project"].id, source_id, StreamSourceUpdate(settings={"topic": "orders2", "password": ""}),
                          world["user"])
    assert streams.settings_for(db, db.get(StreamSource, source_id))["password"] == "s3cret"
    assert streams.settings_for(db, db.get(StreamSource, source_id))["topic"] == "orders2"


def test_a_missing_required_setting_is_refused_by_name(db, world, fake):
    with pytest.raises(BadRequestError, match="Topic is needed"):
        streams.create_source(db, world["project"].id, StreamSourceCreate(name="orders", kind="kafka", settings={}),
                              world["user"])


def test_an_address_the_platform_must_not_call_is_refused(db, world, monkeypatch):
    monkeypatch.delenv("OUTBOUND_ALLOW_LOOPBACK", raising=False)
    result = streams.test_new_settings(db, world["project"].id, StreamTestRequest(
        kind="kafka", settings={"bootstrap_servers": "127.0.0.1:9092", "topic": "t"}), world["user"])
    assert result.ok is False and "this server itself" in result.message
    result = streams.test_new_settings(db, world["project"].id, StreamTestRequest(
        kind="mqtt", settings={"host": "169.254.169.254", "topic": "x"}), world["user"])
    assert result.ok is False and "internal address" in result.message


# ------------------------------------------------------------- reading


def test_a_read_saves_the_position_with_the_events_then_acknowledges(db, world, storage, fake):
    fake.waiting = [{"order": i} for i in range(12)]
    source_id = _queue(db, world)
    monkey_batch = streams.READ_BATCH
    streams.READ_BATCH = 5
    try:
        result = _pass(db, source_id, storage)
    finally:
        streams.READ_BATCH = monkey_batch
    assert result["error"] is None and result["stored"] == 12
    source = db.get(StreamSource, source_id)
    assert json.loads(source.cursor) == {"next": 12}
    assert fake.acked == list(range(12)) and fake.handed_back == []
    seqs = db.scalars(select(StreamEvent.seq).where(StreamEvent.source_id == source_id).order_by(StreamEvent.seq)).all()
    assert seqs == list(range(1, 13))
    # Nothing new: nothing stored, nothing acknowledged twice.
    source.next_read_at = None
    db.commit()
    assert _pass(db, source_id, storage)["stored"] == 0 and fake.acked == list(range(12))


def test_an_event_already_stored_is_saved_once(db, world, fake):
    source_id = _queue(db, world)
    source = db.get(StreamSource, source_id)
    first = [Message("message", {"value": 1}, "0:1"), Message("message", {"value": 2}, "0:2")]
    assert streams.store_messages(db, source, first) == 2
    db.commit()
    again = [Message("message", {"value": 2}, "0:2"), Message("message", {"value": 3}, "0:3"),
             Message("message", {"value": 3}, "0:3"), Message("message", {"value": "no id"}, None)]
    assert streams.store_messages(db, source, again) == 2
    db.commit()
    values = [e.payload_json["value"] for e in db.scalars(select(StreamEvent).order_by(StreamEvent.seq)).all()]
    assert values == [1, 2, 3, "no id"]


def test_a_batch_that_cannot_be_stored_is_handed_back(db, world, storage, fake, monkeypatch):
    fake.waiting = [{"order": 1}, {"order": 2}]
    source_id = _queue(db, world)

    def broken(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(streams, "store_messages", broken)
    result = _pass(db, source_id, storage)
    assert "disk full" in result["error"]
    assert fake.handed_back == [0, 1] and fake.acked == []
    source = db.get(StreamSource, source_id)
    assert source.cursor is None  # the position did not move without the events


def test_a_failing_source_backs_off_and_its_owner_is_told_once(db, world, storage, fake):
    from service_notifications.models import UserNotification

    fake.fail_with = RuntimeError("broker unreachable")
    source_id = _queue(db, world)
    waits = []
    for _ in range(7):
        source = db.get(StreamSource, source_id)
        source.next_read_at = None
        db.commit()
        before = datetime.now(UTC)
        _pass(db, source_id, storage)
        source = db.get(StreamSource, source_id)
        waits.append((streams._aware(source.next_read_at) - before).total_seconds())
    assert source.status == "failing" and source.failures == 7 and "broker unreachable" in source.last_error
    assert waits[0] < waits[3] < waits[6] <= streams.BACKOFF_LIMIT_SECONDS + 1
    told = db.scalars(select(UserNotification).where(UserNotification.type == "live_source_failed")).all()
    assert len(told) == 1 and "keeps failing" in told[0].title
    fake.fail_with = None
    source.next_read_at = None
    db.commit()
    _pass(db, source_id, storage)
    source = db.get(StreamSource, source_id)
    assert (source.status, source.failures, source.last_error) == ("active", 0, None)


def test_a_paused_source_is_not_read(db, world, storage, fake):
    fake.waiting = [{"order": 1}]
    source_id = _queue(db, world)
    streams.update_source(db, world["project"].id, source_id, StreamSourceUpdate(status="paused"), world["user"])
    assert source_id not in streams.due_sources(db)
    assert _pass(db, source_id, storage)["stored"] == 0


def test_two_runners_never_read_one_source_at_once(db, world, fake):
    source_id = _queue(db, world)
    source = db.get(StreamSource, source_id)
    assert streams._claim(db, source, "runner-a") is True
    assert streams._claim(db, source, "runner-b") is False
    streams._release(db, source_id, "runner-a")
    assert streams._claim(db, source, "runner-b") is True


# --------------------------------------------------------------- saving


def test_the_log_is_appended_to_and_old_rows_stay_exactly_as_they_were(db, world, storage, fake):
    fake.waiting = [{"code": "007", "amount": 1}]
    source_id = _queue(db, world, save_every_seconds=5)
    _pass(db, source_id, storage)
    source = db.get(StreamSource, source_id)
    first = _frame(storage, db, source.dataset_id)
    assert first["code"].tolist() == ["007"]
    fake.waiting += [{"code": "8", "amount": 2.5, "note": "new column"}]
    source.next_read_at = None
    source.last_materialised_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    _pass(db, source_id, storage)
    after = _frame(storage, db, db.get(StreamSource, source_id).dataset_id)
    assert after["code"].tolist() == ["007", "8"]  # read back as text: "007" was never re-typed
    assert after["note"].tolist() == ["", "new column"]
    versions = db.scalar(select(func.count()).select_from(DatasetVersion).where(DatasetVersion.dataset_id == source.dataset_id))
    assert versions == 2
    assert db.get(StreamSource, source_id).log_saved_seq == 2


def test_nothing_new_saves_no_version(db, world, storage, fake):
    fake.waiting = [{"a": 1}]
    source_id = _queue(db, world)
    _pass(db, source_id, storage)
    source = db.get(StreamSource, source_id)
    source.next_read_at = None
    source.last_materialised_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    assert _pass(db, source_id, storage)["saved"] is None


def test_a_contract_stops_live_data_that_breaks_it(db, world, storage, fake):
    from service_quality.data_contracts import save_contract
    from service_quality.schemas_contracts import ContractColumn, ContractTerms, DataContractWrite

    fake.waiting = [{"order": 1, "email": "a@x"}]
    source_id = _queue(db, world)
    _pass(db, source_id, storage)
    source = db.get(StreamSource, source_id)
    save_contract(db, world["project"].id, source.dataset_id, DataContractWrite(
        description="Orders keep their email", enforcement="stop",
        terms=ContractTerms(columns=[ContractColumn(name="email", kind="text", always_filled=True)])), world["user"],
        storage)
    fake.waiting += [{"order": 2}]
    source.next_read_at = None
    source.last_materialised_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    result = _pass(db, source_id, storage)
    assert result["error"] and "contract" in result["error"].lower()
    frame = _frame(storage, db, db.get(StreamSource, source_id).dataset_id)
    assert frame["order"].tolist() == ["1"]  # the dataset kept what people use


# ------------------------------------------------------ tables kept current


class FakeTable(ChangeCaptureKind):
    key = "postgres_cdc"
    label = "Fake change capture"
    connection_types = ()

    def __init__(self) -> None:
        self.rows = {"orders": [{"id": 1, "name": "ann", "amount": 10.5}, {"id": 2, "name": "bo", "amount": 3}],
                     "notes": [{"text": "no key here"}]}
        self.changes: list[Message] = []
        self.calls: list[str] = []

    def test(self, settings):
        return Outcome(True, "ok")

    def start_position(self, settings):
        self.calls.append("position")
        return {"at": 0}

    def key_columns(self, settings, table):
        return ["id"] if table == "orders" else []

    def snapshot(self, settings, table, *, chunk):
        self.calls.append(f"snapshot {table}")
        yield list(self.rows[table])

    def read(self, settings, cursor, *, limit):
        start = int((cursor or {}).get("at", 0))
        taken = self.changes[start:start + limit]
        return Batch(messages=taken, cursor={"at": start + len(taken)})


def test_a_followed_table_is_snapshotted_then_kept_current_by_key(db, world, storage, monkeypatch):
    kind = FakeTable()
    monkeypatch.setitem(KINDS, "postgres_cdc", kind)
    created = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name="shop", kind="postgres_cdc", tables=["orders", "notes"]), world["user"])
    _pass(db, created.id, storage)
    # The position is taken before the snapshot, so nothing changing during it is missed.
    assert kind.calls[:2] == ["position", "snapshot notes"] or kind.calls[:2] == ["position", "snapshot orders"]
    tables = {t.table_name: t for t in db.scalars(select(LiveTable)).all()}
    assert tables["orders"].state == "following" and tables["orders"].snapshot_rows == 2
    assert tables["notes"].state == "log_only" and tables["notes"].dataset_id is None
    snap = _frame(storage, db, tables["orders"].dataset_id)
    assert snap["name"].tolist() == ["ann", "bo"]

    kind.changes = [
        Message("insert", {"row": {"id": 3, "name": "cy", "amount": 7}, "old_key": {}}, "c1", "public.orders"),
        Message("update", {"row": {"id": 1, "name": "ann", "amount": 11}, "old_key": {}}, "c2", "public.orders"),
        Message("delete", {"row": {}, "old_key": {"id": 2}}, "c3", "public.orders"),
        Message("insert", {"row": {"id": 9, "name": "other table"}, "old_key": {}}, "c4", "public.customers"),
    ]
    source = db.get(StreamSource, created.id)
    source.next_read_at = None
    source.last_materialised_at = datetime.now(UTC) - timedelta(minutes=5)
    db.commit()
    _pass(db, created.id, storage)
    table = db.get(LiveTable, tables["orders"].id)
    now = _frame(storage, db, table.dataset_id)
    assert now[["id", "name", "amount"]].values.tolist() == [["1", "ann", "11"], ["3", "cy", "7"]]
    assert table.rows_now == 2 and table.applied_seq == 4


def test_applying_changes_keeps_what_a_change_does_not_carry_and_follows_a_new_key():
    current = pd.DataFrame({"id": [1, 2], "name": ["ann", "bo"], "notes": ["long text", "x"]})

    def event(kind, row=None, old=None):
        return SimpleNamespace(kind=kind, payload_json={"row": row or {}, "old_key": old or {}})

    after = streams.apply_changes(current, [
        event("update", {"id": 1, "name": "Ann"}),  # `notes` not sent (unchanged): kept
        event("update", {"id": 20, "name": "bo", "notes": "x"}, old={"id": 2}),  # the key itself changed
        event("insert", {"id": 5, "name": "eve", "notes": None}),
        event("delete", old={"id": 5}),
        event("insert", {"id": 5, "name": "eve again", "notes": None}),
    ], ["id"])
    assert after.to_dict(orient="records") == [
        {"id": 1, "name": "Ann", "notes": "long text"},
        {"id": 5, "name": "eve again", "notes": None},
        {"id": 20, "name": "bo", "notes": "x"},
    ]


def test_starting_again_takes_the_snapshot_again(db, world, storage, monkeypatch):
    kind = FakeTable()
    monkeypatch.setitem(KINDS, "postgres_cdc", kind)
    created = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name="shop", kind="postgres_cdc", tables=["orders"]), world["user"])
    _pass(db, created.id, storage)
    streams.start_again(db, world["project"].id, created.id, world["user"])
    assert db.get(LiveTable, db.scalar(select(LiveTable.id))).state == "waiting"
    _pass(db, created.id, storage)
    assert kind.calls.count("snapshot orders") == 2 and kind.calls.count("position") == 2


# ------------------------------------------------------------- webhooks


def test_a_retried_post_with_an_idempotency_key_is_saved_once(db, world):
    hook = streams.create_source(db, world["project"].id, StreamSourceCreate(name="shop hooks", kind="webhook"),
                                 world["user"])
    assert hook.token and hook.guarantee == "at_least_once"
    first = streams.receive_webhook(db, token=hook.token, body=b'{"order": 7}', content_type="application/json",
                                    headers={"Idempotency-Key": "order-7"})
    again = streams.receive_webhook(db, token=hook.token, body=b'{"order": 7}', content_type="application/json",
                                    headers={"idempotency-key": "order-7"})
    other = streams.receive_webhook(db, token=hook.token, body=b'{"order": 8}', content_type="application/json",
                                    headers={})
    assert first.id == again.id and other.seq == 2
    assert db.scalar(select(func.count()).select_from(StreamEvent)) == 2


# ---------------------------------------------------------- live recipes


def _hook(db, world) -> tuple[uuid.UUID, str]:
    hook = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name="sales", kind="webhook", save_every_seconds=5), world["user"])
    return hook.id, hook.token


def _post(db, token, body: dict) -> None:
    streams.receive_webhook(db, token=token, body=json.dumps(body).encode(), content_type="application/json", headers={})


def _summary(db, world, source_id, **window) -> uuid.UUID:
    created = live_recipes.create_recipe(db, world["project"].id, source_id, LiveRecipeCreate(
        name="sales per minute",
        window={"kind": "tumbling", "size_seconds": 60, "time_column": "at", **window},
        group_by=["region"],
        measures=[{"name": "orders", "op": "count"}, {"name": "revenue", "op": "sum", "column": "amount"}],
    ), world["user"])
    return created.id


def test_a_live_recipe_summarises_by_window_and_saves_its_output(db, world, storage):
    source_id, token = _hook(db, world)
    recipe_id = _summary(db, world, source_id, lateness_seconds=30)
    for at, region, amount in [("2026-10-15T10:00:05Z", "north", 10), ("2026-10-15T10:00:40Z", "north", 5),
                               ("2026-10-15T10:00:50Z", "south", 7), ("2026-10-15T10:01:10Z", "north", 1),
                               ("2026-10-15T10:02:00Z", "south", 2)]:
        _post(db, token, {"at": at, "region": region, "amount": amount})
    _pass(db, source_id, storage)
    rows = live_recipes.recipe_results(db, world["project"].id, source_id, recipe_id, world["user"]).items
    table = {(r.window_start.strftime("%H:%M"), r.group[0]): (r.values["orders"], r.values["revenue"], r.final) for r in rows}
    # Watermark 10:01:30 (latest 10:02:00 less 30 seconds): the 10:00 windows are final.
    assert table == {("10:00", "north"): (2, 15.0, True), ("10:00", "south"): (1, 7.0, True),
                     ("10:01", "north"): (1, 1.0, False), ("10:02", "south"): (1, 2.0, False)}
    recipe = db.get(LiveRecipe, recipe_id)
    output = _frame(storage, db, recipe.output_dataset_id)
    assert list(output.columns) == ["window_start", "window_end", "region", "orders", "revenue", "events", "final", "restated"]
    assert len(output) == 4
    read = live_recipes.list_recipes(db, world["project"].id, source_id, world["user"]).items[0]
    assert read.open_windows == 2 and read.complete_up_to.strftime("%H:%M:%S") == "10:01:30"
    assert read.description == "Summarises by region over back-to-back windows of 1 minute: orders (count), revenue (sum)."


def test_a_batch_repeated_after_a_crash_counts_nothing_twice(db, world, storage, monkeypatch):
    source_id, token = _hook(db, world)
    recipe_id = _summary(db, world, source_id)
    for minute in range(3):
        _post(db, token, {"at": f"2026-10-15T10:0{minute}:00Z", "region": "north", "amount": 1})
    original = live_recipes._upsert

    def crash_after_writing(db_, recipe, outcome):
        original(db_, recipe, outcome)
        raise RuntimeError("the process was killed")

    monkeypatch.setattr(live_recipes, "_upsert", crash_after_writing)
    _pass(db, source_id, storage)
    recipe = db.get(LiveRecipe, recipe_id)
    assert recipe.status == "failed" and recipe.processed_seq == 0
    assert db.scalar(select(func.count()).select_from(LiveRecipeResult)) == 0  # rolled back with the state
    monkeypatch.setattr(live_recipes, "_upsert", original)
    live_recipes.update_recipe(db, world["project"].id, source_id, recipe_id, LiveRecipeUpdate(status="active"), world["user"])
    source = db.get(StreamSource, source_id)
    source.next_read_at = None
    db.commit()
    _pass(db, source_id, storage)
    totals = sorted((r.window_start.strftime("%H:%M"), r.values["orders"]) for r in
                    live_recipes.recipe_results(db, world["project"].id, source_id, recipe_id, world["user"]).items)
    assert totals == [("10:00", 1), ("10:01", 1), ("10:02", 1)]


def test_late_events_are_counted_or_restate_a_window(db, world, storage):
    source_id, token = _hook(db, world)
    dropping = _summary(db, world, source_id)
    restating = live_recipes.create_recipe(db, world["project"].id, source_id, LiveRecipeCreate(
        name="restating", window={"kind": "tumbling", "size_seconds": 60, "time_column": "at", "late": "restate",
                                  "restate_for_seconds": 600},
        group_by=[], measures=[{"name": "orders", "op": "count"}]), world["user"]).id
    _post(db, token, {"at": "2026-10-15T10:00:10Z", "region": "north", "amount": 1})
    _post(db, token, {"at": "2026-10-15T10:05:00Z", "region": "north", "amount": 1})
    _pass(db, source_id, storage)
    _post(db, token, {"at": "2026-10-15T10:00:30Z", "region": "north", "amount": 1})  # behind the watermark
    _post(db, token, {"at": "no time here", "region": "north", "amount": 1})
    source = db.get(StreamSource, source_id)
    source.next_read_at = None
    db.commit()
    _pass(db, source_id, storage)
    dropped, restated = db.get(LiveRecipe, dropping), db.get(LiveRecipe, restating)
    assert (dropped.late_dropped, dropped.late_restated, dropped.without_time) == (1, 0, 1)
    assert (restated.late_dropped, restated.late_restated) == (0, 1)
    first = [r for r in live_recipes.recipe_results(db, world["project"].id, source_id, restating, world["user"]).items
             if r.window_start.strftime("%H:%M") == "10:00"][0]
    assert (first.values["orders"], first.final, first.restated) == (2, True, 1)


def _dataset(db, world, storage, frame: pd.DataFrame, name: str):
    from service_datasets.service import create_uploaded_dataset_placeholder, finalize_dataset_materialization_success
    from service_ingestion.profiling import infer_schema

    placeholder = create_uploaded_dataset_placeholder(
        db, project_id=world["project"].id, name=name, original_filename=f"{name}.csv", file_type="csv",
        file_size_bytes=10, current_user=world["user"], pipeline_run_id=None)
    stored = storage.save_upload(relative_path=f"projects/{world['project'].id}/{uuid.uuid4().hex}.csv",
                                 file_bytes=frame.to_csv(index=False).encode())
    schema = infer_schema(dataframe=frame)
    finalize_dataset_materialization_success(
        db, dataset=placeholder, file_path=stored.relative_path, file_name=stored.file_name, schema_json=schema,
        schema_snapshot={"columns": schema["columns"]}, preview_json={}, profile_json={}, row_count=len(frame),
        column_count=len(frame.columns))
    db.commit()
    return placeholder


def _saved_recipe(db, world, base_id, steps):
    from service_transformations.models import TransformationPipeline

    recipe = TransformationPipeline(project_id=world["project"].id, base_dataset_id=base_id, name="clean",
                                    steps_json=steps, created_by_user_id=OWNER_ID)
    db.add(recipe)
    db.commit()
    return recipe


def test_a_live_recipe_runs_row_wise_steps_and_a_lookup(db, world, storage):
    regions = pd.DataFrame({"customer": ["c1", "c2"], "region": ["north", "south"], "tier": ["gold", "silver"]})
    placeholder = _dataset(db, world, storage, regions, "Customers")
    recipe = _saved_recipe(db, world, placeholder.id, [
        {"step_type": "filter_rows", "config": {"conditions": [{"column": "amount", "operator": "greater_than", "value": 0}]}},
        {"step_type": "derive_column", "config": {"target_column": "double", "formula": "[amount] * 2"}},
    ])
    source_id, token = _hook(db, world)
    live = live_recipes.create_recipe(db, world["project"].id, source_id, LiveRecipeCreate(
        name="enriched", recipe_id=recipe.id,
        lookup={"dataset_id": placeholder.id, "on": [{"event": "customer", "dataset": "customer"}],
                "columns": ["region", "tier"], "keep_unmatched": True}), world["user"])
    for customer, amount in [("c1", 5), ("c2", -1), ("zz", 3)]:
        _post(db, token, {"customer": customer, "amount": amount})
    _pass(db, source_id, storage)
    out = _frame(storage, db, db.get(LiveRecipe, live.id).output_dataset_id)
    assert out[["customer", "double", "region", "tier"]].values.tolist() == [["c1", "10", "north", "gold"], ["zz", "6", "", ""]]
    assert db.get(LiveRecipe, live.id).unmatched == 1


def test_steps_that_need_every_row_are_refused(db, world, storage):
    base = _dataset(db, world, storage, pd.DataFrame({"amount": [1]}), "Base")
    recipe = _saved_recipe(db, world, base.id, [{"step_type": "sort_rows", "config": {"columns": ["amount"]}}])
    source_id, _ = _hook(db, world)
    with pytest.raises(BadRequestError, match="Step 1 \\(sort rows\\) needs every row at once"):
        live_recipes.create_recipe(db, world["project"].id, source_id, LiveRecipeCreate(name="no", recipe_id=recipe.id),
                                   world["user"])
    with pytest.raises(BadRequestError, match="at least one measure"):
        live_recipes.create_recipe(db, world["project"].id, source_id, LiveRecipeCreate(
            name="no", window={"kind": "tumbling", "size_seconds": 60}), world["user"])


def test_old_events_are_forgotten_once_every_output_has_them(db, world, storage):
    source_id, token = _hook(db, world)
    recipe_id = _summary(db, world, source_id)
    for i in range(3):
        _post(db, token, {"at": f"2026-10-15T10:0{i}:00Z", "region": "north", "amount": 1})
    _pass(db, source_id, storage)
    old = datetime.now(UTC) - timedelta(hours=200)
    for event in db.scalars(select(StreamEvent)).all():
        event.received_at = old
    db.commit()
    live_recipes.update_recipe(db, world["project"].id, source_id, recipe_id, LiveRecipeUpdate(status="paused"),
                               world["user"])
    source = db.get(StreamSource, source_id)
    assert streams.trim_events(db, source) == 3
    assert db.scalar(select(func.count()).select_from(StreamEvent)) == 0


# ------------------------------------------------------- roles and activity


@pytest.mark.parametrize(("method", "path", "role"), [
    ("GET", "/api/v1/projects/p/live/kinds", "viewer"),
    ("GET", "/api/v1/projects/p/streams/s/throughput", "viewer"),
    ("GET", "/api/v1/projects/p/streams/s/recipes/r/results", "viewer"),
    # Saved settings: checking them changes nothing.
    ("POST", "/api/v1/projects/p/streams/s/test", "viewer"),
    # Unsaved settings name any address, so calling one is an editor's action.
    ("POST", "/api/v1/projects/p/streams/try", "editor"),
    ("POST", "/api/v1/projects/p/streams/s/poll", "operator"),
    ("POST", "/api/v1/projects/p/streams/s/materialise", "operator"),
    ("POST", "/api/v1/projects/p/streams/s/start-again", "editor"),
    ("PATCH", "/api/v1/projects/p/streams/s", "editor"),
    ("POST", "/api/v1/projects/p/streams/s/recipes", "editor"),
    ("POST", "/api/v1/projects/p/streams/s/recipes/r/start-again", "editor"),
])
def test_each_route_needs_the_role_it_should(method, path, role):
    from service_access.permissions import required_role

    assert required_role(method, path) == role


def test_activity_shows_a_feed_that_keeps_failing_and_a_live_recipe_that_stopped(db, world, storage, fake):
    from api_gateway.activity import project_activity

    fake.fail_with = RuntimeError("broker unreachable")
    source_id = _queue(db, world, name="orders feed")
    for _ in range(streams.NOTIFY_AFTER):
        db.get(StreamSource, source_id).next_read_at = None
        db.commit()
        _pass(db, source_id, storage)
    hook_id, _ = _hook(db, world)
    recipe_id = _summary(db, world, hook_id)
    recipe = db.get(LiveRecipe, recipe_id)
    recipe.status, recipe.last_error = "failed", "The events have no column region."
    db.commit()
    items = project_activity(db, world["project"].id, world["user"], kinds=["live"]).items
    assert {(i.sentence, i.level) for i in items} == {("orders feed keeps failing", "error"),
                                                       ("The live recipe sales per minute stopped", "warning")}
    assert all(i.href and "/live/" in i.href for i in items)


def test_an_output_keeps_the_last_thirty_days_of_windows(db, world, storage):
    source_id, token = _hook(db, world)
    recipe_id = _summary(db, world, source_id, lateness_seconds=0)
    old_day = (datetime.now(UTC) - timedelta(days=40)).strftime("%Y-%m-%dT10:00:00Z")
    _post(db, token, {"at": old_day, "region": "north", "amount": 1})
    _post(db, token, {"at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "region": "north", "amount": 2})
    _pass(db, source_id, storage)
    out = _frame(storage, db, db.get(LiveRecipe, recipe_id).output_dataset_id)
    assert len(out) == 1 and out["revenue"].tolist() == ["2.0"]  # the 40-day-old window left the output
    assert db.scalar(select(func.count()).select_from(LiveRecipeResult)) == 1
