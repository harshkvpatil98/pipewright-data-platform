"""Storing a confirmed spec so next month's file reads the same way.

The roadmap's fifth criterion. The reason it matters is not convenience: it is
that **inference depends on the data**. A date column that read as day-first in
January because one row said `15/01` is genuinely ambiguous in February when no
row does, so the same recurring report would be imported two different ways by
a system that re-infers. A recorded decision does not drift.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401  -- resolves every mapper
from service_auth.models import User
from service_auth.schemas import UserRead
from service_ingestion import analysis_service
from service_ingestion.models import IngestSpecRecord, column_fingerprint, name_pattern
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError, NotFoundError


@pytest.fixture()
def db():
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
def current_user(db, project):
    user = db.get(User, project.owner_user_id)
    return UserRead.model_validate(user, from_attributes=True)


JANUARY = b"id,when,amount\n1,15/01/2026,1.234,56\n"
FEBRUARY = b"id,when,amount\n2,07/02/2026,89,10\n"


class TestFingerprinting:
    def test_the_same_columns_fingerprint_the_same(self) -> None:
        assert column_fingerprint(["id", "name"]) == column_fingerprint(["name", "id"])

    def test_a_rename_that_nobody_meant_is_still_the_same_report(self) -> None:
        """`Order ID` becoming `order_id` is a spelling change, not a new file."""
        assert column_fingerprint(["Order ID"]) == column_fingerprint(["order_id"])

    def test_different_columns_fingerprint_differently(self) -> None:
        assert column_fingerprint(["id"]) != column_fingerprint(["id", "extra"])

    def test_the_month_is_masked_out_of_a_file_name(self) -> None:
        assert name_pattern("sales-2026-01.csv") == name_pattern("sales-2026-02.csv")

    def test_different_reports_do_not_share_a_pattern(self) -> None:
        assert name_pattern("sales-2026-01.csv") != name_pattern("returns-2026-01.csv")


class TestRemembering:
    def _analyse(self, db, project, current_user, payload, name="sales-2026-01.csv"):
        return analysis_service.analyse_upload(
            db,
            project_id=project.id,
            file_name=name,
            content_type="text/csv",
            payload=payload,
            current_user=current_user,
        )

    def test_analysing_stores_nothing(self, db, project, current_user) -> None:
        self._analyse(db, project, current_user, JANUARY)
        assert db.scalars(sa.select(IngestSpecRecord)).all() == []

    def test_a_confirmed_spec_is_saved_and_found_again(
        self, db, project, current_user
    ) -> None:
        analysed = self._analyse(db, project, current_user, JANUARY)
        record = analysis_service.remember(
            db,
            project_id=project.id,
            label="Monthly sales",
            file_name="sales-2026-01.csv",
            payload_spec=analysed["spec"],
            columns=analysed["preview"]["columns"],
            current_user=current_user,
        )
        db.commit()

        found = analysis_service.find_match(
            db,
            project_id=project.id,
            file_name="sales-2026-02.csv",
            columns=analysed["preview"]["columns"],
        )
        assert found is not None and found.id == record.id

    def test_next_months_file_is_offered_the_saved_spec(
        self, db, project, current_user
    ) -> None:
        analysed = self._analyse(db, project, current_user, JANUARY)
        analysis_service.remember(
            db,
            project_id=project.id,
            label="Monthly sales",
            file_name="sales-2026-01.csv",
            payload_spec=analysed["spec"],
            columns=analysed["preview"]["columns"],
            current_user=current_user,
        )
        db.commit()

        next_month = self._analyse(
            db, project, current_user, FEBRUARY, name="sales-2026-02.csv"
        )
        assert next_month["matched_spec"] is not None
        assert next_month["matched_spec"]["label"] == "Monthly sales"

    def test_confirming_the_same_file_twice_updates_rather_than_duplicates(
        self, db, project, current_user
    ) -> None:
        """Two specs for one file means the next upload picks one arbitrarily."""
        analysed = self._analyse(db, project, current_user, JANUARY)
        for label in ("First go", "Second go"):
            analysis_service.remember(
                db,
                project_id=project.id,
                label=label,
                file_name="sales-2026-01.csv",
                payload_spec=analysed["spec"],
                columns=analysed["preview"]["columns"],
                current_user=current_user,
            )
        db.commit()
        rows = db.scalars(sa.select(IngestSpecRecord)).all()
        assert len(rows) == 1
        assert rows[0].label == "Second go"

    def test_a_spec_that_cannot_be_applied_is_refused_before_it_is_saved(
        self, db, project, current_user
    ) -> None:
        """A date column with no format would raise at import time instead."""
        with pytest.raises(BadRequestError, match="no format is set"):
            analysis_service.remember(
                db,
                project_id=project.id,
                label="Broken",
                file_name="x.csv",
                payload_spec={
                    "version": 1,
                    "format": "csv",
                    "columns": [{"name": "when", "type": "date"}],
                },
                columns=["when"],
                current_user=current_user,
            )

    def test_two_columns_cannot_be_renamed_to_the_same_thing(
        self, db, project, current_user
    ) -> None:
        with pytest.raises(BadRequestError, match="both be called"):
            analysis_service.remember(
                db,
                project_id=project.id,
                label="Clashing",
                file_name="x.csv",
                payload_spec={
                    "version": 1,
                    "format": "csv",
                    "columns": [
                        {"name": "a", "type": "string", "rename": "total"},
                        {"name": "b", "type": "string", "rename": "total"},
                    ],
                },
                columns=["a", "b"],
                current_user=current_user,
            )


class TestIsolation:
    def test_another_project_cannot_read_this_one_s_specs(
        self, db, project, current_user
    ) -> None:
        elsewhere = Project(
            id=uuid.uuid4(), name="Q", slug="q", owner_user_id=uuid.uuid4()
        )
        db.add(elsewhere)
        db.commit()
        with pytest.raises(NotFoundError):
            analysis_service.list_specs(
                db, project_id=elsewhere.id, current_user=current_user
            )

    def test_a_spec_from_another_project_is_not_found(self, db, project, current_user) -> None:
        other = IngestSpecRecord(
            project_id=uuid.uuid4(),
            label="Theirs",
            name_pattern="x.csv",
            column_fingerprint="abc",
            file_format="csv",
            spec_json={},
        )
        db.add(other)
        db.commit()
        with pytest.raises(NotFoundError):
            analysis_service._get(db, project.id, other.id)


class TestVersioning:
    def test_a_spec_from_a_newer_platform_is_refused_rather_than_misread(self) -> None:
        """A stored decision that cannot be replayed is not a stored decision."""
        from service_ingestion import spec as spec_module

        with pytest.raises(BadRequestError, match="newer version"):
            spec_module.IngestSpec.from_dict({"version": 99, "format": "csv"})

    def test_a_spec_records_the_version_that_wrote_it(self) -> None:
        from service_ingestion import spec as spec_module

        written = spec_module.IngestSpec(format="csv").to_dict()
        assert written["version"] == spec_module.SPEC_VERSION
