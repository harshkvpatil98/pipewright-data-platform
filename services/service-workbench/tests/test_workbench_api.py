"""The workbench API, end to end, against two real databases.

One SQLite database plays the platform's own store; a second plays the
customer's. Nothing is mocked, because the thing worth testing is that a query
typed into an editor reaches a database and comes back — and that the read-only
default survives every layer on the way.
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
from service_workbench import service as workbench_service
from service_workbench.router import build_router
from shared_python.db import Base
from shared_python.errors import NotFoundError, register_exception_handlers


def _memory_engine() -> sa.Engine:
    """One shared in-memory database, usable from the TestClient's thread."""
    return sa.create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )


@pytest.fixture()
def warehouse() -> Iterator[sa.Engine]:
    engine = _memory_engine()
    with engine.begin() as connection:
        connection.execute(
            sa.text(
                "CREATE TABLE orders ("
                "  id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL,"
                "  region TEXT, amount REAL)"
            )
        )
        connection.execute(
            sa.text(
                "INSERT INTO orders VALUES (1,10,'eu',10.0),(2,11,'us',20.0),(3,10,'eu',30.0)"
            )
        )
        connection.execute(sa.text("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)"))
        connection.execute(sa.text("INSERT INTO customers VALUES (10,'Ada'),(11,'Alan')"))
    yield engine
    engine.dispose()


def _environment(warehouse: sa.Engine, role: str):
    engine = _memory_engine()
    Base.metadata.create_all(engine)
    db: Session = sessionmaker(bind=engine, expire_on_commit=False)()

    user = User(id=uuid.uuid4(), username="analyst", password_hash="x", role=role, is_active=True)
    project = Project(
        id=uuid.uuid4(), name="Warehouse", slug="warehouse",
        owner_user_id=user.id, environment="development",
    )
    db.add_all([user, project])
    db.commit()

    connection_id = uuid.uuid4()

    def resolver(_db: Session, project_id: uuid.UUID, conn_id: uuid.UUID) -> sa.Engine:
        if conn_id != connection_id or project_id != project.id:
            raise NotFoundError("That database connection does not exist in this project.")
        return warehouse

    workbench_service.register_engine_resolver(resolver)
    current = UserRead(
        id=user.id, username=user.username, role=role, is_active=True,
        created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
    )

    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(build_router(lambda: db, lambda: current))
    return {
        "client": TestClient(app),
        "db": db,
        "engine": engine,
        "project": project.id,
        "connection": str(connection_id),
        "base": f"/projects/{project.id}/workbench",
    }


@pytest.fixture()
def env(warehouse) -> Iterator[dict]:
    made = _environment(warehouse, "admin")
    yield made
    workbench_service.register_engine_resolver(None)  # type: ignore[arg-type]
    made["db"].close()
    made["engine"].dispose()


@pytest.fixture()
def editor_env(warehouse) -> Iterator[dict]:
    made = _environment(warehouse, "editor")
    yield made
    workbench_service.register_engine_resolver(None)  # type: ignore[arg-type]
    made["db"].close()
    made["engine"].dispose()


def order_count(warehouse: sa.Engine) -> int:
    with warehouse.connect() as connection:
        return connection.execute(sa.text("SELECT COUNT(*) FROM orders")).scalar_one()


class TestPreview:
    def test_it_splits_a_script_without_running_it(self, env, warehouse) -> None:
        response = env["client"].post(
            f"{env['base']}/preview", json={"sql": "SELECT 1; DELETE FROM orders"}
        )
        assert response.status_code == 200
        body = response.json()
        assert [s["kind"] for s in body["statements"]] == ["read", "write"]
        # Preview is analysis: the DELETE it read must not have happened.
        assert order_count(warehouse) == 3

    def test_it_refuses_a_write_in_read_only_mode_and_explains(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/preview", json={"sql": "DELETE FROM orders"}
        ).json()
        assert body["verdict"]["allowed"] is False
        assert "read-only" in body["verdict"]["reason"]

    def test_it_allows_a_write_when_asked_for_and_permitted(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/preview",
            json={"sql": "DELETE FROM orders WHERE id = 1", "allow_writes": True},
        ).json()
        assert body["verdict"]["allowed"] is True
        assert body["verdict"]["needs_confirmation"] is True
        assert body["policy"]["allow_writes"] is True

    def test_an_editor_cannot_get_write_mode(self, editor_env) -> None:
        body = editor_env["client"].post(
            f"{editor_env['base']}/preview",
            json={"sql": "DELETE FROM orders", "allow_writes": True},
        ).json()
        # Asking is not granting: bypassing every review the platform applies
        # is not something the editor role carries.
        assert body["policy"]["allow_writes"] is False
        assert body["verdict"]["allowed"] is False

    def test_it_warns_about_an_unbounded_delete(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/preview", json={"sql": "DELETE FROM orders", "allow_writes": True}
        ).json()
        assert any("every row" in warning for warning in body["verdict"]["warnings"])

    def test_it_reports_the_parameters_a_script_needs(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/preview", json={"sql": "SELECT * FROM orders WHERE region = :region"}
        ).json()
        assert body["parameters"] == ["region"]


