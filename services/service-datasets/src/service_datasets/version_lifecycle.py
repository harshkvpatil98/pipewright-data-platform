"""Pins and pruning: the concurrent garbage-collection protocol for versions.

Phase 18 §4 names two races a "grace period plus a reference scan" leaves open:

* a reader (rollback, replay) starts using a version after the sweep decided
  it was unreferenced and before the sweep deleted it;
* a sweep deletes a version while a reader is still using it.

Both are closed by the same two rules, enforced here and nowhere else:

1. **A pin is durable before any bytes are read.** `pin_version` writes a
   `DatasetVersionPin` row under a row lock on the version, the caller COMMITS,
   and only then reads. A pin that is still uncommitted is invisible to a sweep
   in another session, so relying on it would be the bug -- every caller in this
   package commits between pinning and reading.
2. **Deletion is two durable steps with re-validation in between.** A sweep
   first MARKS eligible versions `pending_delete` with a lease (`delete_after`).
   On a later pass, for each version whose lease has expired, it takes the row
   lock, re-checks that the version is still pending, still not the head and
   still unpinned, and only then tombstones it (`pruned`). The bytes are removed
   after that commit; a crash in between leaves `artifact_removed_at` null and
   the next pass finishes the job. Every step is idempotent.

Under the row lock the two sides serialise: a pin that commits before the
sweep's re-validation rescues the version (state goes back to `active`); a pin
attempted after the sweep committed `pruned` is refused with the reason. On
PostgreSQL the lock is `SELECT ... FOR UPDATE`; on SQLite (tests, single-file
deployments) the database serialises writers itself and the `FOR UPDATE` is a
no-op, which gives the same ordering guarantee.

Storage keys, reference counts and hash-existence probes never leave this
module for an API payload (§4).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_datasets.models import Dataset, DatasetVersion, DatasetVersionPin
from shared_python.errors import ConflictError
from shared_python.logging import get_logger

logger = get_logger(__name__)

STATE_ACTIVE = "active"
STATE_PENDING = "pending_delete"
STATE_PRUNED = "pruned"

#: How long a marked version waits before it can actually be removed. Long
#: enough that any request that started reading it before the mark has finished
#: (a request is bounded to seconds, not minutes); short enough that a policy
#: visibly does something the same day.
PRUNE_GRACE = timedelta(minutes=30)


# ------------------------------------------------------------------- pins


def _locked_version(db: Session, version_id: uuid.UUID) -> DatasetVersion:
    return db.execute(
        select(DatasetVersion).where(DatasetVersion.id == version_id).with_for_update()
    ).scalar_one()


def unavailable_reason(version: DatasetVersion) -> str | None:
    """Why this version's data cannot be read, or None when it can."""
    if version.retention_state == STATE_PRUNED:
        when = version.pruned_at.date().isoformat() if version.pruned_at else "an earlier sweep"
        return (
            f"Version {version.version_number} was pruned by retention on {when}; its data "
            "is no longer stored. Its metadata remains as a record that it existed."
        )
    return None


def require_readable(version: DatasetVersion) -> None:
    reason = unavailable_reason(version)
    if reason is not None:
        raise ConflictError(reason)


def pin_version(
    db: Session,
    version: DatasetVersion,
    *,
    holder_kind: str,
    holder_id: uuid.UUID | None,
    reason: str | None = None,
) -> DatasetVersionPin:
    """Hold a version open. FLUSHES; the caller must COMMIT before reading bytes.

    Refuses a pruned version (its data is gone) and rescues a `pending_delete`
    one: the sweep has not deleted anything yet, and under the row lock the
    sweep's later re-validation will see the pin and stand down.
    """
    locked = _locked_version(db, version.id)
    if locked.retention_state == STATE_PRUNED:
        raise ConflictError(unavailable_reason(locked) or "This version has been pruned.")
    if locked.retention_state == STATE_PENDING:
        locked.retention_state = STATE_ACTIVE
        locked.delete_after = None
    pin = DatasetVersionPin(
        dataset_version_id=locked.id,
        holder_kind=holder_kind,
        holder_id=holder_id,
        reason=reason,
    )
    db.add(pin)
    db.flush()
    # Keep the caller's instance in step with what was locked and possibly
    # rescued, so a stale `pending_delete` is not read back after the pin.
    if version is not locked:
        db.refresh(version)
    return pin


