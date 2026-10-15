"""Webhooks and the PostgreSQL change-log parser (Phase 20).

SQLite, no network. Change capture against real databases, and every queue,
are in `test_live_change_capture.py` and `test_live_queues.py`; the reading,
saving and live-recipe lifecycle in `test_live_sources.py`.
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_extraction.live.postgres import parse_test_decoding
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
    assert first.version_number == 1 and first.events_saved == 3
    dataset = db.get(Dataset, first.dataset_id)
    columns = set(pd.read_csv(io.BytesIO(storage.read_bytes(dataset.file_path))).columns)
    # Nested JSON is flattened into columns; the event envelope comes along.
    assert {"seq", "kind", "received_at", "order_id", "customer.tier"} <= columns

    receive_webhook(db, token=created.token, body=b'{"order_id": 99}', content_type="application/json", headers={})
    second = materialise_source(db, world["project"].id, created.id, world["user"], storage, SETTINGS)
    assert second.dataset_id == first.dataset_id  # the same dataset, a new version
    assert second.version_number == 2 and second.events_saved == 1
    assert db.get(Dataset, first.dataset_id).row_count == 4
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


def test_a_change_capture_source_needs_the_right_connection_and_tables(db, world):
    with pytest.raises(BadRequestError, match="reads through a connection"):
        create_source(db, world["project"].id, StreamSourceCreate(name="cdc", kind="postgres_cdc"), world["user"])
    mysql = ExtractionConnection(project_id=world["project"].id, name="my", connector_type="mysql", config_json={})
    db.add(mysql)
    db.commit()
    with pytest.raises(BadRequestError, match="follows a postgresql connection"):
        create_source(db, world["project"].id, StreamSourceCreate(name="cdc", kind="postgres_cdc", connection_id=mysql.id, tables=["t"]), world["user"])
    pg = ExtractionConnection(project_id=world["project"].id, name="pg", connector_type="postgresql", config_json={})
    db.add(pg)
    db.commit()
    with pytest.raises(BadRequestError, match="at least one table"):
        create_source(db, world["project"].id, StreamSourceCreate(name="cdc", kind="postgres_cdc", connection_id=pg.id), world["user"])
    source = create_source(db, world["project"].id, StreamSourceCreate(name="Orders CDC", kind="postgres_cdc", connection_id=pg.id, tables=["public.orders", "public.orders", " "]), world["user"])
    assert source.slot_name.startswith("pipewright_orders_cdc_") and source.token is None
    assert source.tables == ["public.orders"] and [t.state for t in source.live_tables] == ["waiting"]
    hook = create_source(db, world["project"].id, StreamSourceCreate(name="hook", kind="webhook"), world["user"])
    with pytest.raises(BadRequestError, match="A webhook is not read"):
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