class TestRunning:
    def test_a_select_returns_rows(self, env) -> None:
        response = env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "SELECT id, region FROM orders ORDER BY id"},
        )
        assert response.status_code == 200, response.text
        first = response.json()["statements"][0]
        assert first["columns"] == ["id", "region"]
        assert first["rows"][0] == {"id": 1, "region": "eu"}

    def test_the_response_says_which_policy_was_in_force(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "SELECT 1"},
        ).json()
        # A client must not be able to believe it is read-only when it is not.
        assert body["policy"] == "read-only"

    def test_a_write_is_refused_in_the_default_mode(self, env, warehouse) -> None:
        response = env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "DELETE FROM orders"},
        )
        assert response.status_code == 403
        assert order_count(warehouse) == 3

    def test_a_write_runs_when_asked_for(self, env, warehouse) -> None:
        response = env["client"].post(
            f"{env['base']}/run",
            json={
                "connection_id": env["connection"],
                "sql": "DELETE FROM orders WHERE id = 1",
                "allow_writes": True,
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["statements"][0]["rows_affected"] == 1
        assert order_count(warehouse) == 2

    def test_an_editor_asking_for_write_mode_is_told_why_not(self, editor_env, warehouse) -> None:
        response = editor_env["client"].post(
            f"{editor_env['base']}/run",
            json={
                "connection_id": editor_env["connection"],
                "sql": "DELETE FROM orders",
                "allow_writes": True,
            },
        )
        assert response.status_code == 400
        assert "admin role" in response.json()["detail"]
        assert order_count(warehouse) == 3

    def test_parameters_are_bound(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/run",
            json={
                "connection_id": env["connection"],
                "sql": "SELECT id FROM orders WHERE region = :region",
                "parameters": {"region": "eu"},
            },
        ).json()
        assert [row["id"] for row in body["statements"][0]["rows"]] == [1, 3]

    def test_an_unknown_connection_is_not_found(self, env) -> None:
        response = env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": str(uuid.uuid4()), "sql": "SELECT 1"},
        )
        assert response.status_code == 404

    def test_a_broken_query_reports_the_database_message(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "SELECT * FROM nope"},
        ).json()
        assert "nope" in body["statements"][0]["error"]


class TestHistory:
    def test_a_run_is_recorded(self, env) -> None:
        env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "SELECT 1 AS a"},
        )
        items = env["client"].get(f"{env['base']}/history").json()["items"]
        assert items[0]["sql"] == "SELECT 1 AS a"
        assert items[0]["succeeded"] is True
        assert items[0]["rows_returned"] == 1

    def test_a_failed_run_is_recorded_with_its_error(self, env) -> None:
        env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "SELECT * FROM nope"},
        )
        entry = env["client"].get(f"{env['base']}/history").json()["items"][0]
        assert entry["succeeded"] is False
        assert "nope" in entry["error"]

    def test_a_refused_write_is_still_recorded(self, env) -> None:
        # The attempt happened, and that is the fact an audit needs.
        env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "DELETE FROM orders"},
        )
        entry = env["client"].get(f"{env['base']}/history").json()["items"][0]
        assert entry["wrote"] is True
        assert entry["succeeded"] is False

    def test_history_never_holds_results(self, env) -> None:
        env["client"].post(
            f"{env['base']}/run",
            json={"connection_id": env["connection"], "sql": "SELECT region FROM orders"},
        )
        entry = env["client"].get(f"{env['base']}/history").json()["items"][0]
        # Retaining a customer's rows is not something anybody asked for.
        assert "eu" not in str(entry)
        assert set(entry) == {
            "id", "sql", "statement_count", "wrote", "succeeded", "duration_ms",
            "rows_returned", "rows_affected", "error", "created_at",
        }


