"""Change capture against real databases (D1, L1 and L2).

PostgreSQL (logical decoding), MySQL (the binary log), MongoDB (change
streams) and SQL Server (its CDC tables), each from `docker-compose.live.yml`.
Every one goes the same way: rows that were there before the source are in
the table's dataset after the first pass (the snapshot); an insert, an update
and a delete afterwards leave it with the right rows; the log has every
change; a second pass finds nothing new. These are what the change-capture
kinds' tier 2 rests on, so the `live` CI job runs them with
`LIVE_TEST_SERVERS=1` and fails if a server is missing; without it they skip.
"""

from __future__ import annotations

import io
import time
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pandas as pd
import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_extraction import streams
from service_extraction.live import postgres as pg_kind
from service_extraction.models import ExtractionConnection, LiveTable, StreamEvent, StreamSource
from service_extraction.schemas import StreamSourceCreate
from service_projects.models import Project
from shared_python.db import Base
from shared_python.security.config_crypto import encrypt_sensitive_fields
from shared_python.storage.local import LocalStorageBackend

import live_servers as servers

pytestmark = pytest.mark.skipif(not servers.ENABLED, reason=servers.REASON)


@pytest.fixture(autouse=True, scope="module")
def _close_pooled_connections() -> Iterator[None]:
    """The kinds reach databases through the import service's pooled engines; close them after."""
    yield
    from service_extraction.connectors import sql_database

    sql_database.dispose_cached_engines()

OWNER_ID = uuid.UUID("0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f")
SETTINGS = SimpleNamespace(max_upload_size_bytes=50 * 1024 * 1024, preview_row_limit=50, profile_sample_value_limit=5)


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
    return {"project": project, "user": UserRead(id=OWNER_ID, username="owner", role="admin", is_active=True,
                                                 created_at=now, updated_at=now)}


def _connection(db, world, connector_type: str, config: dict, secrets: tuple[str, ...]) -> uuid.UUID:
    connection = ExtractionConnection(project_id=world["project"].id, name=connector_type, connector_type=connector_type,
                                      config_json=encrypt_sensitive_fields(config, secrets))
    db.add(connection)
    db.commit()
    return connection.id


def _pass(db, source_id, storage) -> dict:
    source = db.get(StreamSource, source_id)
    source.next_read_at = None
    source.last_materialised_at = datetime.now(UTC) - timedelta(minutes=10)
    db.commit()
    result = streams.run_pass(db, source_id, owner="test-runner", storage_backend=storage, settings=SETTINGS)
    assert result["error"] is None, result["error"]
    return result


def _table_rows(db, storage, source_id) -> pd.DataFrame:
    table = db.scalar(select(LiveTable).where(LiveTable.source_id == source_id))
    assert table.state == "following", (table.state, table.last_error)
    dataset = db.get(Dataset, table.dataset_id)
    return pd.read_csv(io.BytesIO(storage.read_bytes(dataset.file_path)))


def _kinds(db, source_id) -> list[str]:
    return [e.kind for e in db.scalars(select(StreamEvent).where(StreamEvent.source_id == source_id)
                                       .order_by(StreamEvent.seq)).all()]


def _round_trip(db, world, storage, source_id, change, *, wait_for: int = 3) -> None:
    """Snapshot, then an insert, update and delete, then nothing new."""
    _pass(db, source_id, storage)
    snapshot = _table_rows(db, storage, source_id)
    assert sorted(snapshot["name"].tolist()) == ["ann", "bo"]
    change()
    for _ in range(30):
        _pass(db, source_id, storage)
        if len(_kinds(db, source_id)) >= wait_for:
            break
        time.sleep(1)  # SQL Server's capture job copies changes every few seconds
    assert _kinds(db, source_id)[-3:] == ["insert", "update", "delete"]
    now = _table_rows(db, storage, source_id)
    assert sorted(zip(now["name"], now["amount"], strict=True)) == [("ann", 11), ("cy", 7)]
    before = len(_kinds(db, source_id))
    _pass(db, source_id, storage)
    assert len(_kinds(db, source_id)) == before
    log = db.get(Dataset, db.get(StreamSource, source_id).dataset_id)
    assert log.row_count == before


# ------------------------------------------------------------------ PostgreSQL


def _pg_table() -> tuple[sa.Engine, str]:
    engine = sa.create_engine(servers.POSTGRES_URL)
    table = f"pw_live_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f"CREATE TABLE {table} (id serial PRIMARY KEY, name text, amount numeric)"))
        conn.execute(sa.text(f"INSERT INTO {table} (name, amount) VALUES ('ann', 10.5), ('bo', 3)"))
    return engine, table


