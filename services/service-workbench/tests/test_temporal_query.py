"""`AS OF` SQL over stored dataset versions (phase-18, settled decision #8).

Pins: a version is resolved by number or by instant with the stated tie and
before-first semantics; the query runs against THAT version's bytes, not the
head; the workbench's read-only policy applies (a write is refused, not run);
results are capped and say so; a pruned version answers with why; values come
back in the declared JSON representation.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_datasets.version_lifecycle import STATE_PRUNED
from service_projects.models import Project
from service_workbench.schemas import TemporalQueryRequest
from service_workbench.temporal import MAX_ROWS, TABLE_NAME, resolve_version, temporal_query
from shared_python.db import Base
from shared_python.errors import BadRequestError, ConflictError, NotFoundError

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
V1 = b"id,city,amount,seen\n1,Oslo,10.5,2026-01-01\n2,Rome,,2026-01-02\n"
V2 = b"id,city,amount,seen\n1,Oslo,10.5,2026-01-01\n2,Rome,20.25,2026-01-02\n3,Lima,30,\n"


class _Storage:
    def __init__(self) -> None:
        self.files = {"v1.csv": V1, "v2.csv": V2, "v3.csv": V2}

    def read_bytes(self, path: str) -> bytes:
        return self.files[path]


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
def world(db: Session) -> dict:
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    dataset = Dataset(project_id=project.id, name="cities", status="ready", file_type="csv",
                      file_path="v3.csv")
    db.add(dataset)
    db.flush()
    db.add_all([
        DatasetVersion(dataset_id=dataset.id, version_number=1, file_path="v1.csv", file_type="csv",
                       created_at=T0),
        DatasetVersion(dataset_id=dataset.id, version_number=2, file_path="v2.csv", file_type="csv",
                       created_at=T0 + timedelta(hours=1)),
        # Published in the same instant as v2: the tie resolves to the higher number.
        DatasetVersion(dataset_id=dataset.id, version_number=3, file_path="v3.csv", file_type="csv",
                       created_at=T0 + timedelta(hours=1)),
    ])
    db.commit()
    user = UserRead(id=owner.id, username="owner", role="admin", is_active=True,
                    created_at=T0, updated_at=T0)
    return {"project": project, "dataset": dataset, "user": user, "storage": _Storage()}


def _query(world, db, sql, **kw):
    return temporal_query(
        db, world["project"].id, world["dataset"].id,
        TemporalQueryRequest(sql=sql, **kw), world["user"], world["storage"],
    )


def test_a_query_runs_against_the_named_version_not_the_head(db, world):
    old = _query(world, db, f"SELECT COUNT(*) AS n FROM {TABLE_NAME}", version_number=1)
    head = _query(world, db, f"SELECT COUNT(*) AS n FROM {TABLE_NAME}")
    assert old.version_number == 1 and old.rows == [{"n": 2}]
    assert head.version_number == 3 and head.rows == [{"n": 3}]
    assert old.table_name == TABLE_NAME


def test_as_of_resolves_by_publication_time_with_the_stated_tie_rule(db, world):
    dataset = world["dataset"]
    assert resolve_version(db, dataset, version_number=None, as_of=T0).version_number == 1
    assert resolve_version(db, dataset, version_number=None,
                           as_of=T0 + timedelta(minutes=30)).version_number == 1
    # Same instant as v2 and v3: the higher number, which is the later publication.
    assert resolve_version(db, dataset, version_number=None,
                           as_of=T0 + timedelta(hours=1)).version_number == 3
    assert resolve_version(db, dataset, version_number=None,
                           as_of=T0 + timedelta(days=9)).version_number == 3


def test_an_instant_before_the_first_version_is_not_the_head(db, world):
    with pytest.raises(NotFoundError) as excinfo:
        _query(world, db, f"SELECT 1 FROM {TABLE_NAME}", as_of=T0 - timedelta(days=1))
    assert "No version of this dataset existed at" in str(excinfo.value.detail)
    assert "version 1, was published" in str(excinfo.value.detail)


def test_a_naive_as_of_is_taken_as_utc(db, world):
    result = _query(world, db, f"SELECT id FROM {TABLE_NAME} ORDER BY id",
                    as_of=datetime(2026, 9, 1, 12, 30))
    assert result.version_number == 1
    assert result.requested_as_of is not None


def test_real_sql_works_and_values_come_back_in_the_declared_shape(db, world):
    result = _query(
        world, db,
        f"SELECT city, amount, seen FROM {TABLE_NAME} WHERE amount IS NULL OR amount > 15 ORDER BY id",
        version_number=2,
    )
    assert result.columns == ["city", "amount", "seen"]
    assert [row["city"] for row in result.rows] == ["Rome", "Lima"]
    # Numbers are numbers, an empty date is null, a date is ISO text.
    assert result.rows[0]["amount"] == 20.25
    assert result.rows[1]["seen"] is None
    assert str(result.rows[0]["seen"]).startswith("2026-01-02")
    assert result.truncated is False and result.row_count == 2


def test_writes_are_refused_by_the_read_only_policy_not_run(db, world):
    with pytest.raises(BadRequestError) as excinfo:
        _query(world, db, f"DELETE FROM {TABLE_NAME}", version_number=2)
    assert "read-only snapshot" in str(excinfo.value.detail)
    assert "write mode" not in str(excinfo.value.detail)  # there is none to turn on
    # The stored bytes are what they were: the query engine is a throwaway copy
    # anyway, but the refusal must come from policy, before anything runs.
    assert world["storage"].files["v2.csv"] == V2


def test_one_statement_at_a_time(db, world):
    with pytest.raises(BadRequestError, match="one statement at a time"):
        _query(world, db, f"SELECT 1 FROM {TABLE_NAME}; SELECT 2 FROM {TABLE_NAME}")


def test_a_bad_query_reports_the_database_error(db, world):
    with pytest.raises(BadRequestError) as excinfo:
        _query(world, db, f"SELECT nope FROM {TABLE_NAME}")
    assert "nope" in str(excinfo.value.detail)


def test_results_are_capped_and_say_so(db, world):
    result = _query(world, db, f"SELECT id FROM {TABLE_NAME} ORDER BY id", version_number=2, row_limit=2)
    assert result.row_count == 2 and result.truncated is True and result.row_limit == 2
    assert MAX_ROWS == 1_000


def test_a_pruned_version_answers_with_the_reason(db, world):
    version = db.get(DatasetVersion, resolve_version(db, world["dataset"], version_number=1, as_of=None).id)
    version.retention_state = STATE_PRUNED
    version.pruned_at = T0 + timedelta(days=30)
    db.commit()
    with pytest.raises(ConflictError, match="pruned by retention"):
        _query(world, db, f"SELECT 1 FROM {TABLE_NAME}", version_number=1)


def test_a_missing_version_number_is_a_404(db, world):
    with pytest.raises(NotFoundError, match="no version 9"):
        _query(world, db, f"SELECT 1 FROM {TABLE_NAME}", version_number=9)