def release_pins(db: Session, *, holder_kind: str, holder_id: uuid.UUID | None) -> int:
    """Close every open pin this holder took. FLUSHES; the caller commits."""
    now = datetime.now(UTC)
    open_pins = db.scalars(
        select(DatasetVersionPin).where(
            DatasetVersionPin.holder_kind == holder_kind,
            DatasetVersionPin.holder_id == holder_id,
            DatasetVersionPin.released_at.is_(None),
        )
    ).all()
    for pin in open_pins:
        pin.released_at = now
    db.flush()
    return len(open_pins)


def active_pin_count(db: Session, version_id: uuid.UUID) -> int:
    return int(
        db.scalar(
            select(func.count(DatasetVersionPin.id)).where(
                DatasetVersionPin.dataset_version_id == version_id,
                DatasetVersionPin.released_at.is_(None),
            )
        )
        or 0
    )


def active_pin_counts(db: Session, version_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not version_ids:
        return {}
    rows = db.execute(
        select(DatasetVersionPin.dataset_version_id, func.count(DatasetVersionPin.id))
        .where(
            DatasetVersionPin.dataset_version_id.in_(version_ids),
            DatasetVersionPin.released_at.is_(None),
        )
        .group_by(DatasetVersionPin.dataset_version_id)
    ).all()
    return {version_id: int(count) for version_id, count in rows}


# ---------------------------------------------------------------- pruning


@dataclass
class PruneReport:
    """What one sweep pass did, in numbers a policy page can show."""

    #: Superseded, unpinned versions past the cutoff that were marked this pass.
    scheduled: int = 0
    #: Versions whose lease had expired and that were tombstoned this pass.
    pruned: int = 0
    #: Marked versions that re-validation sent back to `active` (pinned or head
    #: again by the time the lease expired).
    rescued: int = 0
    #: Artifacts whose bytes were removed this pass (including resumed ones).
    artifacts_removed: int = 0
    #: Pruned versions whose bytes could not be removed yet; retried next pass.
    artifacts_pending: int = 0
    #: Eligible-but-not-marked count for a dry run.
    would_schedule: int = 0
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "scheduled": self.scheduled,
            "pruned": self.pruned,
            "rescued": self.rescued,
            "artifacts_removed": self.artifacts_removed,
            "artifacts_pending": self.artifacts_pending,
            "would_schedule": self.would_schedule,
            "notes": list(self.notes),
        }


