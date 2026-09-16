"""Connector operations at two hundred connectors.

The schema watch exists because SaaS vendors change their APIs without telling
anybody, and the first sign is a pipeline failing at three in the morning with a
column that no longer exists. The health view exists because "which connectors
do we have" stops being a list somebody reads.
"""

from __future__ import annotations

import service_connectors  # noqa: F401  -- assembles the catalogue
from service_connectors import registry, watch
from service_connectors.health import overview


class TestWhatCanBeWatched:
    def test_manifests_that_declare_columns_are_watchable(self) -> None:
        watchable = watch.describable()
        assert len(watchable) > 20
        assert "klaviyo" in watchable
        assert "zendesk" in watchable

    def test_a_manifest_with_no_declared_schema_is_not(self) -> None:
        # Nothing to go stale, so nothing to watch. Said rather than assumed.
        assert "ga4" not in watch.describable()

    def test_a_connector_that_cannot_describe_itself_says_why(self) -> None:
        result = watch.check("ga4", previous=None)
        assert not result.checked
        assert "does not describe its columns" in result.skipped_reason

    def test_the_declared_schema_uses_the_renamed_columns(self) -> None:
        # `attributes.email` is where the value is; `email` is what a pipeline
        # refers to, so that is what drift compares.
        schema = watch.declared_schema("klaviyo")
        assert "email" in schema
        assert "attributes.email" not in schema


class TestDriftGrading:
    """The grades are Phase 02's, unchanged: a column disappearing means the
    same thing whether it left a CSV or left Klaviyo."""

    BASELINE = {"id": "string", "email": "string", "created_at": "datetime", "updated_at": "datetime"}

    def test_an_unchanged_schema_is_not_drift(self) -> None:
        result = watch.check("klaviyo", previous=self.BASELINE)
        assert not result.has_drift
        assert result.severity in ("none", "compatible")

    def test_a_removed_column_is_breaking(self) -> None:
        previous = {**self.BASELINE, "phone": "string"}
        result = watch.check("klaviyo", previous=previous)
        assert result.severity == "breaking"
        assert "phone" in result.removed_columns

    def test_a_new_column_alone_is_compatible(self) -> None:
        previous = {key: value for key, value in self.BASELINE.items() if key != "updated_at"}
        result = watch.check("klaviyo", previous=previous)
        assert result.severity == "compatible"
        assert "updated_at" in result.added_columns

    def test_a_type_change_is_reported_with_both_types(self) -> None:
        previous = {**self.BASELINE, "created_at": "string"}
        result = watch.check("klaviyo", previous=previous)
        assert result.type_changes
        change = next(c for c in result.type_changes if c["column"] == "created_at")
        assert change["previous_type"] == "string"
        assert change["current_type"] == "datetime"

    def test_a_first_look_is_not_drift(self) -> None:
        result = watch.check("klaviyo", previous=None)
        assert result.checked
        assert not result.has_drift
        assert "nothing to compare" in result.summary.lower()


class TestSweep:
    def test_it_checks_everything_watchable(self) -> None:
        report = watch.sweep()
        assert report.to_dict()["checked"] == len(watch.describable())
        assert report.to_dict()["skipped"] == 0

    def test_a_clean_sweep_reports_no_drift(self) -> None:
        # With no previous schemas, every result is a first look.
        assert watch.sweep().drifted == []

    def test_it_finds_the_one_that_moved(self) -> None:
        seen = {"klaviyo": {"id": "string", "email": "string", "gone": "string"}}
        report = watch.sweep(seen)
        drifted = report.drifted
        assert [result.connector_type for result in drifted] == ["klaviyo"]
        assert report.breaking

    def test_it_can_be_narrowed_to_named_connectors(self) -> None:
        report = watch.sweep(connector_types=["zendesk"])
        assert [result.connector_type for result in report.results] == ["zendesk"]

    def test_a_manifest_type_maps_onto_the_drift_vocabulary(self) -> None:
        # TIMESTAMP is `datetime` to the drift grader; if this mapping is
        # wrong every timestamp column reports a type change forever.
        schema = watch.declared_schema("zendesk", "tickets")
        assert schema["created_at"] == "datetime"
        assert schema["id"] == "int"


class TestHealthUsage:
    def test_usage_is_empty_without_configured_connections(self, tmp_path) -> None:
        import sqlalchemy as sa
        from sqlalchemy.orm import sessionmaker

        import api_gateway.metadata  # noqa: F401
        from shared_python.db import Base
        from service_connectors.health import usage

        engine = sa.create_engine("sqlite://")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine)()
        assert usage(db) == []
        db.close()
        engine.dispose()

    def test_usage_summarises_what_is_configured(self) -> None:
        import uuid

        import sqlalchemy as sa
        from sqlalchemy.orm import sessionmaker

        import api_gateway.metadata  # noqa: F401
        from service_auth.models import User
        from service_extraction.models import ExtractionConnection
        from service_projects.models import Project
        from shared_python.db import Base
        from service_connectors.health import usage

        engine = sa.create_engine("sqlite://")
        Base.metadata.create_all(engine)
        db = sessionmaker(bind=engine, expire_on_commit=False)()
        user = User(id=uuid.uuid4(), username="u", password_hash="x", role="admin", is_active=True)
        project = Project(id=uuid.uuid4(), name="P", slug="p", owner_user_id=user.id)
        db.add_all([user, project])
        db.add_all([
            ExtractionConnection(project_id=project.id, name="A", connector_type="postgresql",
                                 config_json={}, last_test_status="succeeded"),
            ExtractionConnection(project_id=project.id, name="B", connector_type="postgresql",
                                 config_json={}, last_test_status="failed"),
        ])
        db.commit()

        rows = usage(db, project.id)
        assert len(rows) == 1
        assert rows[0].connections == 2
        # The failing one is what somebody opened this view to find.
        assert rows[0].failing == 1
        assert rows[0].tier_label
        db.close()
        engine.dispose()

    def test_the_overview_needs_no_database(self) -> None:
        # It answers "what could this deployment reach", which is a property of
        # the catalogue rather than of anybody's data.
        report = overview()
        assert report.total == len(registry.known_types())
