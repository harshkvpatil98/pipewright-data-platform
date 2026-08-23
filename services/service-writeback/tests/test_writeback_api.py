"""The write-back API, end to end, against two real databases.

One SQLite database plays the platform's own store (change sets, projects,
users); a second plays the customer's warehouse. Nothing here is mocked, because
the thing worth testing is that a cell edited through HTTP actually lands in a
row -- and that everything guarding that path still refuses when it should.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
import sqlalchemy as sa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

import api_gateway.metadata  # noqa: F401  -- registers every mapper
from service_auth.models import User
from service_auth.schemas import UserRead
from service_projects.models import Project
from service_writeback import service as writeback_service
from service_writeback.router import build_router
from shared_python.db import Base
from shared_python.errors import NotFoundError, register_exception_handlers

OTHER_PROJECT = uuid.uuid4()


def _memory_engine() -> sa.Engine:
    """One shared in-memory database, usable from the TestClient's thread.

    The default in-memory engine opens a connection per thread and each gets its
    own empty database, so the handler would not see the fixture's tables.
    """
    return sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )


@pytest.fixture()
def warehouse() -> Iterator[sa.Engine]:
    """The customer's database -- the thing being written to."""
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE orders ("
                "  id INTEGER PRIMARY KEY,"
                "  region TEXT,"
                "  amount REAL NOT NULL"
                ")"
            )
        )
        connection.execute(
            sa.text("INSERT INTO orders VALUES (1,'eu',10.0),(2,'us',20.0),(3,'eu',30.0)")
        )
        connection.execute(sa.text("CREATE TABLE ledger (entry TEXT, amount REAL)"))
        connection.execute(sa.text("INSERT INTO ledger VALUES ('a', 1.0),('a', 2.0)"))
        # Big enough that a share of it is a meaningful risk signal.
        connection.execute(sa.text("CREATE TABLE wide (id INTEGER PRIMARY KEY, tag TEXT)"))
        connection.execute(
            sa.text("INSERT INTO wide (id, tag) VALUES " + ",".join(f"({n},'a')" for n in range(200)))
        )
    yield engine
    engine.dispose()


@pytest.fixture()
def env(warehouse: sa.Engine) -> Iterator[dict]:
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    Sessions = sessionmaker(bind=engine, expire_on_commit=False)
    db: Session = Sessions()

    user = User(
        id=uuid.uuid4(),
        username="editor",
        password_hash="x",
        role="admin",
        is_active=True,
    )
    project = Project(
        id=uuid.uuid4(),
        name="Warehouse",
        slug="warehouse",
        owner_user_id=user.id,
        environment="production",
    )
    db.add_all([user, project])
    db.commit()

    connection_id = uuid.uuid4()

    def resolver(_db: Session, project_id: uuid.UUID, conn_id: uuid.UUID) -> sa.Engine:
        # Stands in for the gateway's resolver, including its project scoping.
        if conn_id != connection_id or project_id != project.id:
            raise NotFoundError("That database connection does not exist in this project.")
        return warehouse

    writeback_service.register_engine_resolver(resolver)

    current_user = UserRead(
        id=user.id,
        username=user.username,
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(lambda: db, lambda: current_user))

    yield {
        "client": TestClient(app),
        "db": db,
        "project": project.id,
        "connection": connection_id,
        "warehouse": warehouse,
        "base": f"/projects/{project.id}/writeback",
    }

    writeback_service.register_engine_resolver(None)  # type: ignore[arg-type]
    db.close()
    engine.dispose()


def rows(warehouse: sa.Engine) -> list[tuple]:
    with warehouse.connect() as connection:
        return [
            tuple(row)
            for row in connection.execute(sa.text("SELECT id, region, amount FROM orders ORDER BY id"))
        ]


