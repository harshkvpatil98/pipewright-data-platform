"""Stream sources (P9 / product Phase 20, first slice): inbound webhooks and
PostgreSQL change data capture, stored as events and materialised as
versioned datasets.

Everything but the last test runs against SQLite with no network. The CDC
test needs a real PostgreSQL with `wal_level = logical` (the dev compose file
sets it); it skips with the reason otherwise -- a skip is not a pass and the
handoff says so.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import DatasetVersion
from service_extraction.cdc_postgres import parse_test_decoding
from service_extraction.models import ExtractionConnection, StreamEvent, StreamSource
from service_extraction.schemas import StreamSourceCreate
from service_extraction.streams import (
    HOOK_PATH,
    create_source,
    delete_source,
    list_events,
    list_sources,
    materialise_source,
    poll_source,
    receive_webhook,
)
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.storage.local import LocalStorageBackend

OWNER_ID = uuid.UUID("0d0d0d0d-0d0d-0d0d-0d0d-0d0d0d0d0d0d")
SETTINGS = SimpleNamespace(max_upload_size_bytes=25 * 1024 * 1024, preview_row_limit=50, profile_sample_value_limit=5)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


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


# ---- webhooks ----


def test_a_webhook_source_shows_its_token_once_and_receives_posts(db, world):
    created = create_source(db, world["project"].id, StreamSourceCreate(name="Orders hook", kind="webhook"), world["user"])
    assert created.token and created.webhook_path_with_token == HOOK_PATH.replace("{token}", created.token)
    # Listed again, the token is gone: only its hash is stored.
    listed = list_sources(db, world["project"].id, world["user"]).items[0]
    assert listed.webhook_path and "…" in listed.webhook_path
    stored = db.get(StreamSource, created.id)
    assert stored.token_hash and created.token not in stored.token_hash

    event = receive_webhook(
        db, token=created.token, body=b'{"order_id": 7, "customer": {"id": "c1", "tier": "gold"}, "amount": 12.5}',
        content_type="application/json", headers={"User-Agent": "shop/1.0", "X-Event-Type": "order.created"},
    )
    assert event.seq == 1 and event.kind == "webhook"
    assert event.payload_json["order_id"] == 7 and event.payload_json["_headers"]["X-Event-Type"] == "order.created"
    plain = receive_webhook(db, token=created.token, body=b"hello", content_type="text/plain", headers={})
    assert plain.seq == 2 and plain.payload_json == {"body": "hello"}
    assert db.get(StreamSource, created.id).events_count == 2

    with pytest.raises(NotFoundError):
        receive_webhook(db, token="not-a-token", body=b"{}", content_type="application/json", headers={})
    with pytest.raises(BadRequestError, match="not valid JSON"):
        receive_webhook(db, token=created.token, body=b"{oops", content_type="application/json", headers={})
    with pytest.raises(BadRequestError, match="exceeds"):
        receive_webhook(db, token=created.token, body=b"x" * (256 * 1024 + 1), content_type="text/plain", headers={})


def test_materialising_writes_an_append_only_versioned_dataset(db, world, storage):
    created = create_source(db, world["project"].id, StreamSourceCreate(name="Orders hook", kind="webhook"), world["user"])
    with pytest.raises(BadRequestError, match="Nothing has arrived"):
        materialise_source(db, world["project"].id, created.id, world["user"], storage, SETTINGS)
    for i in range(3):
        receive_webhook(db, token=created.token, body=f'{{"order_id": {i}, "customer": {{"tier": "gold"}}}}'.encode(),
                        content_type="application/json", headers={})

    first = materialise_source(db, world["project"].id, created.id, world["user"], storage, SETTINGS)
    assert first.version_number == 1 and first.rows == 3
    # Nested JSON is flattened into columns; the event envelope comes along.
    assert {"seq", "kind", "received_at", "order_id", "customer.tier"} <= set(first.columns)

    receive_webhook(db, token=created.token, body=b'{"order_id": 99}', content_type="application/json", headers={})
    second = materialise_source(db, world["project"].id, created.id, world["user"], storage, SETTINGS)
    assert second.dataset_id == first.dataset_id  # the same dataset, a new version
    assert second.version_number == 2 and second.rows == 4
    versions = db.scalars(select(DatasetVersion).where(DatasetVersion.dataset_id == first.dataset_id)).all()
    assert sorted(v.version_number for v in versions) == [1, 2]
    assert versions[0].content_hash != versions[1].content_hash
    events = list_events(db, world["project"].id, created.id, world["user"]).items
    assert [e.seq for e in events] == [4, 3, 2, 1]


def test_deleting_a_source_takes_its_events_with_it(db, world):
    created = create_source(db, world["project"].id, StreamSourceCreate(name="hook", kind="webhook"), world["user"])
    receive_webhook(db, token=created.token, body=b"{}", content_type="application/json", headers={})
    delete_source(db, world["project"].id, created.id, world["user"])
    assert db.scalars(select(StreamEvent)).all() == []


def test_a_cdc_source_needs_a_postgres_connection_and_tables(db, world):
    with pytest.raises(BadRequestError, match="needs a PostgreSQL connection"):
        create_source(db, world["project"].id, StreamSourceCreate(name="cdc", kind="postgres_cdc"), world["user"])
    mysql = ExtractionConnection(project_id=world["project"].id, name="my", connector_type="mysql", config_json={})
    db.add(mysql)
    db.commit()
    with pytest.raises(BadRequestError, match="not supported here"):
        create_source(db, world["project"].id, StreamSourceCreate(name="cdc", kind="postgres_cdc", connection_id=mysql.id, tables=["t"]), world["user"])
    pg = ExtractionConnection(project_id=world["project"].id, name="pg", connector_type="postgresql", config_json={})
    db.add(pg)
    db.commit()
    with pytest.raises(BadRequestError, match="at least one table"):
        create_source(db, world["project"].id, StreamSourceCreate(name="cdc", kind="postgres_cdc", connection_id=pg.id), world["user"])
    source = create_source(db, world["project"].id, StreamSourceCreate(name="Orders CDC", kind="postgres_cdc", connection_id=pg.id, tables=["public.orders"]), world["user"])
    assert source.slot_name == "pipewright_orders_cdc" and source.token is None
    hook = create_source(db, world["project"].id, StreamSourceCreate(name="hook", kind="webhook"), world["user"])
    with pytest.raises(BadRequestError, match="a webhook receives"):
        poll_source(db, world["project"].id, hook.id, world["user"])


# ---- the change-log parser ----


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("table public.orders: INSERT: id[integer]:1 name[text]:'a b' price[numeric]:12.5 ok[boolean]:true note[text]:null",
         ("insert", "public.orders", {"id": 1, "name": "a b", "price": 12.5, "ok": True, "note": None}, {})),
        ("table public.orders: UPDATE: old-key: id[integer]:1 new-tuple: id[integer]:1 name[text]:'it''s'",
         ("update", "public.orders", {"id": 1, "name": "it's"}, {"id": 1})),
        ("table public.orders: DELETE: id[integer]:2", ("delete", "public.orders", {"id": 2}, {})),
        ("table public.\"Odd Name\": INSERT: \"a b\"[text]:'x'", ("insert", 'public."Odd Name"', {"a b": "x"}, {})),
        ("BEGIN 700", None),
        ("COMMIT 700", None),
    ],
)
def test_test_decoding_lines_parse_into_row_changes(line, expected):
    assert parse_test_decoding(line) == expected


# ---- live CDC against a logical-WAL PostgreSQL ----

PG_URL = os.environ.get("CONNECTORS_TEST_POSTGRES_URL") or "postgresql+psycopg://platform:platform@127.0.0.1:5432/platform"


def _logical_postgres():
    try:
        engine = sa.create_engine(PG_URL)
        with engine.connect() as conn:
            level = conn.execute(sa.text("SHOW wal_level")).scalar()
        engine.dispose()
    except Exception as exc:  # noqa: BLE001 - not reachable is a skip, stated
        return None, f"PostgreSQL not reachable at {PG_URL}: {exc}"
    if level != "logical":
        return None, f"PostgreSQL at {PG_URL} has wal_level={level}; CDC needs logical"
    return PG_URL, None


def test_cdc_follows_a_tables_change_log_at_least_once(db, world, storage):
    url, reason = _logical_postgres()
    if url is None:
        pytest.skip(reason)
    from sqlalchemy.engine import make_url

    parsed = make_url(url)
    suffix = uuid.uuid4().hex[:8]
    table = f"pw_cdc_{suffix}"
    admin = sa.create_engine(url)
    with admin.begin() as conn:
        conn.execute(sa.text(f"CREATE TABLE {table} (id serial PRIMARY KEY, name text, amount numeric)"))
    connection = ExtractionConnection(
        project_id=world["project"].id, name="pg", connector_type="postgresql",
        config_json={"host": parsed.host, "port": parsed.port or 5432, "database": parsed.database,
                     "username": parsed.username, "password": parsed.password},
    )
    db.add(connection)
    db.commit()
    source = create_source(
        db, world["project"].id,
        StreamSourceCreate(name=f"cdc {suffix}", kind="postgres_cdc", connection_id=connection.id,
                           tables=[f"public.{table}"], slot_name=f"pw_test_{suffix}"),
        world["user"],
    )
    try:
        first = poll_source(db, world["project"].id, source.id, world["user"])
        assert first.slot_created is True and first.events_stored == 0

        with admin.begin() as conn:
            conn.execute(sa.text(f"INSERT INTO {table} (name, amount) VALUES ('ann', 10.5), ('bo', 20)"))
            conn.execute(sa.text(f"UPDATE {table} SET amount = 11 WHERE name = 'ann'"))
            conn.execute(sa.text(f"DELETE FROM {table} WHERE name = 'bo'"))
        second = poll_source(db, world["project"].id, source.id, world["user"])
        assert second.events_stored == 4 and second.upto_lsn
        kinds = [e.kind for e in sorted(list_events(db, world["project"].id, source.id, world["user"]).items, key=lambda e: e.seq)]
        assert kinds == ["insert", "insert", "update", "delete"]
        # Consumed: a third poll finds nothing new; the slot advanced.
        third = poll_source(db, world["project"].id, source.id, world["user"])
        assert third.events_stored == 0 and third.changes_read == 0

        made = materialise_source(db, world["project"].id, source.id, world["user"], storage, SETTINGS)
        assert made.rows == 4 and {"kind", "table", "lsn", "name", "amount"} <= set(made.columns)
    finally:
        delete_source(db, world["project"].id, source.id, world["user"])  # drops the slot
        with admin.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
            left = conn.execute(sa.text("SELECT count(*) FROM pg_replication_slots WHERE slot_name = :s"), {"s": f"pw_test_{suffix}"}).scalar()
        admin.dispose()
        assert left == 0
