"""The nightly schema watch, against a real database and a real connector.

The thing worth testing here is not the comparison -- `service_quality.drift`
owns that and has its own tests -- but the parts that only exist because this
runs on a schedule and writes to a database: that a second sweep compares
against the first, that a change opens exactly one incident however many nights
it recurs, that a schema going back to normal closes it, and that "we could not
look" never gets recorded as "the columns are gone".
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401  -- resolves every mapper
import service_connectors  # noqa: F401  -- assembles the catalogue
from service_auth.models import User
from service_connectors.models import ConnectorSchemaSnapshot
from service_connectors.protocol import ConnectorError, StreamColumn, StreamRef
from service_connectors.sweep import fingerprint, sweep_project, watched_streams
from service_extraction.models import ExtractionConnection
from service_observability.incidents import find_active
from service_projects.models import Project
from shared_python.db import Base


@pytest.fixture()
def db():
    # `StaticPool` with `check_same_thread` off because the route tests below
    # drive the app through a TestClient, which runs it on another thread and
    # would otherwise be handed a connection SQLite refuses to share.
    engine = sa.create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=sa.pool.StaticPool,
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def project(db):
    user = User(id=uuid.uuid4(), username="u", password_hash="x", role="admin", is_active=True)
    row = Project(id=uuid.uuid4(), name="P", slug="p", owner_user_id=user.id)
    db.add_all([user, row])
    db.commit()
    return row


@pytest.fixture()
def connection(db, project):
    row = ExtractionConnection(
        project_id=project.id,
        name="Warehouse",
        connector_type="postgresql",
        config_json={"host": "db", "database": "d", "username": "u", "password": "p"},
    )
    db.add(row)
    db.commit()
    return row


class _Source:
    """A connector that answers with whatever the test put in it.

    The network is the only thing replaced: `sweep_project` calls `discover`
    and `columns` exactly as it would on a real source, and everything after
    that -- the comparison, the snapshot, the incident -- is the real code.
    """

    def __init__(self, columns: dict[str, str] | None, *, streams=("orders",), fail=None):
        self.columns_by_name = columns
        self.streams = streams
        self.fail = fail
        self.calls = 0

    def install(self, monkeypatch, connector_type: str = "postgresql"):
        from service_connectors import registry

        real = registry.get(connector_type)
        monkeypatch.setattr(
            type(real), "discover", lambda _self, _config: [
                StreamRef(name=name, namespace="public") for name in self.streams
            ],
            raising=False,
        )

        def columns(_self, _config, stream):
            self.calls += 1
            if self.fail:
                raise ConnectorError(self.fail)
            assert self.columns_by_name is not None
            return [
                StreamColumn(name=name, data_type=kind)
                for name, kind in self.columns_by_name.items()
            ]

        monkeypatch.setattr(type(real), "columns", columns, raising=False)
        return self


def _sweep(db, project, **kwargs: Any):
    report = sweep_project(db, project_id=project.id, **kwargs)
    db.commit()
    return report


class TestTheFirstLook:
    def test_it_records_the_schema_and_calls_nothing_drift(
        self, db, project, connection, monkeypatch
    ) -> None:
        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        report = _sweep(db, project)

        assert report.connections == 1
        outcome = report.results[0]
        assert outcome.checked and outcome.first_look
        assert not outcome.has_drift
        assert report.drifted == []

    def test_the_snapshot_is_what_the_next_sweep_compares_against(
        self, db, project, connection, monkeypatch
    ) -> None:
        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        _sweep(db, project)

        stored = db.scalars(sa.select(ConnectorSchemaSnapshot)).all()
        assert len(stored) == 1
        # Stored in the drift grader's vocabulary, not the database's: `integer`
        # and `int4` are the same column and must not read as a type change.
        assert stored[0].columns_json == {"id": "int", "region": "string"}
        assert stored[0].observed_at is not None

    def test_a_first_look_opens_no_incident(self, db, project, connection, monkeypatch) -> None:
        _Source({"id": "integer"}).install(monkeypatch)
        _sweep(db, project)
        assert find_active(db, project.id, fingerprint(connection.id, "public.orders")) is None


class TestDrift:
    def _first_then(self, db, project, connection, monkeypatch, before, after):
        _Source(before).install(monkeypatch)
        _sweep(db, project)
        _Source(after).install(monkeypatch)
        return _sweep(db, project)

    def test_a_removed_column_is_breaking_and_opens_an_incident(
        self, db, project, connection, monkeypatch
    ) -> None:
        report = self._first_then(
            db, project, connection, monkeypatch,
            {"id": "integer", "region": "text"},
            {"id": "integer"},
        )
        outcome = report.results[0]
        assert outcome.severity == "breaking"
        assert outcome.removed_columns == ["region"]

        incident = find_active(db, project.id, fingerprint(connection.id, "public.orders"))
        assert incident is not None
        assert incident.severity == "critical"
        assert incident.source_kind == "drift"
        assert incident.context_json["removed_columns"] == ["region"]
        assert outcome.incident_id == str(incident.id)

    def test_a_new_column_alone_is_not_breaking(
        self, db, project, connection, monkeypatch
    ) -> None:
        report = self._first_then(
            db, project, connection, monkeypatch,
            {"id": "integer"},
            {"id": "integer", "email": "text"},
        )
        outcome = report.results[0]
        assert outcome.added_columns == ["email"]
        assert outcome.severity != "breaking"

    def test_the_same_drift_two_nights_running_is_one_incident(
        self, db, project, connection, monkeypatch
    ) -> None:
        """The reason incidents exist at all: twenty nights is one problem."""
        self._first_then(
            db, project, connection, monkeypatch,
            {"id": "integer", "region": "text"},
            {"id": "integer"},
        )
        # The third sweep sees the same schema as the second, so the comparison
        # is clean -- which is the honest answer, and closes the incident.
        _Source({"id": "integer"}).install(monkeypatch)
        _sweep(db, project)

        all_incidents = db.scalars(
            sa.select(sa.text("id")).select_from(sa.table("incidents"))
        ).all()
        assert len(all_incidents) == 1

    def test_a_schema_that_goes_back_to_normal_closes_its_incident(
        self, db, project, connection, monkeypatch
    ) -> None:
        self._first_then(
            db, project, connection, monkeypatch,
            {"id": "integer", "region": "text"},
            {"id": "integer"},
        )
        assert find_active(db, project.id, fingerprint(connection.id, "public.orders")) is not None

        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        report = _sweep(db, project)

        assert report.results[0].added_columns == ["region"]
        # Adding it back is itself a change, so the incident stays open and
        # records the new occurrence rather than pretending nothing happened.
        assert find_active(db, project.id, fingerprint(connection.id, "public.orders")) is not None

        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        _sweep(db, project)
        closed = find_active(db, project.id, fingerprint(connection.id, "public.orders"))
        assert closed is None, "a stable schema should close the incident"

    def test_the_drift_count_accumulates_on_the_snapshot(
        self, db, project, connection, monkeypatch
    ) -> None:
        self._first_then(
            db, project, connection, monkeypatch,
            {"id": "integer", "region": "text"},
            {"id": "integer"},
        )
        stored = db.scalars(sa.select(ConnectorSchemaSnapshot)).one()
        assert stored.drift_count == 1
        assert stored.last_severity == "breaking"


class TestNotLooking:
    def test_a_source_that_will_not_answer_is_skipped_not_drifted(
        self, db, project, connection, monkeypatch
    ) -> None:
        """The failure this prevents: a dropped VPN filing a breaking incident."""
        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        _sweep(db, project)

        _Source(None, fail="connection refused").install(monkeypatch)
        report = _sweep(db, project)

        outcome = report.results[0]
        assert not outcome.checked
        assert "connection refused" in outcome.skipped_reason
        assert find_active(db, project.id, fingerprint(connection.id, "public.orders")) is None

        # And the last known good schema is still there to compare against.
        stored = db.scalars(sa.select(ConnectorSchemaSnapshot)).one()
        assert stored.columns_json == {"id": "int", "region": "string"}

    def test_a_connector_this_deployment_does_not_have_says_so(
        self, db, project, monkeypatch
    ) -> None:
        db.add(
            ExtractionConnection(
                project_id=project.id, name="Ghost", connector_type="not-a-connector",
                config_json={},
            )
        )
        db.commit()
        report = _sweep(db, project)
        assert report.results == []
        assert "not a connector" in report.skipped_connections[0]["reason"]

    def test_an_unavailable_driver_is_reported_rather_than_attempted(
        self, db, project, monkeypatch
    ) -> None:
        db.add(
            ExtractionConnection(
                project_id=project.id, name="Snow", connector_type="snowflake",
                config_json={},
            )
        )
        db.commit()
        report = _sweep(db, project)
        reasons = " ".join(entry["reason"] for entry in report.skipped_connections)
        assert "snowflake" in reasons.lower()


class TestRehearsal:
    def test_apply_false_records_nothing(self, db, project, connection, monkeypatch) -> None:
        """The first sweep of a busy project can open a lot of incidents."""
        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        sweep_project(db, project_id=project.id, open_incidents=True)
        db.commit()

        _Source({"id": "integer"}).install(monkeypatch)
        report = sweep_project(db, project_id=project.id, open_incidents=False)
        db.rollback()

        assert report.results[0].severity == "breaking"
        assert report.results[0].incident_id is None
        assert find_active(db, project.id, fingerprint(connection.id, "public.orders")) is None
        # And the stored schema is untouched, so a real sweep still compares
        # against the last thing actually observed.
        stored = db.scalars(sa.select(ConnectorSchemaSnapshot)).one()
        assert stored.columns_json == {"id": "int", "region": "string"}


class TestNarrowing:
    def test_a_sweep_can_be_limited_to_one_connection(
        self, db, project, connection, monkeypatch
    ) -> None:
        other = ExtractionConnection(
            project_id=project.id, name="Other", connector_type="postgresql", config_json={}
        )
        db.add(other)
        db.commit()
        _Source({"id": "integer"}).install(monkeypatch)

        report = _sweep(db, project, connection_id=connection.id)
        assert report.connections == 1
        assert {row.connection_id for row in report.results} == {str(connection.id)}

    def test_another_project_is_never_swept(self, db, project, connection, monkeypatch) -> None:
        user = db.scalars(sa.select(User)).first()
        elsewhere = Project(id=uuid.uuid4(), name="Q", slug="q", owner_user_id=user.id)
        db.add(elsewhere)
        db.commit()
        _Source({"id": "integer"}).install(monkeypatch)

        report = _sweep(db, elsewhere)
        assert report.connections == 0
        assert report.results == []


class TestTheStatusView:
    def test_it_lists_what_is_being_remembered(
        self, db, project, connection, monkeypatch
    ) -> None:
        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        _sweep(db, project)

        rows = watched_streams(db, project_id=project.id)
        assert len(rows) == 1
        assert rows[0]["stream"] == "public.orders"
        assert rows[0]["columns"] == 2
        assert rows[0]["connector_type"] == "postgresql"

    def test_the_summary_line_reads_as_a_sentence(
        self, db, project, connection, monkeypatch
    ) -> None:
        """It becomes the schedule's last-run message, which people read."""
        _Source({"id": "integer"}).install(monkeypatch)
        clean = _sweep(db, project)
        assert "no schema changes" in clean.summary_line()

        _Source({}).install(monkeypatch)
        # An empty column list is "could not describe it", not "no columns".
        empty = _sweep(db, project)
        assert empty.results[0].checked is False


