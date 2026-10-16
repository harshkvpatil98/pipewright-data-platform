from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.audit import build_dataset_audit_summary
from service_datasets.models import Dataset, DatasetVersion
from service_datasets.schemas import (
    DatasetAuditSummary,
    DatasetCreate,
    DatasetDetailRead,
    DatasetListResponse,
    DatasetPreviewResponse,
    DatasetProfileResponse,
    DatasetSummaryRead,
    DatasetUpdate,
    DatasetVersionDiff,
    DatasetVersionDiffRequest,
    DatasetVersionListResponse,
    DatasetVersionRead,
)
from service_datasets.version_lifecycle import (
    active_pin_count,
    active_pin_counts,
    pin_version,
    release_pins,
    require_readable,
)
from service_datasets.versions_diff import diff_frames
from service_projects.contracts import ensure_owned_project
from service_sources.contracts import get_source_for_project
from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger

logger = get_logger(__name__)


def _to_summary(dataset: Dataset) -> DatasetSummaryRead:
    return DatasetSummaryRead.model_validate(dataset)


def _to_detail(dataset: Dataset) -> DatasetDetailRead:
    return DatasetDetailRead.model_validate(dataset)


def statistics_of(profile_json: dict[str, Any] | None) -> dict[str, Any] | None:
    """A version's statistics, from the profile written with it (D2)."""
    from shared_python.statistics import from_profile

    stats = from_profile(profile_json, collected_at=datetime.now(UTC))
    return stats.to_json() if stats is not None else None


def stored_file_identity(db: Session, dataset_id: uuid.UUID, file_path: str | None) -> str | None:
    """What a stored file holds, for addressing what was made from it (D2): the
    content hash recorded with its version, which an erasure rewrites with the
    file. None when there is none to go by."""
    if not file_path:
        return None
    found = db.scalar(
        select(DatasetVersion.content_hash)
        .where(DatasetVersion.dataset_id == dataset_id, DatasetVersion.file_path == file_path)
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    )
    return f"{dataset_id}:{file_path}:{found}" if found else None


def version_statistics(db: Session, dataset: Dataset, version: DatasetVersion | None = None):
    """What is known about a dataset's values: of `version`, or of the current one.

    A version written before statistics were kept has none, unless it is the
    latest, whose figures are the dataset's own profile.
    """
    from shared_python.statistics import TableStats, from_profile

    if version is not None and version.statistics_json:
        return TableStats.from_json(version.statistics_json)
    if version is None or version.version_number == _next_version_number(db, dataset.id) - 1:
        return from_profile(dataset.profile_json)
    return None


def _policy_view(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead):
    """The row and column policies that apply to this person on this dataset (A6, W1).

    Function-level import: service_enterprise imports this service's models.
    """
    from service_enterprise.policy_view import Reader, view_for

    return view_for(db, project_id, dataset_id, Reader.for_user(db, project_id, current_user))


def list_datasets_by_project(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> DatasetListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    datasets = db.scalars(
        select(Dataset).where(Dataset.project_id == project_id).order_by(Dataset.created_at.desc())
    ).all()
    return DatasetListResponse(items=[_to_summary(dataset) for dataset in datasets])


def get_dataset_model_for_project(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(Dataset.project_id == project_id, Dataset.id == dataset_id)
    )
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def reusable_dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID | None) -> Dataset | None:
    """The dataset a repeating producer (an import, a recipe) writes its next
    version into, or None when it has not made one yet or it has been deleted.

    Producers used to create a new dataset on every run, so a nightly import
    made 365 near-identical datasets a year. Writing a version into the same
    dataset keeps one name with a history, which versions, diff and AS OF
    already understand.
    """
    if dataset_id is None:
        return None
    return db.scalar(select(Dataset).where(Dataset.project_id == project_id, Dataset.id == dataset_id))