class TestSavedQueries:
    def test_saving_and_listing(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/queries",
            json={"name": "EU orders", "sql": "SELECT * FROM orders WHERE region = :region"},
        )
        assert created.status_code == 201, created.text
        assert created.json()["parameters"] == {"region": None}
        assert env["client"].get(f"{env['base']}/queries").json()["items"][0]["name"] == "EU orders"

    def test_a_duplicate_name_is_refused(self, env) -> None:
        env["client"].post(f"{env['base']}/queries", json={"name": "x", "sql": "SELECT 1"})
        again = env["client"].post(f"{env['base']}/queries", json={"name": "x", "sql": "SELECT 2"})
        assert again.status_code == 409

    def test_saving_something_that_will_not_parse_is_refused(self, env) -> None:
        response = env["client"].post(f"{env['base']}/queries", json={"name": "y", "sql": ";;;"})
        assert response.status_code == 400

    def test_editing_the_sql_rediscovers_its_parameters(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/queries", json={"name": "z", "sql": "SELECT :a"}
        ).json()
        updated = env["client"].patch(
            f"{env['base']}/queries/{created['id']}", json={"sql": "SELECT :b, :c"}
        ).json()
        assert set(updated["parameters"]) == {"b", "c"}

    def test_running_a_saved_query_counts(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/queries", json={"name": "counted", "sql": "SELECT 1"}
        ).json()
        env["client"].post(
            f"{env['base']}/run",
            json={
                "connection_id": env["connection"],
                "sql": "SELECT 1",
                "saved_query_id": created["id"],
            },
        )
        listed = env["client"].get(f"{env['base']}/queries").json()["items"][0]
        assert listed["run_count"] == 1
        assert listed["last_run_at"] is not None

    def test_deleting(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/queries", json={"name": "gone", "sql": "SELECT 1"}
        ).json()
        assert env["client"].delete(f"{env['base']}/queries/{created['id']}").status_code == 204
        assert env["client"].get(f"{env['base']}/queries").json()["items"] == []


class TestSchemaAndCompletion:
    def test_the_schema_lists_tables(self, env) -> None:
        body = env["client"].get(f"{env['base']}/schema/{env['connection']}").json()
        assert {table["name"] for table in body["tables"]} == {"orders", "customers"}
        assert body["dialect"] == "sqlite"

    def test_asking_for_a_table_loads_its_columns(self, env) -> None:
        body = env["client"].get(
            f"{env['base']}/schema/{env['connection']}", params={"table": "orders"}
        ).json()
        orders = next(table for table in body["tables"] if table["name"] == "orders")
        assert orders["loaded"] is True
        assert {column["name"] for column in orders["columns"]} == {
            "id", "customer_id", "region", "amount"
        }

    def test_an_unknown_table_is_not_found(self, env) -> None:
        response = env["client"].get(
            f"{env['base']}/schema/{env['connection']}", params={"table": "ghost"}
        )
        assert response.status_code == 404

    def test_completions_after_from_are_tables(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/completions/{env['connection']}",
            json={"sql": "SELECT * FROM ord"},
        ).json()
        assert body["items"][0]["label"] == "orders"

    def test_completions_work_for_a_script_too_long_for_a_url(self, env) -> None:
        """A URL that long is refused by most proxies before it reaches here.

        Autocomplete would have worked on a short query and stopped working
        exactly as somebody's script got big enough to need it.
        """
        padding = "-- a comment line to make this long\n" * 1_000
        sql = f"{padding}SELECT * FROM ord"
        assert len(sql) > 30_000
        body = env["client"].post(
            f"{env['base']}/completions/{env['connection']}",
            json={"sql": sql, "offset": len(sql)},
        ).json()
        assert body["items"][0]["label"] == "orders"

    def test_completions_after_a_dot_are_that_table_s_columns(self, env) -> None:
        sql = "SELECT o. FROM orders o"
        body = env["client"].post(
            f"{env['base']}/completions/{env['connection']}",
            json={"sql": sql, "offset": len("SELECT o.")},
        ).json()
        # Columns are reflected on demand, only for tables the statement names.
        assert {item["label"] for item in body["items"]} == {
            "id", "customer_id", "region", "amount"
        }


class TestExplain:
    def test_it_returns_a_plan(self, env) -> None:
        body = env["client"].post(
            f"{env['base']}/explain",
            json={"connection_id": env["connection"], "sql": "SELECT * FROM orders WHERE region = 'eu'"},
        ).json()
        assert body["dialect"] == "sqlite"
        assert body["text"]

    def test_explaining_a_delete_does_not_perform_it(self, env, warehouse) -> None:
        env["client"].post(
            f"{env['base']}/explain",
            json={"connection_id": env["connection"], "sql": "DELETE FROM orders"},
        )
        assert order_count(warehouse) == 3