class TestQualifiedNames:
    """Two tables can share a name; a snapshot key cannot.

    `public.orders` and `analytics.orders` are different tables. Filing both
    under `orders` compares the second against the first's columns -- drift
    reported between two unrelated tables -- and then collides on the unique
    index that makes the sweep idempotent.
    """

    def test_two_schemas_with_the_same_table_do_not_collide(
        self, db, project, connection, monkeypatch
    ) -> None:
        from service_connectors import registry
        from service_connectors.protocol import StreamColumn, StreamRef

        real = registry.get("postgresql")
        monkeypatch.setattr(
            type(real), "discover",
            lambda _self, _config: [
                StreamRef(name="orders", namespace="public"),
                StreamRef(name="orders", namespace="analytics"),
            ],
            raising=False,
        )
        # Deliberately different shapes: if they shared a key, the second would
        # be graded against the first and report a breaking change.
        shapes = {
            "public": {"id": "integer", "region": "text"},
            "analytics": {"id": "integer", "total": "numeric", "day": "date"},
        }
        monkeypatch.setattr(
            type(real), "columns",
            lambda _self, _config, stream: [
                StreamColumn(name=name, data_type=kind)
                for name, kind in shapes[stream.namespace].items()
            ],
            raising=False,
        )

        report = _sweep(db, project)
        assert {row.stream for row in report.results} == {"public.orders", "analytics.orders"}
        assert not report.drifted, "a first look at two tables is not drift"

        stored = {
            row.stream_name: row.columns_json
            for row in db.scalars(sa.select(ConnectorSchemaSnapshot)).all()
        }
        assert set(stored) == {"public.orders", "analytics.orders"}
        assert stored["analytics.orders"] == {"id": "int", "total": "float", "day": "datetime"}

        # And a second sweep still sees no change, which is the real proof that
        # each one was compared against itself.
        again = _sweep(db, project)
        assert not again.drifted