def _head_numbers(db: Session, dataset_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not dataset_ids:
        return {}
    rows = db.execute(
        select(DatasetVersion.dataset_id, func.max(DatasetVersion.version_number))
        .where(DatasetVersion.dataset_id.in_(dataset_ids))
        .group_by(DatasetVersion.dataset_id)
    ).all()
    return {dataset_id: int(number) for dataset_id, number in rows}


def eligible_versions(
    db: Session, *, project_id: uuid.UUID, cutoff: datetime
) -> list[DatasetVersion]:
    """Superseded, active, unpinned versions published before the cutoff.

    Never the head: the current data is not "old" however long ago it was
    published. Never a pinned one: somebody is using it.
    """
    candidates = list(
        db.scalars(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(
                Dataset.project_id == project_id,
                DatasetVersion.retention_state == STATE_ACTIVE,
                DatasetVersion.created_at < cutoff,
            )
            .order_by(DatasetVersion.created_at)
        ).all()
    )
    if not candidates:
        return []
    heads = _head_numbers(db, list({version.dataset_id for version in candidates}))
    pins = active_pin_counts(db, [version.id for version in candidates])
    return [
        version
        for version in candidates
        if heads.get(version.dataset_id) != version.version_number
        and pins.get(version.id, 0) == 0
    ]


def schedule_prunes(
    db: Session,
    *,
    project_id: uuid.UUID,
    cutoff: datetime,
    now: datetime | None = None,
    dry_run: bool = False,
    grace: timedelta = PRUNE_GRACE,
) -> tuple[int, list[DatasetVersion]]:
    """Step one: mark eligible versions `pending_delete` with a lease.

    Nothing is removed here. FLUSHES; the caller commits. A dry run only counts.
    """
    moment = now or datetime.now(UTC)
    eligible = eligible_versions(db, project_id=project_id, cutoff=cutoff)
    if dry_run:
        return len(eligible), []
    for version in eligible:
        version.retention_state = STATE_PENDING
        version.delete_after = moment + grace
    db.flush()
    return len(eligible), eligible


def _path_still_referenced(db: Session, path: str, *, except_version_id: uuid.UUID) -> bool:
    """Do the bytes at this path back anything else -- a head, or another version
    that has not been pruned? Then removing them would corrupt that other thing."""
    head = db.scalar(select(Dataset.id).where(Dataset.file_path == path).limit(1))
    if head is not None:
        return True
    other = db.scalar(
        select(DatasetVersion.id)
        .where(
            DatasetVersion.file_path == path,
            DatasetVersion.id != except_version_id,
            DatasetVersion.retention_state != STATE_PRUNED,
        )
        .limit(1)
    )
    return other is not None


def prune_due(
    db: Session,
    *,
    project_id: uuid.UUID,
    now: datetime | None = None,
    storage: Any | None = None,
) -> PruneReport:
    """Step two: tombstone every marked version whose lease has expired, then
    remove its bytes. Each version is its own committed step, so a crash loses
    at most the work of one and a re-run picks up exactly where it stopped.
    """
    moment = now or datetime.now(UTC)
    report = PruneReport()

    due_ids = list(
        db.scalars(
            select(DatasetVersion.id)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(
                Dataset.project_id == project_id,
                DatasetVersion.retention_state == STATE_PENDING,
                DatasetVersion.delete_after.is_not(None),
                DatasetVersion.delete_after <= moment,
            )
        ).all()
    )
    for version_id in due_ids:
        # Re-validate under the row lock: the world may have moved since the
        # mark. Whatever is decided here is decided against committed state.
        locked = _locked_version(db, version_id)
        if locked.retention_state != STATE_PENDING:
            continue  # rescued by a pin, or already handled
        head = _head_numbers(db, [locked.dataset_id]).get(locked.dataset_id)
        if head == locked.version_number or active_pin_count(db, locked.id) > 0:
            locked.retention_state = STATE_ACTIVE
            locked.delete_after = None
            report.rescued += 1
            db.commit()
            continue
        locked.retention_state = STATE_PRUNED
        locked.pruned_at = moment
        locked.delete_after = None
        # The preview is sample rows of the data being removed; a tombstone
        # keeps the shape (schema, counts, digest), not the values.
        locked.preview_json = None
        report.pruned += 1
        db.commit()

    # Blob removal -- for this pass's prunes AND any earlier pass that crashed
    # between the tombstone and the delete.
    orphans = list(
        db.scalars(
            select(DatasetVersion)
            .join(Dataset, Dataset.id == DatasetVersion.dataset_id)
            .where(
                Dataset.project_id == project_id,
                DatasetVersion.retention_state == STATE_PRUNED,
                DatasetVersion.artifact_removed_at.is_(None),
            )
        ).all()
    )
    for version in orphans:
        if storage is None:
            report.artifacts_pending += 1
            continue
        if _path_still_referenced(db, version.file_path, except_version_id=version.id):
            # Shared bytes: nothing to delete for this version; the reference
            # that remains owns them now.
            version.artifact_removed_at = moment
            db.commit()
            continue
        try:
            storage.delete(version.file_path)
        except FileNotFoundError:
            pass  # already gone -- a resumed sweep after a crash mid-delete
        except Exception:  # noqa: BLE001 - leave it for the next pass, and say so
            logger.warning(
                "dataset_version_artifact_not_removed version_id=%s", version.id
            )
            report.artifacts_pending += 1
            continue
        version.artifact_removed_at = moment
        report.artifacts_removed += 1
        db.commit()

    if report.artifacts_pending:
        report.notes.append(
            f"{report.artifacts_pending} pruned version(s) still have bytes to remove; "
            "the next sweep retries."
        )
    return report


def sweep_project_versions(
    db: Session,
    *,
    project_id: uuid.UUID,
    cutoff: datetime,
    now: datetime | None = None,
    dry_run: bool,
    storage: Any | None,
) -> PruneReport:
    """One policy pass: schedule what is newly eligible, then prune what is due.

    Ordered prune-then-schedule would let a version be marked and removed in
    one call with no lease at all; schedule-then-prune means the earliest a
    freshly marked version can go is the *next* pass after its grace period.
    """
    moment = now or datetime.now(UTC)
    count, _marked = schedule_prunes(
        db, project_id=project_id, cutoff=cutoff, now=moment, dry_run=dry_run
    )
    if dry_run:
        report = PruneReport(would_schedule=count)
        report.notes.append(
            f"{count} superseded version(s) would be scheduled for removal after a "
            f"{int(PRUNE_GRACE.total_seconds() // 60)}-minute grace period."
        )
        return report
    db.commit()
    report = prune_due(db, project_id=project_id, now=moment, storage=storage)
    report.scheduled = count
    if count:
        report.notes.append(
            f"{count} superseded version(s) scheduled; they are removed on a later sweep "
            f"once their {int(PRUNE_GRACE.total_seconds() // 60)}-minute grace period ends."
        )
    return report