def get_dataset_by_project(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DatasetDetailRead:
    ensure_owned_project(db, project_id, current_user.id)
    detail = _to_detail(get_dataset_model_for_project(db, project_id, dataset_id))
    view = _policy_view(db, project_id, dataset_id, current_user)
    if not view.restricted:
        return detail
    return detail.model_copy(update={
        "preview_json": view.preview(detail.preview_json),
        "profile_json": view.profile(detail.profile_json),
        "schema_json": view.schema(detail.schema_json),
    })


def list_dataset_versions(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DatasetVersionListResponse:
    """The recorded snapshot history of a dataset, newest first.

    A read: viewer role (settled matrix, §6). The storage key each version points
    at is deliberately not exposed -- a caller sees what changed and when, not
    where the bytes live."""
    ensure_owned_project(db, project_id, current_user.id)
    # 404 if the dataset is not in this project, rather than an empty list that
    # cannot tell "no history" apart from "no such dataset".
    get_dataset_model_for_project(db, project_id, dataset_id)
    versions = list(
        db.scalars(
            select(DatasetVersion)
            .where(DatasetVersion.dataset_id == dataset_id)
            .order_by(DatasetVersion.version_number.desc())
        ).all()
    )
    current = versions[0].version_number if versions else None
    pins = active_pin_counts(db, [version.id for version in versions])
    return DatasetVersionListResponse(
        items=[_version_read(db, version, pins.get(version.id, 0)) for version in versions],
        current_version=current,
    )


def _version_read(
    db: Session, version: DatasetVersion, active_pins: int | None = None
) -> DatasetVersionRead:
    read = DatasetVersionRead.model_validate(version)
    read.active_pins = active_pin_count(db, version.id) if active_pins is None else active_pins
    return read


def _get_dataset_version(
    db: Session, dataset_id: uuid.UUID, version_number: int
) -> DatasetVersion:
    version = db.scalar(
        select(DatasetVersion).where(
            DatasetVersion.dataset_id == dataset_id,
            DatasetVersion.version_number == version_number,
        )
    )
    if version is None:
        raise NotFoundError(f"This dataset has no version {version_number}.")
    return version


def get_dataset_version(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_number: int,
    current_user: UserRead,
) -> DatasetVersionRead:
    """Metadata for one specific version. A read: viewer role (§6)."""
    ensure_owned_project(db, project_id, current_user.id)
    get_dataset_model_for_project(db, project_id, dataset_id)
    return _version_read(db, _get_dataset_version(db, dataset_id, version_number))


def get_dataset_version_preview(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_number: int,
    current_user: UserRead,
) -> DatasetPreviewResponse:
    """Read a dataset *as of* a version: the preview captured when that version
    was published, so history shows the data as it was then rather than the
    current head. A read: viewer role (§6). Mirrors the base dataset preview's
    security posture -- neither applies an enforced row/column policy gate today;
    if that gate lands, it lands at the shared read layer for both."""
    ensure_owned_project(db, project_id, current_user.id)
    get_dataset_model_for_project(db, project_id, dataset_id)
    version = _get_dataset_version(db, dataset_id, version_number)
    # A pruned version answers with why, not with an empty table that looks
    # like a dataset with no rows.
    require_readable(version)
    preview = _policy_view(db, project_id, dataset_id, current_user).preview(
        version.preview_json or {"columns": [], "rows": []}
    )
    return DatasetPreviewResponse(
        dataset_id=dataset_id,
        columns=list(preview.get("columns", [])),
        rows=list(preview.get("rows", [])),
    )


def stored_file_spec(db: Session, path: str) -> dict[str, object] | None:
    """How the stored file at `path` is read: its version's confirmed import
    settings, or its dataset's for a head with no version record (A8)."""
    version = db.scalar(
        select(DatasetVersion).where(DatasetVersion.file_path == path).order_by(DatasetVersion.version_number.desc()).limit(1)
    )
    if version is not None:
        return version.ingest_spec_json
    dataset = db.scalar(select(Dataset).where(Dataset.file_path == path).limit(1))
    return dataset.ingest_spec_json if dataset is not None else None


def _read_version_frame(storage_backend, version: DatasetVersion, fallback_type: str | None):
    """Parse one version's artifact, or say plainly which version cannot be read."""
    # Function-level import: ingestion imports this module's finalize seam, so a
    # module-level import back would be the cycle the hook rule exists to avoid.
    from service_ingestion.read_copy import frame_of

    require_readable(version)
    try:
        stored = storage_backend.read_bytes(version.file_path)
    except Exception as exc:  # noqa: BLE001 - every read failure gets the same honest answer
        raise BadRequestError(
            f"Version {version.version_number}'s saved data could not be read."
        ) from exc
    return frame_of(
        storage_backend, version.file_path, stored, file_type=version.file_type or fallback_type or "csv",
        spec=version.ingest_spec_json,
    )


def read_version_frame(db: Session, dataset: Dataset, version_number: int, storage_backend):
    """One recorded version's rows, read the way that version was read."""
    version = _get_dataset_version(db, dataset.id, version_number)
    return _read_version_frame(storage_backend, version, dataset.file_type)


def diff_dataset_versions(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DatasetVersionDiffRequest,
    current_user: UserRead,
    storage_backend,
) -> DatasetVersionDiff:
    """Compare two recorded versions of one dataset.

    A read (POST only because identity columns ride in the body): resolves to
    viewer via the central `diff` read-only segment — no role logic here.
    Identical digests are answered from the hashes without touching storage.
    """
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    v_from = _get_dataset_version(db, dataset_id, payload.from_version)
    v_to = _get_dataset_version(db, dataset_id, payload.to_version)

    if v_from.content_hash is not None and v_from.content_hash == v_to.content_hash:
        return DatasetVersionDiff(
            dataset_id=dataset_id,
            from_version=v_from.version_number,
            to_version=v_to.version_number,
            identical=True,
            rows_before=v_from.row_count,
            rows_after=v_to.row_count,
            rows_added=0,
            rows_removed=0,
            rows_changed=0,
            changed_available=True,
            method="content digests are equal; the artifacts were not read",
        )

    view = _policy_view(db, project_id, dataset_id, current_user)
    before = view.frame(_read_version_frame(storage_backend, v_from, dataset.file_type))
    after = view.frame(_read_version_frame(storage_backend, v_to, dataset.file_type))
    computed = diff_frames(before, after, payload.identity_columns)
    return DatasetVersionDiff(
        dataset_id=dataset_id,
        from_version=v_from.version_number,
        to_version=v_to.version_number,
        identical=False,
        **computed,
    )


def rollback_dataset_version(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    version_number: int,
    current_user: UserRead,
    storage_backend,
) -> DatasetVersionRead:
    """Make an older version the current data — by appending, never rewriting.

    Settled decision #6: rollback appends a new version whose content is the
    target's; it never mutates, deletes or renumbers history, and it never
    re-runs the producing pipeline. The target's bytes are copied to a fresh
    artifact (every publication owns its path), so the restored head and the
    version it came from remain independent files with matching digests — an
    integrity property a reader can check.
    """
    from service_ingestion.profiling import build_preview, build_profile, infer_schema
    from shared_python.storage import content_digest

    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    target = _get_dataset_version(db, dataset_id, version_number)
    head = db.scalar(
        select(func.max(DatasetVersion.version_number)).where(
            DatasetVersion.dataset_id == dataset_id
        )
    )
    if head == version_number:
        raise BadRequestError(
            f"Version {version_number} is already the current data; there is "
            "nothing to roll back."
        )

    from service_ingestion.read_copy import frame_of

    # §4: hold the target open -- durably, before any bytes are read -- so a
    # retention sweep in another session cannot remove it underneath the copy.
    # A pruned target is refused here with the reason; a pending one is rescued.
    holder_id = uuid.uuid4()
    pin_version(
        db, target, holder_kind="rollback", holder_id=holder_id,
        reason=f"rollback of dataset {dataset_id} to version {version_number}",
    )
    db.commit()

    file_type = target.file_type or dataset.file_type or "csv"
    try:
        payload_bytes = storage_backend.read_bytes(target.file_path)
    except Exception as exc:  # noqa: BLE001 - one honest answer for every read failure
        release_pins(db, holder_kind="rollback", holder_id=holder_id)
        db.commit()
        raise BadRequestError(
            f"Version {version_number}'s saved data could not be read."
        ) from exc
    frame = frame_of(storage_backend, target.file_path, payload_bytes, file_type=file_type, spec=target.ingest_spec_json)

    # A version that breaks an enforced contract is refused in front of the
    # person, with the reasons, before anything is copied (C1).
    from service_quality.data_contracts import ContractBroken, check_new_data

    try:
        verdict = check_new_data(
            db,
            dataset=dataset,
            frame=frame,
            source_type="rollback",
            actor_user_id=current_user.id,
            record_stop=False,
        )
    except ContractBroken:
        release_pins(db, holder_kind="rollback", holder_id=holder_id)
        db.commit()
        raise

    # The original bytes are copied verbatim -- no parse-and-reserialize round
    # trip -- so the restored head's digest equals the target's recorded digest,
    # an integrity property a reader can check.
    extension = "csv" if file_type == "csv" else file_type
    new_path = (
        f"rollbacks/{project_id}/{dataset_id}/{uuid.uuid4().hex}"
        f"_v{target.version_number}.{extension}"
    )
    try:
        storage_backend.save_upload(relative_path=new_path, file_bytes=payload_bytes)
    except OSError as exc:
        raise BadRequestError(f"Unable to store the restored data: {exc}") from exc

    schema = infer_schema(dataframe=frame)
    dataset.file_type = file_type
    version = apply_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path=new_path,
        file_name=f"restored_v{target.version_number}.{extension}",
        schema_json=schema,
        schema_snapshot={"columns": schema["columns"]},
        preview_json=build_preview(dataframe=frame, limit=50),
        profile_json=build_profile(
            dataframe=frame, sample_limit=5, file_size_bytes=len(payload_bytes)
        ),
        row_count=int(len(frame)),
        column_count=int(len(frame.columns)),
        # The restored bytes are the target's own, read the way it was.
        ingest_spec_json=target.ingest_spec_json,
        content_hash=content_digest(payload_bytes),
        created_by_user_id=current_user.id,
        contract_verdict=verdict,
    )
    # The pin is released in the same commit that publishes the restored head,
    # so there is no window where the copy exists but its source is unprotected
    # -- and no window where a crash leaves the head advanced but the pin open
    # forever (an open pin would only keep data, which is the safe direction).
    release_pins(db, holder_kind="rollback", holder_id=holder_id)
    db.commit()
    db.refresh(version)
    return _version_read(db, version)


def update_dataset(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    payload: DatasetUpdate,
    current_user: UserRead,
) -> DatasetDetailRead:
    """Rename a dataset.

    A dataset took its name from whatever the uploaded file was called, and
    there was no way to change it afterwards -- so `export_final_v2 (3).csv`
    was the permanent name of a table people had to work with every day.
    """
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    fields = payload.model_dump(exclude_unset=True)
    if "name" in fields and fields["name"] is not None:
        dataset.name = fields["name"].strip()
    db.commit()
    return _to_detail(dataset)


def delete_dataset(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    current_user: UserRead,
    *,
    storage_backend=None,
) -> None:
    """Remove a dataset, its dependent rows, and the file behind it.

    The row goes first and the bytes second, which is the order that fails
    safely. A stored file with no dataset row is wasted disk somebody can
    reclaim later; a dataset row whose file has been deleted underneath it is a
    dataset that looks fine in every list and fails the moment anyone opens it.

    The file is only removed once nothing else points at it. A derived dataset
    can be materialised from the same artifact as its parent, and deleting the
    copy must not take the original's bytes with it.

    Storage failures are logged rather than raised: the dataset is already gone
    by then, so turning a leaked file into a 500 would report the whole
    deletion as failed when the part the caller asked for succeeded.
    """
    ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)

    # Version artifacts belong to this dataset's history; collect them before
    # the cascade removes the rows that know where they are. Without this, the
    # head file is reclaimed but every older snapshot leaks on disk forever.
    candidate_paths = {path for path in [dataset.file_path] if path}
    candidate_paths.update(
        path
        for path in db.scalars(
            select(DatasetVersion.file_path).where(
                DatasetVersion.dataset_id == dataset_id
            )
        ).all()
        if path
    )

    db.delete(dataset)
    db.commit()

    if storage_backend is None or not candidate_paths:
        return
    for path in candidate_paths:
        # Only remove bytes nothing else points at -- another dataset's head or
        # another dataset's version can share an artifact path.
        still_referenced = db.scalar(
            select(Dataset.id).where(Dataset.file_path == path).limit(1)
        ) or db.scalar(
            select(DatasetVersion.id).where(DatasetVersion.file_path == path).limit(1)
        )
        if still_referenced is not None:
            continue
        try:
            storage_backend.delete(path)
            from service_ingestion.read_copy import forget_copy

            forget_copy(storage_backend, path)
        except Exception:  # noqa: BLE001 - the row is gone; this is cleanup, not the request
            logger.warning(
                "dataset_artifact_not_removed dataset_id=%s path=%s", dataset_id, path
            )