def test_postgres_keeps_a_table_current_from_its_change_log(db, world, storage):
    engine, table = _pg_table()
    connection_id = _connection(db, world, "postgresql", dict(servers.POSTGRES), ("password",))
    source = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=f"pg {table}", kind="postgres_cdc", connection_id=connection_id, tables=[f"public.{table}"]), world["user"])

    def change() -> None:
        with engine.begin() as conn:
            conn.execute(sa.text(f"INSERT INTO {table} (name, amount) VALUES ('cy', 7)"))
            conn.execute(sa.text(f"UPDATE {table} SET amount = 11 WHERE name = 'ann'"))
            conn.execute(sa.text(f"DELETE FROM {table} WHERE name = 'bo'"))

    try:
        _round_trip(db, world, storage, source.id, change)
    finally:
        streams.delete_source(db, world["project"].id, source.id, world["user"])  # drops the slot
        with engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
            left = conn.execute(sa.text("SELECT count(*) FROM pg_replication_slots WHERE slot_name = :s"),
                                {"s": source.slot_name}).scalar()
        engine.dispose()
    assert left == 0


def test_postgres_never_loses_a_change_committed_during_a_read(db, world, storage, monkeypatch):
    """The position consumed up to comes from the read that was stored. When it
    came from a second read, a change committed in between was consumed
    without ever being stored (the D1 baseline lost it every time)."""
    engine, table = _pg_table()
    connection_id = _connection(db, world, "postgresql", dict(servers.POSTGRES), ("password",))
    source = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=f"race {table}", kind="postgres_cdc", connection_id=connection_id, tables=[table]), world["user"])
    try:
        _pass(db, source.id, storage)
        with engine.begin() as conn:
            conn.execute(sa.text(f"INSERT INTO {table} (name, amount) VALUES ('before', 1)"))
        original = pg_kind._peek
        raced = {"done": False}

        def read_then_race(*args, **kwargs):
            result = original(*args, **kwargs)
            if not raced["done"]:
                raced["done"] = True
                with engine.begin() as conn:  # committed while the read is still working
                    conn.execute(sa.text(f"INSERT INTO {table} (name, amount) VALUES ('raced', 1)"))
            return result

        monkeypatch.setattr(pg_kind, "_peek", read_then_race)
        _pass(db, source.id, storage)
        monkeypatch.setattr(pg_kind, "_peek", original)
        _pass(db, source.id, storage)
        names = [e.payload_json["row"]["name"] for e in db.scalars(
            select(StreamEvent).where(StreamEvent.source_id == source.id).order_by(StreamEvent.seq)).all()]
        assert names == ["before", "raced"]
    finally:
        streams.delete_source(db, world["project"].id, source.id, world["user"])
        with engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()


def test_postgres_catches_up_twenty_thousand_changes_in_one_pass(db, world, storage):
    engine, table = _pg_table()
    connection_id = _connection(db, world, "postgresql", dict(servers.POSTGRES), ("password",))
    source = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=f"bulk {table}", kind="postgres_cdc", connection_id=connection_id, tables=[table]), world["user"])
    try:
        _pass(db, source.id, storage)
        with engine.begin() as conn:
            conn.execute(sa.text(f"INSERT INTO {table} (name, amount) SELECT 'n' || g, g FROM generate_series(1, 20000) g"))
        started = time.monotonic()
        _pass(db, source.id, storage)
        took = time.monotonic() - started
        assert db.get(StreamSource, source.id).events_count == 20_000
        assert db.scalar(select(LiveTable.rows_now).where(LiveTable.source_id == source.id)) == 20_002
        assert took < 60, took
    finally:
        streams.delete_source(db, world["project"].id, source.id, world["user"])
        with engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()


# ----------------------------------------------------------------------- MySQL


def test_mysql_keeps_a_table_current_from_its_binary_log(db, world, storage):
    engine = sa.create_engine(servers.MYSQL_URL)
    table = f"pw_live_{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(sa.text(f"CREATE TABLE {table} (id INT AUTO_INCREMENT PRIMARY KEY, name VARCHAR(20), amount DECIMAL(10,2))"))
        conn.execute(sa.text(f"INSERT INTO {table} (name, amount) VALUES ('ann', 10.5), ('bo', 3)"))
    connection_id = _connection(db, world, "mysql", dict(servers.MYSQL), ("password",))
    source = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=f"my {table}", kind="mysql_cdc", connection_id=connection_id, tables=[table]), world["user"])

    def change() -> None:
        with engine.begin() as conn:
            conn.execute(sa.text(f"INSERT INTO {table} (name, amount) VALUES ('cy', 7)"))
            conn.execute(sa.text(f"UPDATE {table} SET amount = 11 WHERE name = 'ann'"))
        with engine.begin() as conn:
            conn.execute(sa.text(f"DELETE FROM {table} WHERE name = 'bo'"))

    try:
        _round_trip(db, world, storage, source.id, change)
        assert "file" in streams.cursor_of(db.get(StreamSource, source.id))
    finally:
        streams.delete_source(db, world["project"].id, source.id, world["user"])
        with engine.begin() as conn:
            conn.execute(sa.text(f"DROP TABLE IF EXISTS {table}"))
        engine.dispose()