class TestNotebooks:
    def test_creating_with_cells_and_reading_back(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/notebooks",
            json={
                "name": "Analysis",
                "connection_id": env["connection"],
                "cells": [
                    {"kind": "markdown", "source": "# Orders"},
                    {"kind": "sql", "source": "SELECT * FROM orders", "output_name": "orders"},
                ],
            },
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert [cell["kind"] for cell in body["cells"]] == ["markdown", "sql"]
        assert [cell["position"] for cell in body["cells"]] == [0, 1]

    def test_a_cell_that_would_not_run_cannot_be_saved(self, env) -> None:
        response = env["client"].post(
            f"{env['base']}/notebooks",
            json={"name": "Bad", "cells": [{"kind": "sql", "output_name": "not a name"}]},
        )
        assert response.status_code == 400

    def test_running_a_notebook_threads_frames_between_cells(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/notebooks",
            json={
                "name": "Chained",
                "connection_id": env["connection"],
                "cells": [
                    {"kind": "sql", "source": "SELECT region FROM orders", "output_name": "raw"},
                    {
                        "kind": "recipe",
                        "output_name": "clean",
                        "config": {
                            "input": "raw",
                            "steps": [
                                {"step_type": "tool", "config": {"tool": "text.upper", "column": "region"}}
                            ],
                        },
                    },
                ],
            },
        ).json()
        body = env["client"].post(
            f"{env['base']}/notebooks/{created['id']}/run", json={}
        ).json()
        assert all(cell["ok"] for cell in body["cells"]), [c["error"] for c in body["cells"]]
        assert body["cells"][1]["rows"][0]["region"] == "EU"
        assert body["cells"][1]["bindings"] == {
            "raw": "3 rows x 1 columns",
            "clean": "3 rows x 1 columns",
        }

    def test_running_only_to_a_cell(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/notebooks",
            json={
                "name": "Partial",
                "connection_id": env["connection"],
                "cells": [
                    {"kind": "sql", "source": "SELECT 1 AS a"},
                    {"kind": "sql", "source": "SELECT 2 AS b"},
                ],
            },
        ).json()
        body = env["client"].post(
            f"{env['base']}/notebooks/{created['id']}/run", json={"only_to": 0}
        ).json()
        assert len(body["cells"]) == 1

    def test_updating_replaces_the_cells_whole(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/notebooks",
            json={"name": "Edited", "cells": [{"kind": "sql", "source": "SELECT 1"}]},
        ).json()
        updated = env["client"].patch(
            f"{env['base']}/notebooks/{created['id']}",
            json={"cells": [{"kind": "markdown", "source": "# only this"}]},
        ).json()
        assert len(updated["cells"]) == 1
        assert updated["cells"][0]["kind"] == "markdown"

    def test_deleting(self, env) -> None:
        created = env["client"].post(
            f"{env['base']}/notebooks", json={"name": "Temp", "cells": []}
        ).json()
        assert env["client"].delete(f"{env['base']}/notebooks/{created['id']}").status_code == 204
        assert env["client"].get(f"{env['base']}/notebooks").json()["items"] == []


class TestPlatformSurfaces:
    def test_the_sandbox_reports_itself_honestly(self, env) -> None:
        body = env["client"].get("/workbench/sandbox").json()
        assert isinstance(body["usable"], bool)
        assert body["allowed_imports"]
        if not body["usable"]:
            # A deployment that cannot enforce the limits says which one.
            assert body["reason"]
            assert any(not item["available"] for item in body["capabilities"])

    def test_a_recipe_round_trips_through_the_api(self, env) -> None:
        steps = [{"step_type": "tool", "config": {"tool": "text.trim", "column": "name"}}]
        text = env["client"].post(
            "/workbench/recipe/yaml", json={"steps": steps, "name": "Tidy"}
        ).json()["yaml"]
        parsed = env["client"].post("/workbench/recipe/parse", json={"yaml": text}).json()
        assert parsed["steps"] == steps
        assert parsed["name"] == "Tidy"

    def test_bad_yaml_is_a_message_not_a_crash(self, env) -> None:
        response = env["client"].post(
            "/workbench/recipe/parse", json={"yaml": "steps:\n  - step: x\n   bad: 1"}
        )
        assert response.status_code == 400
        assert "YAML" in response.json()["detail"]
