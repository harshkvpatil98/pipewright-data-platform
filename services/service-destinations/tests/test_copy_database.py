"""Copying a database into a destination (adoption-readiness A4, U4).

Needs the servers from `docker-compose.connectors.yml`: a PostgreSQL source
and a MySQL (and PostgreSQL) destination. Skips with the reason when
CONNECTORS_TEST_POSTGRES_URL / CONNECTORS_TEST_MYSQL_URL are not set.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401
from service_auth.models import User
from service_auth.schemas import UserRead
from service_destinations.copy_database import plan_copy, run_copy
from service_destinations.copy_schemas import CopyRequest
from service_destinations.schemas import DestinationCreate
from service_destinations.service import create_destination
from service_extraction.models import ExtractionConnection
from service_pipeline_runs.models import PipelineRun
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from shared_python.db import Base

POSTGRES = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")
MYSQL = os.environ.get("CONNECTORS_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(
    not (POSTGRES and MYSQL),
    reason="Set CONNECTORS_TEST_POSTGRES_URL and CONNECTORS_TEST_MYSQL_URL to copy between real servers.",
)


def _server(url: str) -> dict:
    parsed = make_url(url)
    return {"host": parsed.host, "port": parsed.port, "database": parsed.database,
            "username": parsed.username, "password": parsed.password}


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
def source_schema() -> Iterator[str]:
    schema = f"copy_src_{uuid.uuid4().hex[:8]}"
    engine = create_engine(POSTGRES)
    with engine.begin() as conn:
        conn.execute(text(f"CREATE SCHEMA {schema}"))
        conn.execute(text(f"""
            CREATE TABLE {schema}.customers (
                id SERIAL PRIMARY KEY,
                email VARCHAR(120) NOT NULL UNIQUE,
                joined TIMESTAMPTZ DEFAULT now(),
                profile JSONB,
                ref UUID
            )"""))
        conn.execute(text(f"""
            CREATE TABLE {schema}.orders (
                id BIGINT PRIMARY KEY,
                customer_id INTEGER REFERENCES {schema}.customers(id),
                amount NUMERIC(10, 2),
                note TEXT
            )"""))
        conn.execute(text(f"CREATE INDEX ON {schema}.orders (customer_id)"))
        conn.execute(text(f"CREATE VIEW {schema}.big_orders AS SELECT * FROM {schema}.orders WHERE amount > 100"))
        conn.execute(text(f"""
            INSERT INTO {schema}.customers (email, joined, profile, ref) VALUES
              ('ann@example.com', '2026-01-01T10:00:00+00', '{{"tier": "gold", "tags": [1, 2]}}', 'a0a0a0a0-0000-4000-8000-000000000001'),
              ('bo@example.com', NULL, NULL, NULL)"""))
        conn.execute(text(f"INSERT INTO {schema}.orders VALUES (1, 1, 120.50, 'first'), (2, 1, 9.99, NULL), (3, 2, NULL, 'blank amount')"))
    yield schema
    with engine.begin() as conn:
        conn.execute(text(f"DROP SCHEMA {schema} CASCADE"))
    engine.dispose()


@pytest.fixture()
def world(db: Session, source_schema: str, monkeypatch) -> dict:
    from cryptography.fernet import Fernet

    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    project = create_project(db, ProjectCreate(name="Shop", description=None), user)
    connection = ExtractionConnection(project_id=project.id, name="Shop Postgres", connector_type="postgresql",
                                      config_json={**_server(POSTGRES), "schema": source_schema})
    db.add(connection)
    db.commit()
    destination = create_destination(
        db, project.id, DestinationCreate(name="Reporting MySQL", destination_type="mysql", config_json=_server(MYSQL)), user,
    )
    suffix = uuid.uuid4().hex[:6]
    return {"project": project, "user": user, "connection": connection, "destination": destination,
            "tables": [f"{source_schema}.customers", f"{source_schema}.orders"], "suffix": suffix}


@pytest.fixture()
def mysql_engine():
    engine = create_engine(MYSQL)
    yield engine
    engine.dispose()


def _request(world: dict, **kwargs) -> CopyRequest:
    return CopyRequest(connection_id=world["connection"].id, destination_id=world["destination"].id,
                       tables=world["tables"], **kwargs)


def _cleanup(engine, *names):
    with engine.begin() as conn:
        for name in names:
            conn.execute(text(f"DROP TABLE IF EXISTS {name}"))


def test_the_plan_maps_each_type_and_flags_what_does_not_come_across(db, world, mysql_engine) -> None:
    plan = plan_copy(db, world["project"].id, _request(world), world["user"])
    tables = {table.target: table for table in plan.tables}
    customers = {column.name: column for column in tables["customers"].columns}

    assert tables["customers"].primary_key == ["id"]
    assert customers["email"].target_type == "varchar(120)" and not customers["email"].nullable
    # Every UUID fits char(36): a note, not a loss.
    assert customers["ref"].target_type == "char(36)" and not customers["ref"].lossy
    assert "no uuid type" in customers["ref"].note
    # A zoned time is written in UTC: that is a loss, and said.
    assert customers["joined"].target_type == "datetime(6)" and customers["joined"].lossy
    assert customers["profile"].target_type == "json"
    orders = {column.name: column for column in tables["orders"].columns}
    assert orders["amount"].target_type == "decimal(10,2)" and not orders["amount"].lossy
    assert any("foreign key" in item for item in tables["orders"].not_carried)
    assert any("index" in item for item in tables["orders"].not_carried)
    assert any("unique" in item for item in tables["customers"].not_carried)
    assert plan.never_copied[0].startswith("1 view not copied")


def test_a_copy_carries_rows_keys_and_not_null_and_reports_the_rest(db, world, mysql_engine) -> None:
    _cleanup(mysql_engine, "customers", "orders")
    try:
        report = run_copy(db, world["project"].id, _request(world), world["user"])
        assert report.status == "succeeded"
        assert {t.target: t.rows_copied for t in report.tables} == {"customers": 2, "orders": 3}
        assert any("primary key" in item for item in report.tables[0].carried)

        inspector = inspect(mysql_engine)
        assert inspector.get_pk_constraint("customers")["constrained_columns"] == ["id"]
        email = next(c for c in inspector.get_columns("customers") if c["name"] == "email")
        assert email["nullable"] is False
        with mysql_engine.connect() as conn:
            ann = conn.execute(text("SELECT profile, ref FROM customers WHERE email = 'ann@example.com'")).one()
            amounts = [row[0] for row in conn.execute(text("SELECT amount FROM orders ORDER BY id"))]
        assert json.loads(ann[0]) == {"tier": "gold", "tags": [1, 2]}
        assert ann[1] == "a0a0a0a0-0000-4000-8000-000000000001"
        assert amounts == [Decimal("120.50"), Decimal("9.99"), None]
        assert db.get(PipelineRun, report.run_id).run_type == "database_copy"
    finally:
        _cleanup(mysql_engine, "orders", "customers")


def test_an_existing_table_is_left_alone_unless_replacing(db, world, mysql_engine) -> None:
    _cleanup(mysql_engine, "customers", "orders")
    try:
        run_copy(db, world["project"].id, _request(world), world["user"])
        again = run_copy(db, world["project"].id, _request(world), world["user"])
        assert {t.status for t in again.tables} == {"skipped"}
        replaced = run_copy(db, world["project"].id, _request(world, replace_existing=True), world["user"])
        assert {t.status for t in replaced.tables} == {"succeeded"}
        with mysql_engine.connect() as conn:
            assert conn.execute(text("SELECT COUNT(*) FROM orders")).scalar() == 3
    finally:
        _cleanup(mysql_engine, "orders", "customers")
