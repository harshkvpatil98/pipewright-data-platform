from __future__ import annotations

import uuid
from datetime import UTC, datetime

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
)
from service_projects.contracts import ensure_owned_project
from service_sources.contracts import get_source_for_project
from shared_python.errors import NotFoundError
from shared_python.logging import get_logger

logger = get_logger(__name__)


def _to_summary(dataset: Dataset) -> DatasetSummaryRead:
    return DatasetSummaryRead.model_validate(dataset)


def _to_detail(dataset: Dataset) -> DatasetDetailRead:
    return DatasetDetailRead.model_validate(dataset)


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


def get_dataset_by_project(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead
) -> DatasetDetailRead:
    ensure_owned_project(db, project_id, current_user.id)
    return _to_detail(get_dataset_model_for_project(db, project_id, dataset_id))


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
    file_path = dataset.file_path

    db.delete(dataset)
    db.commit()

    if storage_backend is None or not file_path:
        return
    still_referenced = db.scalar(
        select(Dataset.id).where(Dataset.file_path == file_path).limit(1)
    )
    if still_referenced is not None:
        return
    try:
        storage_backend.delete(file_path)
    except Exception:  # noqa: BLE001 - the row is gone; this is cleanup, not the request
        logger.warning(
            "dataset_artifact_not_removed dataset_id=%s path=%s", dataset_id, file_path
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
    return build_dataset_audit_summary(
        dataset=dataset,
        project_id=project.id,
        project_name=project.name,
    )


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
    if ingest_spec_json is not None:
        # How the file was read, kept with the dataset: "why is this column
        # text" needs an answer, and re-reading the same file needs the same
        # answers rather than a fresh inference over different data.
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
        pipeline_run_id=pipeline_run_id,
        created_by_user_id=created_by_user_id,
    )
    db.add(version)
    db.flush()
    return version


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