def new_change_set(env, table="orders", **extra) -> str:
    response = env["client"].post(
        f"{env['base']}/change-sets",
        json={
            "connection_id": str(env["connection"]),
            "table_name": table,
            "name": "Fix regions",
            **extra,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


class TestTableShape:
    def test_reports_the_key_it_would_use(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/tables/{env['connection']}", params={"table": "orders"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["editable"] is True
        assert body["identity"]["kind"] == "primary_key"
        assert body["identity"]["columns"] == ["id"]
        assert body["identity"]["durable"] is True
        assert body["columns"] == ["id", "region", "amount"]
        assert "amount" not in body["nullable"]

    def test_a_keyless_table_is_reported_as_not_editable(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/tables/{env['connection']}", params={"table": "ledger"}
        )
        assert response.status_code == 200
        body = response.json()
        assert body["editable"] is False
        assert body["identity"]["kind"] == "none"
        assert body["identity"]["reason"]

    def test_an_unknown_connection_is_not_found(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/tables/{uuid.uuid4()}", params={"table": "orders"}
        )
        assert response.status_code == 404

    def test_an_unknown_table_says_so_without_leaking_the_driver(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/tables/{env['connection']}", params={"table": "nope"}
        )
        assert response.status_code == 400
        assert "nope" in response.json()["detail"]


class TestStaging:
    def test_a_keyless_table_cannot_start_a_change_set(self, env) -> None:
        response = env["client"].post(
            f"{env['base']}/change-sets",
            json={
                "connection_id": str(env["connection"]),
                "table_name": "ledger",
                "name": "nope",
            },
        )
        assert response.status_code == 400

    def test_edits_are_numbered_in_the_order_they_arrive(self, env) -> None:
        change_set = new_change_set(env)
        for value in ("emea", "apac"):
            response = env["client"].post(
                f"{env['base']}/change-sets/{change_set}/edits",
                json={
                    "edits": [
                        {"kind": "set_cell", "key": {"id": 1}, "column": "region", "value": value}
                    ]
                },
            )
            assert response.status_code == 200, response.text
        body = response.json()
        assert [edit["sequence"] for edit in body["edits"]] == [0, 1]
        assert body["edits"][0]["description"].startswith("Set region to 'emea'")

    def test_an_edit_naming_a_missing_column_is_refused_before_it_is_stored(self, env) -> None:
        change_set = new_change_set(env)
        response = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "region", "value": "eu"},
                    {"kind": "set_cell", "key": {"id": 1}, "column": "nope", "value": "x"},
                ]
            },
        )
        assert response.status_code == 400
        # The valid first edit must not have been kept.
        detail = env["client"].get(f"{env['base']}/change-sets/{change_set}").json()
        assert detail["edits"] == []

    def test_an_edit_can_be_removed(self, env) -> None:
        change_set = new_change_set(env)
        body = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "region", "value": "a"},
                    {"kind": "set_cell", "key": {"id": 2}, "column": "region", "value": "b"},
                ]
            },
        ).json()
        removed = body["edits"][0]["id"]
        after = env["client"].delete(
            f"{env['base']}/change-sets/{change_set}/edits/{removed}"
        )
        assert after.status_code == 200
        assert [edit["sequence"] for edit in after.json()["edits"]] == [1]

    def test_a_change_set_from_another_project_is_not_found(self, env) -> None:
        change_set = new_change_set(env)
        response = env["client"].get(
            f"/projects/{OTHER_PROJECT}/writeback/change-sets/{change_set}"
        )
        assert response.status_code == 404


class TestPlan:
    def test_rehearsing_writes_nothing(self, env) -> None:
        before = rows(env["warehouse"])
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "region", "value": "emea"}
                ]
            },
        )
        response = env["client"].post(f"{env['base']}/change-sets/{change_set}/plan")
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["rows_affected"] == 1
        assert body["table_rows"] == 3
        assert body["needs_confirmation"] is False
        assert body["statements"][0]["actual_rows"] == 1
        assert rows(env["warehouse"]) == before

    def test_an_empty_change_set_has_nothing_to_plan(self, env) -> None:
        change_set = new_change_set(env)
        response = env["client"].post(f"{env['base']}/change-sets/{change_set}/plan")
        assert response.status_code == 400
        assert "empty" in response.json()["detail"]

    def test_a_dropped_column_is_reported_as_irreversible(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={"edits": [{"kind": "drop_column", "column": "region"}]},
        )
        body = env["client"].post(f"{env['base']}/change-sets/{change_set}/plan").json()
        assert body["has_irreversible"] is True