# --------------------------------------------------------------------- MongoDB


def test_mongodb_keeps_a_collection_current_from_its_change_stream(db, world, storage):
    import pymongo

    client = pymongo.MongoClient(servers.MONGO_URI)
    name = f"pw_live_{uuid.uuid4().hex[:8]}"
    collection = client.platform[name]
    collection.insert_many([{"name": "ann", "amount": 10.5, "address": {"city": "Leeds"}}, {"name": "bo", "amount": 3}])
    connection_id = _connection(db, world, "mongodb", {"connection_string": servers.MONGO_URI, "database": "platform"},
                                ("connection_string",))
    source = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=f"mongo {name}", kind="mongodb_cdc", connection_id=connection_id, tables=[name]), world["user"])

    def change() -> None:
        collection.insert_one({"name": "cy", "amount": 7})
        collection.update_one({"name": "ann"}, {"$set": {"amount": 11}})
        collection.delete_one({"name": "bo"})

    try:
        _round_trip(db, world, storage, source.id, change)
        rows = _table_rows(db, storage, source.id)
        assert "address.city" in rows.columns and "_id" in rows.columns  # documents flattened, keyed by _id
    finally:
        streams.delete_source(db, world["project"].id, source.id, world["user"])
        collection.drop()
        client.close()


# ------------------------------------------------------------------ SQL Server


def test_sqlserver_keeps_a_table_current_from_its_change_tables(db, world, storage):
    import pymssql

    admin = pymssql.connect(server=servers.SQLSERVER["host"], port=servers.SQLSERVER["port"],
                            user=servers.SQLSERVER["username"], password=servers.SQLSERVER["password"], autocommit=True)
    admin.cursor().execute("IF DB_ID('pw_live') IS NULL CREATE DATABASE pw_live")
    admin.close()
    conn = pymssql.connect(server=servers.SQLSERVER["host"], port=servers.SQLSERVER["port"],
                           user=servers.SQLSERVER["username"], password=servers.SQLSERVER["password"],
                           database="pw_live", autocommit=True)
    cursor = conn.cursor()
    cursor.execute("IF (SELECT is_cdc_enabled FROM sys.databases WHERE name = 'pw_live') = 0 EXEC sys.sp_cdc_enable_db")
    table = f"pw_live_{uuid.uuid4().hex[:8]}"
    cursor.execute(f"CREATE TABLE dbo.{table} (id INT IDENTITY PRIMARY KEY, name NVARCHAR(20), amount DECIMAL(10,2))")
    cursor.execute(f"INSERT INTO dbo.{table} (name, amount) VALUES ('ann', 10.5), ('bo', 3)")
    settings = {"host": servers.SQLSERVER["host"], "port": servers.SQLSERVER["port"], "database": "pw_live",
                "username": servers.SQLSERVER["username"], "password": servers.SQLSERVER["password"]}
    # The test names exactly what to run when change capture is off for the table.
    refused = streams.test_new_settings(db, world["project"].id, _test_request("sqlserver_cdc", settings, [f"dbo.{table}"]),
                                        world["user"])
    assert refused.ok is False and "sys.sp_cdc_enable_table" in refused.message
    cursor.execute(f"EXEC sys.sp_cdc_enable_table @source_schema = N'dbo', @source_name = N'{table}', @role_name = NULL")
    source = streams.create_source(db, world["project"].id, StreamSourceCreate(
        name=f"mssql {table}", kind="sqlserver_cdc", settings=settings, tables=[f"dbo.{table}"]), world["user"])

    def change() -> None:
        cursor.execute(f"INSERT INTO dbo.{table} (name, amount) VALUES ('cy', 7)")
        cursor.execute(f"UPDATE dbo.{table} SET amount = 11 WHERE name = 'ann'")
        cursor.execute(f"DELETE FROM dbo.{table} WHERE name = 'bo'")

    try:
        _round_trip(db, world, storage, source.id, change)
    finally:
        streams.delete_source(db, world["project"].id, source.id, world["user"])
        cursor.execute(f"EXEC sys.sp_cdc_disable_table @source_schema = N'dbo', @source_name = N'{table}', @capture_instance = N'all'")
        cursor.execute(f"DROP TABLE dbo.{table}")
        conn.close()


def _test_request(kind, settings, tables):
    from service_extraction.schemas import StreamTestRequest

    return StreamTestRequest(kind=kind, settings=settings, tables=tables)
