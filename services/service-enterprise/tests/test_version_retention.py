"""A retention policy over superseded dataset versions.

Dataset versions do not go the way runs and metrics go (one DELETE past a
cutoff): the phase-18 §4 protocol marks them, waits out a lease, re-validates
and only then removes. These pin how that shows through the retention API --
report-only counts, a first pass that schedules, a later pass that prunes --
and that a destructive erasure treats a pruned version as already clean rather
than as an unreadable blocker.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  -- registers every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_datasets.version_lifecycle import PRUNE_GRACE, STATE_PENDING, STATE_PRUNED
from service_enterprise.models import RetentionPolicy
from service_enterprise.schemas import ErasureCreate, RetentionCreate
from service_enterprise.service import (
    create_retention,
    request_erasure,
    run_retention,
    sweep_dataset_version_retention,
)
from service_projects.models import Project
from shared_python.db import Base
from shared_python.storage import content_digest

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
CSV = b"name,email\nAlice,alice@acme.com\nBob,bob@acme.com\n"


class _Storage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def save_upload(self, *, relative_path: str, file_bytes: bytes):
        from shared_python.storage.interface import StoredArtifact

        self.files[relative_path] = file_bytes
        return StoredArtifact(relative_path=relative_path, file_name="f", size_bytes=len(file_bytes))

    def delete(self, path: str) -> None:
        del self.files[path]

    def exists(self, path: str) -> bool:
        return path in self.files


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


def _read(user: User) -> UserRead:
    return UserRead(id=user.id, username=user.username, role="admin", is_active=True,
                    created_at=NOW, updated_at=NOW)


@pytest.fixture()
def world(db: Session):
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    storage = _Storage()
    ds = Dataset(project_id=project.id, name="customers", status="ready",
                 ingestion_status="succeeded", file_path="d/v3.csv", file_type="csv")
    db.add(ds)
    db.flush()
    old = NOW - timedelta(days=400)
    for number in (1, 2, 3):
        path = f"d/v{number}.csv"
        storage.files[path] = CSV
        db.add(DatasetVersion(
            dataset_id=ds.id, version_number=number, file_path=path, file_type="csv",
            content_hash=content_digest(CSV), created_at=old,
            preview_json={"columns": ["email"], "rows": [{"email": "alice@acme.com"}]},
        ))
    db.commit()
    return {"owner": owner, "project": project, "storage": storage, "dataset": ds}


def _policy(db, world, *, dry_run: bool) -> RetentionPolicy:
    create_retention(
        db, world["project"].id,
        RetentionCreate(resource_type="dataset_versions", retain_days=30, dry_run=dry_run),
        _read(world["owner"]),
    )
    return db.scalar(select(RetentionPolicy))


def _versions(db, ds) -> dict[int, DatasetVersion]:
    db.expire_all()
    return {v.version_number: v for v in db.scalars(
        select(DatasetVersion).where(DatasetVersion.dataset_id == ds.id)).all()}


def test_dataset_versions_is_a_retainable_resource(db, world):
    policy = _policy(db, world, dry_run=True)
    assert policy.resource_type == "dataset_versions"


def test_a_report_only_policy_counts_superseded_versions_and_touches_nothing(db, world):
    _policy(db, world, dry_run=True)
    result = run_retention(db, world["project"].id, _read(world["owner"]), now=NOW,
                           storage=world["storage"])
    plan = result.plans[0]
    assert plan["matched"] == 2  # v1 and v2; v3 is the head
    assert plan["deleted"] == 0
    assert "report-only" in plan["summary"]
    assert plan["detail"]["would_schedule"] == 2
    assert all(v.retention_state == "active" for v in _versions(db, world["dataset"]).values())
    assert "Nothing was deleted" in result.summary


def test_a_live_policy_schedules_first_and_prunes_on_a_later_pass(db, world):
    _policy(db, world, dry_run=False)
    storage = world["storage"]

    first = run_retention(db, world["project"].id, _read(world["owner"]), now=NOW, storage=storage)
    assert first.plans[0]["detail"]["scheduled"] == 2
    assert first.plans[0]["deleted"] == 0
    assert "Scheduled 2" in first.summary
    versions = _versions(db, world["dataset"])
    assert versions[1].retention_state == STATE_PENDING
    assert versions[3].retention_state == "active"
    assert "d/v1.csv" in storage.files  # nothing removed yet

    # Too early: the lease has not ended.
    early = run_retention(db, world["project"].id, _read(world["owner"]),
                          now=NOW + timedelta(minutes=1), storage=storage)
    assert early.plans[0]["deleted"] == 0

    later = run_retention(db, world["project"].id, _read(world["owner"]),
                          now=NOW + PRUNE_GRACE, storage=storage)
    plan = later.plans[0]
    assert plan["deleted"] == 2
    assert "removed 2" in plan["summary"].lower()
    assert "Deleted 2" in later.summary
    versions = _versions(db, world["dataset"])
    assert versions[1].retention_state == STATE_PRUNED
    assert versions[2].retention_state == STATE_PRUNED
    assert versions[3].retention_state == "active"
    assert "d/v1.csv" not in storage.files and "d/v2.csv" not in storage.files
    assert storage.files["d/v3.csv"] == CSV
    policy = db.scalar(select(RetentionPolicy))
    assert policy.last_deleted_count == 2


def test_the_ticker_sweep_covers_live_policies_and_skips_report_only_ones(db, world):
    policy = _policy(db, world, dry_run=True)
    storage = world["storage"]
    assert sweep_dataset_version_retention(db, storage=storage, now=NOW)["projects"] == 0
    assert all(v.retention_state == "active" for v in _versions(db, world["dataset"]).values())

    policy.dry_run = False
    db.commit()
    totals = sweep_dataset_version_retention(db, storage=storage, now=NOW)
    assert totals == {"projects": 1, "scheduled": 2, "pruned": 0, "artifacts_removed": 0}
    totals = sweep_dataset_version_retention(db, storage=storage, now=NOW + PRUNE_GRACE)
    assert totals == {"projects": 1, "scheduled": 0, "pruned": 2, "artifacts_removed": 2}


def test_destructive_erasure_treats_a_pruned_version_as_already_clean(db, world):
    """A pruned version has no bytes and no preview left; there is nothing of
    the subject in it to redact. It must not be reported as an unreadable
    blocker -- that would make every erasure after any retention 'partial'."""
    _policy(db, world, dry_run=False)
    storage = world["storage"]
    owner = _read(world["owner"])
    run_retention(db, world["project"].id, owner, now=NOW, storage=storage)
    run_retention(db, world["project"].id, owner, now=NOW + PRUNE_GRACE, storage=storage)
    assert _versions(db, world["dataset"])[1].retention_state == STATE_PRUNED

    result = request_erasure(
        db, world["project"].id,
        ErasureCreate(subject_value="alice@acme.com", apply=True, mode="destructive"),
        owner, storage,
    )
    assert result.status == "completed"
    assert result.report["blocked"] == []
    assert b"alice@acme.com" not in storage.files["d/v3.csv"]
    versions = _versions(db, world["dataset"])
    assert versions[3].content_hash == content_digest(storage.files["d/v3.csv"])
    # The tombstones are untouched: still pruned, still no preview.
    assert versions[1].retention_state == STATE_PRUNED and versions[1].preview_json is None