class TestCommit:
    def test_a_cell_edit_reaches_the_table(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 2}, "column": "region", "value": "latam"}
                ]
            },
        )
        response = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/commit", json={}
        )
        assert response.status_code == 200, response.text
        assert response.json()["rows_affected"] == 1
        assert rows(env["warehouse"])[1] == (2, "latam", 20.0)

    def test_the_committed_sql_is_kept(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "amount", "value": 99.0}
                ]
            },
        )
        env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={})
        detail = env["client"].get(f"{env['base']}/change-sets/{change_set}").json()
        assert detail["status"] == "committed"
        assert detail["rows_affected"] == 1
        assert detail["committed_at"] is not None

    def test_a_stale_previous_value_stops_the_write(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {
                        "kind": "set_cell",
                        "key": {"id": 1},
                        "column": "region",
                        "value": "emea",
                        "previous": "not-what-is-there",
                        "has_previous": True,
                    }
                ]
            },
        )
        response = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/commit", json={}
        )
        assert response.status_code == 409
        assert rows(env["warehouse"])[0] == (1, "eu", 10.0)
        # A failed commit stays a draft so it can be retried after a look.
        assert env["client"].get(f"{env['base']}/change-sets/{change_set}").json()["status"] == "draft"

    def test_committing_twice_is_refused(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "region", "value": "x"}
                ]
            },
        )
        assert (
            env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={}).status_code
            == 200
        )
        again = env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={})
        assert again.status_code == 409
        assert "committed" in again.json()["detail"]

    def test_a_small_change_to_a_small_table_is_not_treated_as_wide(self, env) -> None:
        """One row of three is 33% and still nothing to be afraid of."""
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": row}, "column": "region", "value": "x"}
                    for row in (1, 2, 3)
                ]
            },
        )
        response = env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={})
        assert response.status_code == 200, response.text
        assert {row[1] for row in rows(env["warehouse"])} == {"x"}

    def test_a_wide_change_needs_the_table_name_typed_back(self, env) -> None:
        change_set = new_change_set(env, table="wide")
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": row}, "column": "tag", "value": "x"}
                    for row in range(40)
                ]
            },
        )
        blocked = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/commit", json={}
        )
        assert blocked.status_code == 400
        assert "wide" in blocked.json()["detail"]
        with env["warehouse"].connect() as connection:
            assert connection.execute(
                sa.text("SELECT COUNT(*) FROM wide WHERE tag = 'x'")
            ).scalar_one() == 0

        allowed = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/commit",
            json={"confirm_table_name": "wide"},
        )
        assert allowed.status_code == 200
        with env["warehouse"].connect() as connection:
            assert connection.execute(
                sa.text("SELECT COUNT(*) FROM wide WHERE tag = 'x'")
            ).scalar_one() == 40

    def test_a_discarded_change_set_cannot_be_committed(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "region", "value": "x"}
                ]
            },
        )
        assert (
            env["client"].post(f"{env['base']}/change-sets/{change_set}/discard").status_code == 200
        )
        response = env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={})
        assert response.status_code == 409
        assert rows(env["warehouse"])[0][1] == "eu"

    def test_inserting_and_deleting_rows(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "insert_row", "values": {"id": 9, "region": "apac", "amount": 5.0}},
                    {"kind": "delete_row", "key": {"id": 3}},
                ]
            },
        )
        assert (
            env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={}).status_code
            == 200
        )
        assert rows(env["warehouse"]) == [(1, "eu", 10.0), (2, "us", 20.0), (9, "apac", 5.0)]

    def test_a_column_added_in_one_batch_can_be_filled_in_the_next(self, env) -> None:
        """The Studio gesture: add a column, then type into it.

        The two batches arrive as separate requests, so staging has to validate
        against the change set rather than against the table as it is now.
        """
        change_set = new_change_set(env)
        first = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={"edits": [{"kind": "add_column", "column": "note", "column_type": "text"}]},
        )
        assert first.status_code == 200, first.text
        second = env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "note", "value": "hi"}
                ]
            },
        )
        assert second.status_code == 200, second.text
        assert (
            env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={}).status_code
            == 200
        )
        with env["warehouse"].connect() as connection:
            assert (
                connection.execute(sa.text("SELECT note FROM orders WHERE id = 1")).scalar_one()
                == "hi"
            )

    def test_adding_a_column_changes_the_shape(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={"edits": [{"kind": "add_column", "column": "note", "column_type": "text"}]},
        )
        assert (
            env["client"].post(f"{env['base']}/change-sets/{change_set}/commit", json={}).status_code
            == 200
        )
        shape = env["client"].get(
            f"{env['base']}/tables/{env['connection']}", params={"table": "orders"}
        ).json()
        assert "note" in shape["columns"]