class TestTheStreamCap:
    """A cap that is not said out loud is a half-read reported as a whole one."""

    def test_the_summary_line_names_what_was_not_looked_at(
        self, db, project, connection, monkeypatch
    ) -> None:
        from service_connectors import sweep as sweep_module

        monkeypatch.setattr(sweep_module, "MAX_STREAMS_PER_CONNECTION", 2)
        _Source({"id": "integer"}, streams=("a", "b", "c", "d")).install(monkeypatch)

        report = _sweep(db, project)
        assert len(report.results) == 2
        assert report.truncated[0]["unwatched"] == 2
        assert report.truncated[0]["total"] == 4
        # The sentence that becomes the schedule's last-run message.
        line = report.summary_line()
        assert "2 further stream(s)" in line
        assert "not looked at" in line

    def test_a_sweep_within_the_cap_says_nothing_extra(
        self, db, project, connection, monkeypatch
    ) -> None:
        _Source({"id": "integer"}, streams=("a", "b")).install(monkeypatch)
        report = _sweep(db, project)
        assert report.truncated == []
        assert "not looked at" not in report.summary_line()


class TestTheScheduledJob:
    def test_the_schedule_type_is_accepted_and_normalised(self, db, project, connection) -> None:
        from service_schedules.validators import validate_and_normalize_target_config

        assert validate_and_normalize_target_config(
            db, project_id=project.id, schedule_type="connector_schema_watch", target={}
        ) == {}
        assert validate_and_normalize_target_config(
            db,
            project_id=project.id,
            schedule_type="connector_schema_watch",
            target={"connection_id": str(connection.id)},
        ) == {"connection_id": str(connection.id)}

    def test_a_connection_from_another_project_is_refused_at_creation(
        self, db, project, connection
    ) -> None:
        """Refused when the schedule is made, not silently every night."""
        from shared_python.errors import NotFoundError
        from service_schedules.validators import validate_and_normalize_target_config

        user = db.scalars(sa.select(User)).first()
        elsewhere = Project(id=uuid.uuid4(), name="Q", slug="q", owner_user_id=user.id)
        db.add(elsewhere)
        db.commit()

        with pytest.raises(NotFoundError):
            validate_and_normalize_target_config(
                db,
                project_id=elsewhere.id,
                schedule_type="connector_schema_watch",
                target={"connection_id": str(connection.id)},
            )

    def test_an_unknown_key_is_refused_rather_than_ignored(self, db, project) -> None:
        from shared_python.errors import BadRequestError
        from service_schedules.validators import validate_and_normalize_target_config

        with pytest.raises(BadRequestError, match="Unexpected keys"):
            validate_and_normalize_target_config(
                db,
                project_id=project.id,
                schedule_type="connector_schema_watch",
                target={"conneciton_id": "typo"},
            )

    def test_breaking_drift_does_not_mark_the_schedule_failed(
        self, db, project, connection, monkeypatch
    ) -> None:
        """A sweep that found a problem did its job.

        Marking it failed would put the schedule into retry and re-file the
        same incident every few minutes.
        """
        from service_schedules.execution import execute_schedule_operation
        from service_schedules.models import ScheduledOperation

        _Source({"id": "integer", "region": "text"}).install(monkeypatch)
        _sweep(db, project)
        _Source({"id": "integer"}).install(monkeypatch)

        row = ScheduledOperation(
            project_id=project.id,
            name="Nightly watch",
            schedule_type="connector_schema_watch",
            cron_expression="0 3 * * *",
            target_config_json={},
        )
        db.add(row)
        db.commit()

        outcome = execute_schedule_operation(
            db, row=row, current_user=None, storage_backend=None, settings=None
        )
        assert outcome.success
        assert "changed" in outcome.message
        assert find_active(db, project.id, fingerprint(connection.id, "public.orders")) is not None


