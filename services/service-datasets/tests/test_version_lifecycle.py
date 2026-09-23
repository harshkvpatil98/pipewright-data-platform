"""The concurrent-GC protocol for dataset versions (Phase 18 §4).

Two races have to be closed, not made unlikely: a reader taking a version
after a sweep judged it unreferenced, and a sweep deleting a version a reader
still holds. These tests drive the protocol through its interleavings with
explicit sequencing -- pin before mark, pin after mark, pin after prune, a
crash between tombstone and blob deletion, a resumed sweep -- and pin the
answer each one must give.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion, DatasetVersionPin
from service_datasets.schemas import DatasetVersionDiffRequest
from service_datasets.service import (
    diff_dataset_versions,
    finalize_dataset_materialization_success,
    get_dataset_version_preview,
    list_dataset_versions,
    rollback_dataset_version,
)
from service_datasets.version_lifecycle import (
    PRUNE_GRACE,
    STATE_ACTIVE,
    STATE_PENDING,
    STATE_PRUNED,
    active_pin_count,
    eligible_versions,
    pin_version,
    prune_due,
    release_pins,
    schedule_prunes,
    sweep_project_versions,
)
from shared_python.db import Base
from shared_python.errors import ConflictError
from shared_python.storage import content_digest

NOW = datetime(2026, 9, 23, 12, 0, tzinfo=UTC)
OLD = NOW - timedelta(days=400)


class _Storage:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}
        self.fail_delete = False
        self.deleted: list[str] = []

    def read_bytes(self, path: str) -> bytes:
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]

    def save_upload(self, *, relative_path: str, file_bytes: bytes):
        from shared_python.storage.interface import StoredArtifact

        self.files[relative_path] = file_bytes
        return StoredArtifact(
            relative_path=relative_path,
            file_name=relative_path.rsplit("/", 1)[-1],
            size_bytes=len(file_bytes),
        )

    def delete(self, path: str) -> None:
        if self.fail_delete:
            raise OSError("disk unavailable")
        if path not in self.files:
            raise FileNotFoundError(path)
        self.deleted.append(path)
        del self.files[path]

    def exists(self, path: str) -> bool:
        return path in self.files


@pytest.fixture()
def engine(tmp_path):
    # A file-backed database, so a SECOND session can observe what the first
    # committed -- which is exactly the visibility the protocol depends on.
    eng = create_engine(f"sqlite:///{tmp_path / 'lifecycle.db'}")

    @event.listens_for(eng, "connect")
    def _fk(connection, _record):  # noqa: ANN001
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def db(engine) -> Iterator[Session]:
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def storage() -> _Storage:
    return _Storage()


@pytest.fixture()
def world(db: Session, storage: _Storage) -> dict:
    owner = User(username="owner", password_hash="x", role="admin", is_active=True)
    db.add(owner)
    db.flush()
    from service_projects.models import Project

    project = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(project)
    db.flush()
    dataset = Dataset(project_id=project.id, name="sales", status="registered", file_type="csv")
    db.add(dataset)
    db.commit()
    return {"owner": owner, "project": project, "dataset": dataset}


def _publish(db, storage, dataset, *, path, data: bytes, owner_id, created_at=None):
    storage.files[path] = data
    schema = {"columns": [{"name": "amount", "inferred_type": "int"}]}
    finalize_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path=path,
        file_name=path.rsplit("/", 1)[-1],
        schema_json=schema,
        schema_snapshot=schema,
        preview_json={"columns": ["amount"], "rows": [{"amount": 1}]},
        profile_json={"row_count": 1, "column_count": 1},
        row_count=1,
        column_count=1,
        content_hash=content_digest(data),
        created_by_user_id=owner_id,
    )
    version = db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset.id)
        .order_by(DatasetVersion.version_number.desc())
    )
    if created_at is not None:
        # Backdate: the retention clock is publication time.
        version.created_at = created_at
        db.commit()
    return version


def _three_versions(db, storage, world):
    ds = world["dataset"]
    uid = world["owner"].id
    v1 = _publish(db, storage, ds, path="a/v1.csv", data=b"amount\n1\n", owner_id=uid, created_at=OLD)
    v2 = _publish(db, storage, ds, path="a/v2.csv", data=b"amount\n2\n", owner_id=uid, created_at=OLD)
    v3 = _publish(db, storage, ds, path="a/v3.csv", data=b"amount\n3\n", owner_id=uid, created_at=OLD)
    return v1, v2, v3


def _user(world) -> UserRead:
    owner = world["owner"]
    return UserRead(
        id=owner.id, username=owner.username, role="admin", is_active=True,
        created_at=NOW, updated_at=NOW,
    )


def _state(db, version_id) -> DatasetVersion:
    db.expire_all()
    return db.get(DatasetVersion, version_id)


def _aware(value: datetime | None) -> datetime | None:
    # SQLite stores no offset; the protocol only ever writes UTC.
    if value is None or value.tzinfo is not None:
        return value
    return value.replace(tzinfo=UTC)


# ------------------------------------------------------------ eligibility


def test_the_head_and_pinned_versions_are_never_eligible(db, storage, world):
    v1, v2, v3 = _three_versions(db, storage, world)
    pin_version(db, v2, holder_kind="replay", holder_id=uuid.uuid4())
    db.commit()

    eligible = eligible_versions(db, project_id=world["project"].id, cutoff=NOW)
    # v3 is the head however old it is; v2 is held open; only v1 can go.
    assert [v.version_number for v in eligible] == [1]


def test_only_versions_older_than_the_cutoff_are_eligible(db, storage, world):
    v1, v2, v3 = _three_versions(db, storage, world)
    v2.created_at = NOW - timedelta(days=1)
    db.commit()
    eligible = eligible_versions(db, project_id=world["project"].id, cutoff=NOW - timedelta(days=30))
    assert [v.version_number for v in eligible] == [1]


# ----------------------------------------------------------- two-step prune


def test_a_sweep_marks_first_and_removes_only_after_the_lease(db, storage, world):
    v1, v2, v3 = _three_versions(db, storage, world)
    project_id = world["project"].id

    count, marked = schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    assert count == 2 and {v.version_number for v in marked} == {1, 2}
    assert _state(db, v1.id).retention_state == STATE_PENDING
    assert _aware(_state(db, v1.id).delete_after) == NOW + PRUNE_GRACE
    # Nothing has been removed: marking is not deleting.
    assert storage.files["a/v1.csv"] == b"amount\n1\n"

    # Before the lease ends a prune pass does nothing to them.
    early = prune_due(db, project_id=project_id, now=NOW + timedelta(minutes=5), storage=storage)
    assert early.pruned == 0
    assert "a/v1.csv" in storage.files

    # After the lease they are tombstoned and their bytes go.
    late = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    assert late.pruned == 2 and late.artifacts_removed == 2
    pruned = _state(db, v1.id)
    assert pruned.retention_state == STATE_PRUNED
    assert _aware(pruned.pruned_at) == NOW + PRUNE_GRACE
    assert pruned.artifact_removed_at is not None
    # The tombstone keeps the shape and the digest, not the values.
    assert pruned.preview_json is None
    assert pruned.content_hash == content_digest(b"amount\n1\n")
    assert pruned.row_count == 1
    assert "a/v1.csv" not in storage.files
    # The head is untouched.
    assert _state(db, v3.id).retention_state == STATE_ACTIVE
    assert storage.files["a/v3.csv"] == b"amount\n3\n"


def test_a_dry_run_counts_and_marks_nothing(db, storage, world):
    v1, _v2, _v3 = _three_versions(db, storage, world)
    report = sweep_project_versions(
        db, project_id=world["project"].id, cutoff=NOW, now=NOW, dry_run=True, storage=storage
    )
    assert report.would_schedule == 2
    assert report.scheduled == 0 and report.pruned == 0
    assert _state(db, v1.id).retention_state == STATE_ACTIVE


def test_one_sweep_call_cannot_mark_and_remove_the_same_version(db, storage, world):
    # schedule-then-prune inside one pass: a freshly marked version is never
    # due in the pass that marked it, whatever `now` is.
    v1, _v2, _v3 = _three_versions(db, storage, world)
    report = sweep_project_versions(
        db, project_id=world["project"].id, cutoff=NOW, now=NOW, dry_run=False, storage=storage
    )
    assert report.scheduled == 2 and report.pruned == 0
    assert _state(db, v1.id).retention_state == STATE_PENDING


# ------------------------------------------------------------- interleavings


def test_a_pin_committed_after_the_mark_rescues_the_version(db, storage, world):
    """Race one: the sweep decided v1 is unreferenced; a replay pins it before
    the lease ends. The pin wins: v1 goes back to active and the prune pass
    re-validation stands down."""
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    assert _state(db, v1.id).retention_state == STATE_PENDING

    pin_version(db, v1, holder_kind="replay", holder_id=uuid.uuid4())
    db.commit()
    assert _state(db, v1.id).retention_state == STATE_ACTIVE
    assert _state(db, v1.id).delete_after is None

    report = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    assert report.pruned == 1  # v2, which nobody pinned
    assert _state(db, v1.id).retention_state == STATE_ACTIVE
    assert "a/v1.csv" in storage.files


def test_a_pin_that_lands_during_the_lease_is_seen_at_revalidation(db, storage, world):
    """Same race, other ordering inside the lease: the pin arrives after the
    mark but the sweep's prune pass only re-validates later. The row-level
    re-check must see the committed pin even when the state column was not
    rescued (a pin written by an older client, say)."""
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    # A raw pin row -- no rescue, state still pending.
    db.add(DatasetVersionPin(dataset_version_id=v1.id, holder_kind="run", holder_id=uuid.uuid4()))
    db.commit()

    report = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    assert report.rescued == 1 and report.pruned == 1
    assert _state(db, v1.id).retention_state == STATE_ACTIVE


def test_a_pin_after_the_prune_is_refused_with_the_reason(db, storage, world):
    """Race two, resolved the only honest way: once the tombstone is committed
    the data is gone, so a late reader is told so rather than handed a
    version that will fail on the first byte."""
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)

    with pytest.raises(ConflictError) as excinfo:
        pin_version(db, v1, holder_kind="replay", holder_id=uuid.uuid4())
    assert "pruned by retention" in str(excinfo.value.detail)


def test_a_pin_is_visible_to_a_second_session_before_any_bytes_are_read(engine, db, storage, world):
    """The pin visibility question, resolved: the pin is committed first, and
    a sweep running in ANOTHER session sees it. An uncommitted pin would not
    be, which is why every caller commits between pinning and reading."""
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id

    pin_version(db, v1, holder_kind="replay", holder_id=uuid.uuid4())
    db.commit()

    other = sessionmaker(bind=engine)()
    try:
        assert active_pin_count(other, v1.id) == 1
        eligible = eligible_versions(other, project_id=project_id, cutoff=NOW)
        assert [v.version_number for v in eligible] == [2]
    finally:
        other.close()


# --------------------------------------------------------- crash and resume


def test_a_crash_between_tombstone_and_blob_delete_is_resumed(db, storage, world):
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()

    storage.fail_delete = True
    first = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    assert first.pruned == 2
    assert first.artifacts_removed == 0 and first.artifacts_pending == 2
    # The tombstone is durable; the bytes are still there; the row says so.
    assert _state(db, v1.id).retention_state == STATE_PRUNED
    assert _state(db, v1.id).artifact_removed_at is None
    assert "a/v1.csv" in storage.files

    storage.fail_delete = False
    resumed = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE + timedelta(hours=1), storage=storage)
    assert resumed.pruned == 0 and resumed.artifacts_removed == 2
    assert _state(db, v1.id).artifact_removed_at is not None
    assert "a/v1.csv" not in storage.files

    # Idempotent: a third pass has nothing to do.
    again = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE + timedelta(hours=2), storage=storage)
    assert again.pruned == 0 and again.artifacts_removed == 0 and again.artifacts_pending == 0


def test_a_sweep_without_storage_tombstones_and_leaves_bytes_for_the_next_pass(db, storage, world):
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    report = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=None)
    assert report.pruned == 2 and report.artifacts_pending == 2
    assert "a/v1.csv" in storage.files
    later = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    assert later.artifacts_removed == 2


def test_shared_bytes_are_not_deleted_from_under_another_reference(db, storage, world):
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    # Another dataset's head points at the same artifact as v1.
    twin = Dataset(project_id=project_id, name="twin", status="ready", file_type="csv", file_path="a/v1.csv")
    db.add(twin)
    db.commit()
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    report = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    assert report.pruned == 2
    assert "a/v1.csv" in storage.files  # the twin still needs it
    assert "a/v2.csv" not in storage.files
    assert _state(db, v1.id).artifact_removed_at is not None  # nothing left for us to do


# -------------------------------------------------------- reads of a tombstone


def _pruned_world(db, storage, world):
    v1, v2, v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    return v1, v2, v3


def test_history_still_lists_a_pruned_version_and_says_so(db, storage, world):
    _pruned_world(db, storage, world)
    listing = list_dataset_versions(db, world["project"].id, world["dataset"].id, _user(world))
    assert [item.version_number for item in listing.items] == [3, 2, 1]
    states = {item.version_number: item.retention_state for item in listing.items}
    assert states == {3: STATE_ACTIVE, 2: STATE_PRUNED, 1: STATE_PRUNED}
    assert listing.items[-1].pruned_at is not None


def test_reading_a_pruned_version_is_refused_with_the_reason(db, storage, world):
    _pruned_world(db, storage, world)
    project_id, dataset_id, user = world["project"].id, world["dataset"].id, _user(world)

    with pytest.raises(ConflictError, match="pruned by retention"):
        get_dataset_version_preview(db, project_id, dataset_id, 1, user)
    with pytest.raises(ConflictError, match="pruned by retention"):
        diff_dataset_versions(
            db, project_id, dataset_id,
            DatasetVersionDiffRequest(from_version=1, to_version=3), user, storage,
        )
    with pytest.raises(ConflictError, match="pruned by retention"):
        rollback_dataset_version(db, project_id, dataset_id, 1, user, storage)
    # And history is exactly as it was: nothing appended by the refusals.
    assert [v.version_number for v in db.scalars(select(DatasetVersion)).all()] == [1, 2, 3]


# ------------------------------------------------------------ rollback pins


def test_rollback_pins_its_target_while_copying_and_releases_it_after(db, storage, world):
    v1, _v2, _v3 = _three_versions(db, storage, world)
    user = _user(world)
    restored = rollback_dataset_version(
        db, world["project"].id, world["dataset"].id, 1, user, storage
    )
    assert restored.version_number == 4
    assert restored.content_hash == content_digest(b"amount\n1\n")
    pins = db.scalars(select(DatasetVersionPin).where(DatasetVersionPin.dataset_version_id == v1.id)).all()
    assert len(pins) == 1
    assert pins[0].holder_kind == "rollback"
    assert pins[0].released_at is not None  # held only for the copy
    assert active_pin_count(db, v1.id) == 0


def test_rollback_rescues_a_version_scheduled_for_removal(db, storage, world):
    v1, _v2, _v3 = _three_versions(db, storage, world)
    project_id = world["project"].id
    schedule_prunes(db, project_id=project_id, cutoff=NOW, now=NOW)
    db.commit()
    assert _state(db, v1.id).retention_state == STATE_PENDING

    rollback_dataset_version(db, project_id, world["dataset"].id, 1, _user(world), storage)
    assert _state(db, v1.id).retention_state == STATE_ACTIVE
    # A later prune pass leaves it alone: it was rescued, then released, and is
    # simply an active superseded version again until a future policy pass.
    report = prune_due(db, project_id=project_id, now=NOW + PRUNE_GRACE, storage=storage)
    assert _state(db, v1.id).retention_state == STATE_ACTIVE
    assert report.pruned == 1  # v2


def test_release_closes_only_the_holders_own_pins(db, storage, world):
    v1, v2, _v3 = _three_versions(db, storage, world)
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    pin_version(db, v1, holder_kind="replay", holder_id=mine)
    pin_version(db, v2, holder_kind="replay", holder_id=theirs)
    db.commit()
    assert release_pins(db, holder_kind="replay", holder_id=mine) == 1
    db.commit()
    assert active_pin_count(db, v1.id) == 0
    assert active_pin_count(db, v2.id) == 1