def get_dataset_preview(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DatasetPreviewResponse:
    dataset = get_dataset_by_project(db, project_id, dataset_id, current_user)
    preview = dataset.preview_json or {"columns": [], "rows": []}
    return DatasetPreviewResponse(
        dataset_id=dataset.id,
        columns=list(preview.get("columns", [])),
        rows=list(preview.get("rows", [])),
    )


def get_dataset_profile(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DatasetProfileResponse:
    dataset = get_dataset_by_project(db, project_id, dataset_id, current_user)
    return DatasetProfileResponse(dataset_id=dataset.id, profile=dataset.profile_json)


def get_dataset_audit_summary(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DatasetAuditSummary:
    project = ensure_owned_project(db, project_id, current_user.id)
    dataset = get_dataset_model_for_project(db, project_id, dataset_id)
    summary = build_dataset_audit_summary(
        dataset=dataset,
        project_id=project.id,
        project_name=project.name,
    )
    from service_auth.models import User
    from service_transformations.models import TransformationPipeline

    if dataset.uploaded_by_user_id is not None:
        person = db.get(User, dataset.uploaded_by_user_id)
        summary.uploaded_by_name = (person.display_name or person.username) if person else None
    if dataset.parent_dataset_id is not None:
        parent = db.get(Dataset, dataset.parent_dataset_id)
        summary.parent_dataset_name = parent.name if parent else None
    if dataset.created_from_pipeline_id is not None:
        recipe = db.get(TransformationPipeline, dataset.created_from_pipeline_id)
        summary.created_from_pipeline_name = recipe.name if recipe else None
    view = _policy_view(db, project_id, dataset_id, current_user)
    if view.restricted:
        highlights = summary.profile_highlights
        summary.schema_summary.sample_column_names = view.visible_columns(summary.schema_summary.sample_column_names)
        highlights.high_null_columns = view.visible_columns(highlights.high_null_columns)
        highlights.constant_value_columns = view.visible_columns(highlights.constant_value_columns)
        highlights.potential_id_columns = view.visible_columns(highlights.potential_id_columns)
        if view.filters_rows:
            # Figures over every row would describe rows this person cannot see.
            highlights.duplicate_row_count = None
            highlights.duplicate_row_percentage = None
            highlights.completeness_score = None
    return summary


def create_dataset(
    db: Session, project_id: uuid.UUID, payload: DatasetCreate, current_user: UserRead
) -> DatasetDetailRead:
    ensure_owned_project(db, project_id, current_user.id)
    if payload.source_id is not None:
        get_source_for_project(db, payload.source_id, project_id)

    dataset = Dataset(
        project_id=project_id,
        source_id=payload.source_id,
        uploaded_by_user_id=current_user.id,
        is_derived=False,
        name=payload.name.strip(),
        original_filename=payload.original_filename.strip() if payload.original_filename else None,
        status=payload.status,
        ingestion_status="pending",
        row_count=payload.row_count,
        column_count=payload.column_count,
        schema_snapshot=payload.schema_snapshot,
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return _to_detail(dataset)


def create_uploaded_dataset_placeholder(
    db: Session,
    *,
    project_id: uuid.UUID,
    name: str,
    original_filename: str,
    file_type: str,
    file_size_bytes: int,
    current_user: UserRead,
    pipeline_run_id: uuid.UUID,
) -> Dataset:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = Dataset(
        project_id=project_id,
        uploaded_by_user_id=current_user.id,
        pipeline_run_id=pipeline_run_id,
        is_derived=False,
        name=name.strip(),
        original_filename=original_filename,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        status="processing",
        ingestion_status="queued",
    )
    db.add(dataset)
    db.flush()
    return dataset


def create_derived_dataset_placeholder(
    db: Session,
    *,
    project_id: uuid.UUID,
    parent_dataset_id: uuid.UUID,
    created_from_pipeline_id: uuid.UUID,
    name: str,
    original_filename: str,
    file_type: str,
    file_size_bytes: int,
    source_id: uuid.UUID | None,
    current_user: UserRead,
    pipeline_run_id: uuid.UUID,
) -> Dataset:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = Dataset(
        project_id=project_id,
        source_id=source_id,
        uploaded_by_user_id=current_user.id,
        pipeline_run_id=pipeline_run_id,
        parent_dataset_id=parent_dataset_id,
        created_from_pipeline_id=created_from_pipeline_id,
        is_derived=True,
        name=name.strip(),
        original_filename=original_filename,
        file_type=file_type,
        file_size_bytes=file_size_bytes,
        status="processing",
        ingestion_status="queued",
    )
    db.add(dataset)
    db.flush()
    return dataset


def mark_dataset_processing_running(db: Session, *, dataset: Dataset) -> Dataset:
    dataset.status = "processing"
    dataset.ingestion_status = "running"
    dataset.ingestion_error = None
    db.flush()
    return dataset


def mark_dataset_ingestion_running(db: Session, *, dataset: Dataset) -> Dataset:
    return mark_dataset_processing_running(db, dataset=dataset)


def _next_version_number(db: Session, dataset_id: uuid.UUID) -> int:
    """The next 1-based version number for a dataset. Read inside the publishing
    transaction so it is consistent with the row about to be inserted; the
    (dataset_id, version_number) unique constraint is the real guard against two
    concurrent publications choosing the same number."""
    highest = db.scalar(
        select(func.max(DatasetVersion.version_number)).where(
            DatasetVersion.dataset_id == dataset_id
        )
    )
    return (highest or 0) + 1


def apply_dataset_materialization_success(
    db: Session,
    *,
    dataset: Dataset,
    file_path: str,
    file_name: str,
    schema_json: dict[str, object],
    schema_snapshot: dict[str, object],
    preview_json: dict[str, object],
    profile_json: dict[str, object],
    row_count: int,
    column_count: int,
    ingest_spec_json: dict[str, object] | None = None,
    content_hash: str | None = None,
    pipeline_run_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID | None = None,
    contract_verdict: object | None = None,
) -> DatasetVersion:
    """Advance a dataset's head and append its immutable version, then FLUSH --
    without committing.

    The commit boundary belongs to the caller (settled contract in
    `docs/plans/phase-18-review-requirements.md` §5): head advance and version
    publication must land in one transaction, so the two can never disagree about
    what the current data is. `finalize_dataset_materialization_success` is the
    commit-owning wrapper the existing producers use; a caller that needs a wider
    atomic transaction calls this directly and owns the commit itself.

    Returns the newly published `DatasetVersion` (already flushed, so it has an
    id) rather than a detail read, because the detail read is only meaningful
    after the commit the caller controls.

    `contract_verdict` is what the dataset's contract made of this data
    (`service_quality.data_contracts.check_new_data`, called by the producer
    before it stored anything); recording it here puts the outcome in the
    version's own transaction.
    """
    dataset.file_path = file_path
    dataset.file_name = file_name
    dataset.row_count = row_count
    dataset.column_count = column_count
    dataset.schema_json = schema_json
    dataset.schema_snapshot = schema_snapshot
    dataset.preview_json = preview_json
    dataset.profile_json = profile_json
    dataset.ingestion_status = "succeeded"
    dataset.status = "ready"
    dataset.ingestion_error = None
    dataset.last_profiled_at = datetime.now(UTC)
    # How the head file is read, kept with the dataset and its version:
    # re-reading the same file needs the same answers rather than a fresh
    # inference. Set every time: keeping an earlier upload's settings once a
    # recipe's output became the head would read that output wrongly (A8),
    # and a file Pipewright wrote itself is read back as it was written
    # (`service_ingestion.written`, E2).
    dataset.ingest_spec_json = ingest_spec_json

    version = DatasetVersion(
        dataset_id=dataset.id,
        version_number=_next_version_number(db, dataset.id),
        content_hash=content_hash,
        file_path=file_path,
        file_name=file_name,
        file_type=dataset.file_type,
        row_count=row_count,
        column_count=column_count,
        schema_json=schema_json,
        preview_json=preview_json,
        ingest_spec_json=ingest_spec_json,
        statistics_json=statistics_of(profile_json),
        pipeline_run_id=pipeline_run_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(version)
    db.flush()
    if contract_verdict is not None:
        from service_quality.data_contracts import record_landing

        record_landing(db, dataset=dataset, verdict=contract_verdict)
    _record_measures(db, dataset=dataset, profile_json=profile_json, pipeline_run_id=pipeline_run_id)
    return version


def _record_measures(
    db: Session, *, dataset: Dataset, profile_json: dict[str, object], pipeline_run_id: uuid.UUID | None
) -> None:
    """Record the new data's measures and check its alerts (A8, Y5).

    Every upload, import, recipe run, rollback and erasure passes through
    here, so a dataset's history and its alerts follow every change, not only
    the ones a workflow makes. In the same transaction as the new version, so
    data that is rolled back leaves no measures and sends no alert. Best
    effort, in a savepoint: a measurement problem never fails the data.
    """
    try:
        from service_observability.service import record_dataset_metrics

        with db.begin_nested():
            record_dataset_metrics(
                db,
                project_id=dataset.project_id,
                dataset_id=dataset.id,
                profile=profile_json,
                pipeline_run_id=pipeline_run_id,
            )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("measure_capture_failed dataset_id=%s", dataset.id)


def finalize_dataset_materialization_success(
    db: Session,
    *,
    dataset: Dataset,
    file_path: str,
    file_name: str,
    schema_json: dict[str, object],
    schema_snapshot: dict[str, object],
    preview_json: dict[str, object],
    profile_json: dict[str, object],
    row_count: int,
    column_count: int,
    ingest_spec_json: dict[str, object] | None = None,
    content_hash: str | None = None,
    pipeline_run_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID | None = None,
    contract_verdict: object | None = None,
) -> DatasetDetailRead:
    apply_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path=file_path,
        file_name=file_name,
        schema_json=schema_json,
        schema_snapshot=schema_snapshot,
        preview_json=preview_json,
        profile_json=profile_json,
        row_count=row_count,
        column_count=column_count,
        ingest_spec_json=ingest_spec_json,
        content_hash=content_hash,
        pipeline_run_id=pipeline_run_id,
        created_by_user_id=created_by_user_id,
        contract_verdict=contract_verdict,
    )
    db.commit()
    db.refresh(dataset)
    return _to_detail(dataset)


def finalize_dataset_ingestion_success(
    db: Session,
    *,
    dataset: Dataset,
    file_path: str,
    file_name: str,
    schema_json: dict[str, object],
    schema_snapshot: dict[str, object],
    preview_json: dict[str, object],
    profile_json: dict[str, object],
    row_count: int,
    column_count: int,
    ingest_spec_json: dict[str, object] | None = None,
    content_hash: str | None = None,
    pipeline_run_id: uuid.UUID | None = None,
    created_by_user_id: uuid.UUID | None = None,
    contract_verdict: object | None = None,
) -> DatasetDetailRead:
    return finalize_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path=file_path,
        file_name=file_name,
        schema_json=schema_json,
        schema_snapshot=schema_snapshot,
        preview_json=preview_json,
        profile_json=profile_json,
        row_count=row_count,
        column_count=column_count,
        ingest_spec_json=ingest_spec_json,
        content_hash=content_hash,
        pipeline_run_id=pipeline_run_id,
        created_by_user_id=created_by_user_id,
        contract_verdict=contract_verdict,
    )


def finalize_dataset_processing_failure(
    db: Session, *, dataset: Dataset, ingestion_error: str
) -> DatasetDetailRead:
    dataset.ingestion_status = "failed"
    dataset.status = "failed"
    dataset.ingestion_error = ingestion_error
    db.commit()
    db.refresh(dataset)
    return _to_detail(dataset)


def finalize_dataset_ingestion_failure(
    db: Session, *, dataset: Dataset, ingestion_error: str
) -> DatasetDetailRead:
    return finalize_dataset_processing_failure(db, dataset=dataset, ingestion_error=ingestion_error)
