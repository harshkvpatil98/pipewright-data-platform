"""A query across a real PostgreSQL, a real MySQL and a dataset (D2, O4).

Needs the servers from `docker-compose.connectors.yml` and skips without them.
The project's own connections and dataset are used as a person would use
them, through `across_project.run`: names resolve, each database runs its
part in its own dialect, the dataset is read under the person's policies,
and the answer is what pandas gives over the same three tables.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the membership resolver
from api_gateway.config import settings
from service_auth.models import User
from service_auth.schemas import UserRead
from service_extraction.connectors import sql_database
from service_extraction.models import ExtractionConnection
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.schemas import ProjectCreate
from service_projects.service import create_project
from service_workbench import across_project
from service_workbench.models import QueryRun
from shared_python.db import Base
from shared_python.errors import BadRequestError
from shared_python.security.config_crypto import encrypt_sensitive_fields
from shared_python.storage.local import LocalStorageBackend

POSTGRES = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")
MYSQL = os.environ.get("CONNECTORS_TEST_MYSQL_URL")
pytestmark = pytest.mark.skipif(not (POSTGRES and MYSQL), reason=(
    "Set CONNECTORS_TEST_POSTGRES_URL and CONNECTORS_TEST_MYSQL_URL to query across real databases."))

RNG = np.random.default_rng(11)
ORDERS = pd.DataFrame({"id": np.arange(2_000), "customer_id": RNG.integers(0, 300, 2_000),
                       "amount": RNG.gamma(2.0, 40.0, 2_000).round(2)})
CUSTOMERS = pd.DataFrame({"id": np.arange(300), "region_id": RNG.integers(0, 4, 300)})
REGIONS_CSV = b"id,region,manager\n0,north,Ann\n1,south,Bo\n2,east,Cy\n3,west,Di\n"


@pytest.fixture()
def db(monkeypatch) -> Iterator[Session]:
    monkeypatch.setenv("APP_SECRET_ENCRYPTION_KEY", Fernet.generate_key().decode())
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _connection(db: Session, project_id, name: str, kind: str, url: str) -> ExtractionConnection:
    parsed = make_url(url)
    config = {"host": parsed.host, "port": parsed.port, "database": parsed.database,
              "username": parsed.username, "password": parsed.password}
    connection = ExtractionConnection(project_id=project_id, name=name, connector_type=kind,
                                      config_json=encrypt_sensitive_fields(config, ("password",)))
    db.add(connection)
    db.commit()
    return connection


@pytest.fixture()
def world(db: Session, tmp_path) -> Iterator[dict]:
    suffix = uuid.uuid4().hex[:8]
    tables = {"orders": f"orders_{suffix}", "customers": f"customers_{suffix}"}
    pg, my = create_engine(POSTGRES), create_engine(MYSQL)
    ORDERS.to_sql(tables["orders"], pg, index=False)
    CUSTOMERS.to_sql(tables["customers"], my, index=False)
    with pg.begin() as conn:
        conn.execute(text(f"ANALYZE {tables['orders']}"))
    row = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.commit()
    now = datetime.now(UTC)
    user = UserRead(id=row.id, username="owner", role="admin", is_active=True, created_at=now, updated_at=now)
    storage = LocalStorageBackend(str(tmp_path / "storage"))
    project = create_project(db, ProjectCreate(name="Sales", description=None), user)
    _connection(db, project.id, "Sales PG", "postgresql", POSTGRES)
    _connection(db, project.id, "CRM", "mysql", MYSQL)
    regions = ingest_project_file(
        db, project_id=project.id, dataset_name="Regions",
        upload_file=IngestionUpload(file_name="regions.csv", content_type="text/csv", file_bytes=REGIONS_CSV),
        storage_backend=storage, settings=settings, current_user=user,
    ).dataset
    try:
        yield {"project": project, "user": user, "storage": storage, "tables": tables, "regions": regions}
    finally:
        sql_database.dispose_cached_engines()
        with pg.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {tables['orders']}"))
        with my.begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {tables['customers']}"))
        pg.dispose()
        my.dispose()


def _run(db: Session, world: dict, sql: str):
    return across_project.run(db, world["project"].id, sql=sql, user=world["user"], storage_backend=world["storage"])


def test_postgresql_mysql_and_a_dataset_in_one_query(db: Session, world: dict) -> None:
    orders, customers = world["tables"]["orders"], world["tables"]["customers"]
    outcome = _run(db, world, f"""
        SELECT r.region, COUNT(*) AS orders, ROUND(SUM(o.amount), 2) AS sales
        FROM "Sales PG".public.{orders} AS o
        JOIN crm.{customers} AS c ON o.customer_id = c.id
        JOIN datasets."Regions" AS r ON c.region_id = r.id
        WHERE o.amount > 30
        GROUP BY r.region
        ORDER BY r.region
    """)
    merged = ORDERS[ORDERS.amount > 30].merge(CUSTOMERS, left_on="customer_id", right_on="id", suffixes=("", "_c"))
    merged = merged.merge(pd.DataFrame({"rid": [0, 1, 2, 3], "region": ["north", "south", "east", "west"]}),
                          left_on="region_id", right_on="rid")
    expected = merged.groupby("region").agg(orders=("amount", "size"), sales=("amount", "sum")).reset_index()
    got = pd.DataFrame(outcome.rows)
    assert list(got["region"]) == sorted(expected["region"])
    expected = expected.sort_values("region").reset_index(drop=True)
    assert list(got["orders"]) == list(expected["orders"])
    assert np.allclose(got["sales"], expected["sales"].round(2))

    by_source = {source.source: source for source in outcome.sources}
    pg_part = by_source[f"Sales PG.public.{orders}"]
    assert '"public"' in pg_part.ran and "> 30" in pg_part.ran  # PostgreSQL ran its filter, in its dialect
    assert "PostgreSQL's own statistics" in pg_part.estimate_how or pg_part.estimated is not None
    my_part = by_source[f"CRM.{customers}"]
    assert "`" in my_part.ran  # MySQL quoting
    history = db.query(QueryRun).filter(QueryRun.project_id == world["project"].id).all()
    assert len(history) == 1 and history[0].succeeded and history[0].connection_id is None


def test_a_name_typed_without_quotes_finds_the_connection_and_mistakes_are_named(db: Session, world: dict) -> None:
    orders = world["tables"]["orders"]
    outcome = _run(db, world, f"SELECT COUNT(*) AS n FROM sales_pg.public.{orders} o")
    assert outcome.rows == [{"n": len(ORDERS)}]
    with pytest.raises(BadRequestError, match="No database connection in this project is called 'shop'"):
        _run(db, world, "SELECT * FROM shop.public.orders")
    with pytest.raises(BadRequestError, match='No dataset in this project is called "Nope"'):
        _run(db, world, 'SELECT * FROM datasets."Nope"')
    failed = db.query(QueryRun).filter(QueryRun.succeeded.is_(False)).count()
    assert failed == 2  # kept in the history with what went wrong