class TestMigrationExport:
    def test_the_same_change_can_be_taken_away_as_sql(self, env) -> None:
        change_set = new_change_set(env)
        env["client"].post(
            f"{env['base']}/change-sets/{change_set}/edits",
            json={
                "edits": [
                    {"kind": "set_cell", "key": {"id": 1}, "column": "region", "value": "emea"}
                ]
            },
        )
        response = env["client"].get(f"{env['base']}/change-sets/{change_set}/migration")
        assert response.status_code == 200
        body = response.json()
        assert body["filename"].startswith("orders_")
        assert "UPDATE" in body["sql"]
        # Exporting must not be a way to write.
        assert rows(env["warehouse"])[0] == (1, "eu", 10.0)


class TestReadingRows:
    def test_rows_come_back_in_key_order(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/rows/{env['connection']}", params={"table": "orders"}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["key_columns"] == ["id"]
        assert body["total"] == 3
        assert [row["id"] for row in body["rows"]] == [1, 2, 3]

    def test_paging_is_stable(self, env) -> None:
        first = env["client"].get(
            f"{env['base']}/rows/{env['connection']}",
            params={"table": "wide", "limit": 10, "offset": 0},
        ).json()
        second = env["client"].get(
            f"{env['base']}/rows/{env['connection']}",
            params={"table": "wide", "limit": 10, "offset": 10},
        ).json()
        assert [row["id"] for row in first["rows"]] == list(range(10))
        assert [row["id"] for row in second["rows"]] == list(range(10, 20))
        assert first["total"] == second["total"] == 200

    def test_sorting_by_a_repeated_column_still_pages_deterministically(self, env) -> None:
        """`tag` is the same in every row, so the key has to break the tie."""
        pages = [
            env["client"].get(
                f"{env['base']}/rows/{env['connection']}",
                params={"table": "wide", "limit": 5, "offset": offset, "order_by": "tag"},
            ).json()["rows"]
            for offset in (0, 5)
        ]
        seen = [row["id"] for page in pages for row in page]
        assert seen == list(range(10))

    def test_a_keyless_table_cannot_be_read_for_editing(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/rows/{env['connection']}", params={"table": "ledger"}
        )
        assert response.status_code == 400
        assert response.json()["detail"]

    def test_an_unknown_sort_column_is_refused(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/rows/{env['connection']}",
            params={"table": "orders", "order_by": "nope"},
        )
        assert response.status_code == 400

    def test_reading_never_writes(self, env) -> None:
        before = rows(env["warehouse"])
        env["client"].get(
            f"{env['base']}/rows/{env['connection']}",
            params={"table": "orders", "descending": True},
        )
        assert rows(env["warehouse"]) == before