class TestTenancy:
    """A project's connections are not readable by someone outside it.

    The gateway guard deliberately *returns* rather than raising when the caller
    has no role at all, so that "no access" reads as "not found" everywhere.
    That only holds if the service says so, and these routes are the ones that
    would otherwise list another project's sources.
    """

    def _routes(self, db):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient

        from shared_python.errors import register_exception_handlers

        from service_connectors.router import build_router

        holder: dict[str, Any] = {}

        def current_user():
            return holder["user"]

        app = FastAPI()
        # The same handlers the gateway installs, or a NotFoundError arrives as
        # a 500 and the test would be measuring the test app.
        register_exception_handlers(app)
        app.include_router(build_router(lambda: db, current_user), prefix="")
        return TestClient(app, raise_server_exceptions=False), holder

    def test_a_stranger_is_told_the_project_does_not_exist(
        self, db, project, connection
    ) -> None:
        from service_auth.schemas import UserRead

        client, holder = self._routes(db)
        stranger = User(
            id=uuid.uuid4(), username="outsider", password_hash="x",
            role="admin", is_active=True,
        )
        db.add(stranger)
        db.commit()
        holder["user"] = UserRead.model_validate(stranger, from_attributes=True)

        for method, path in (
            ("get", f"/projects/{project.id}/connectors/watch"),
            ("get", f"/projects/{project.id}/connectors/usage"),
        ):
            response = getattr(client, method)(path)
            assert response.status_code == 404, (method, path, response.text)

        response = client.post(
            f"/projects/{project.id}/connectors/watch", json={"apply": False}
        )
        assert response.status_code == 404, response.text

    def test_a_member_is_answered(self, db, project, connection) -> None:
        from service_auth.schemas import UserRead

        client, holder = self._routes(db)
        owner = db.get(User, project.owner_user_id)
        holder["user"] = UserRead.model_validate(owner, from_attributes=True)

        response = client.get(f"/projects/{project.id}/connectors/watch")
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
