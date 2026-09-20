from __future__ import annotations

import uuid
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_datasets.models import Dataset
from service_datasets.service import get_dataset_model_for_project
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError

from service_comparisons.models import SavedStatisticalTest, SavedStatisticalTestRun
from service_comparisons.schemas import (
    DatasetStatisticalTestRequest,
    DatasetStatisticalTestResult,
    SavedStatisticalTestCreate,
    SavedStatisticalTestDetail,
    SavedStatisticalTestListItem,
    SavedStatisticalTestListResponse,
    SavedStatisticalTestRead,
    SavedStatisticalTestRunRead,
    SavedStatisticalTestRunsResponse,
    SavedStatisticalTestUpdate,
)
from service_comparisons.testing_service import (
    _validate_column_declared,
    run_dataset_statistical_test,
)


def _dataset_name_map(db: Session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    rows = db.execute(select(Dataset.id, Dataset.name).where(Dataset.id.in_(ids))).all()
    return {row[0]: row[1] for row in rows}


def _to_run_read(run: SavedStatisticalTestRun) -> SavedStatisticalTestRunRead:
    result: DatasetStatisticalTestResult | None = None
    if run.result_json:
        result = DatasetStatisticalTestResult.model_validate(run.result_json)
    return SavedStatisticalTestRunRead(
        id=run.id,
        saved_test_id=run.saved_test_id,
        project_id=run.project_id,
        status=run.status,
        executed_by_user_id=run.executed_by_user_id,
        result=result,
        error_message=run.error_message,
        warnings_json=run.warnings_json,
        created_at=run.created_at,
    )


def _comparison_note(runs_read: list[SavedStatisticalTestRunRead]) -> str | None:
    succeeded: list[SavedStatisticalTestRunRead] = []
    for r in runs_read:
        if r.status != "succeeded" or r.result is None or r.result.p_value is None:
            continue
        succeeded.append(r)
    if len(succeeded) < 2:
        return None
    latest_p = succeeded[0].result.p_value
    prev_p = succeeded[1].result.p_value
    return (
        f"Latest successful run p-value: {latest_p:.4g}; previous: {prev_p:.4g}. "
        "Values reflect the current datasets; this is not causal inference."
    )


def _to_saved_read(
    st: SavedStatisticalTest,
    *,
    left_name: str,
    right_name: str,
) -> SavedStatisticalTestRead:
    return SavedStatisticalTestRead(
        id=st.id,
        project_id=st.project_id,
        name=st.name,
        description=st.description,
        test_type=st.test_type,
        column_name=st.column_name,
        options_json=st.options_json,
        left_dataset_id=st.left_dataset_id,
        right_dataset_id=st.right_dataset_id,
        left_dataset_name=left_name,
        right_dataset_name=right_name,
        created_by_user_id=st.created_by_user_id,
        created_at=st.created_at,
        updated_at=st.updated_at,
    )


def get_saved_test_model(
    db: Session, project_id: uuid.UUID, saved_test_id: uuid.UUID
) -> SavedStatisticalTest:
    st = db.scalar(
        select(SavedStatisticalTest).where(
            SavedStatisticalTest.id == saved_test_id,
            SavedStatisticalTest.project_id == project_id,
        )
    )
    if st is None:
        raise NotFoundError("Saved statistical test not found.")
    return st


def create_saved_statistical_test(
    db: Session,
    project_id: uuid.UUID,
    payload: SavedStatisticalTestCreate,
    current_user: UserRead,
) -> SavedStatisticalTestRead:
    ensure_owned_project(db, project_id, current_user.id)
    if payload.left_dataset_id == payload.right_dataset_id:
        raise BadRequestError("Saved test datasets must be two different datasets.")
    left = get_dataset_model_for_project(db, project_id, payload.left_dataset_id)
    right = get_dataset_model_for_project(db, project_id, payload.right_dataset_id)
    column_key = payload.column_name.strip()
    if not column_key:
        raise BadRequestError("Column name is required.")
    _validate_column_declared(left, right, column_key)

    st = SavedStatisticalTest(
        id=uuid.uuid4(),
        project_id=project_id,
        left_dataset_id=payload.left_dataset_id,
        right_dataset_id=payload.right_dataset_id,
        name=payload.name.strip(),
        description=payload.description,
        test_type=payload.test_type,
        column_name=column_key,
        options_json=payload.options_json,
        created_by_user_id=current_user.id,
    )
    db.add(st)
    db.commit()
    db.refresh(st)
    return _to_saved_read(st, left_name=left.name, right_name=right.name)


def list_saved_statistical_tests(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    left_dataset_id: uuid.UUID | None = None,
    right_dataset_id: uuid.UUID | None = None,
) -> SavedStatisticalTestListResponse:
    ensure_owned_project(db, project_id, current_user.id)

    last_run_sq = (
        select(
            SavedStatisticalTestRun.saved_test_id,
            func.max(SavedStatisticalTestRun.created_at).label("last_run_at"),
        ).group_by(SavedStatisticalTestRun.saved_test_id)
    ).subquery()

    stmt = (
        select(SavedStatisticalTest, last_run_sq.c.last_run_at)
        .outerjoin(last_run_sq, SavedStatisticalTest.id == last_run_sq.c.saved_test_id)
        .where(SavedStatisticalTest.project_id == project_id)
    )
    if left_dataset_id is not None:
        stmt = stmt.where(SavedStatisticalTest.left_dataset_id == left_dataset_id)
    if right_dataset_id is not None:
        stmt = stmt.where(SavedStatisticalTest.right_dataset_id == right_dataset_id)
    stmt = stmt.order_by(SavedStatisticalTest.updated_at.desc())

    rows = db.execute(stmt).all()
    items: list[SavedStatisticalTestListItem] = []
    id_set: set[uuid.UUID] = set()
    for st, last_run_at in rows:
        id_set.add(st.left_dataset_id)
        id_set.add(st.right_dataset_id)
    name_map = _dataset_name_map(db, id_set)

    for st, last_run_at in rows:
        items.append(
            SavedStatisticalTestListItem(
                id=st.id,
                project_id=st.project_id,
                name=st.name,
                test_type=st.test_type,
                column_name=st.column_name,
                left_dataset_id=st.left_dataset_id,
                right_dataset_id=st.right_dataset_id,
                left_dataset_name=name_map.get(st.left_dataset_id, ""),
                right_dataset_name=name_map.get(st.right_dataset_id, ""),
                last_run_at=last_run_at,
                updated_at=st.updated_at,
            )
        )
    return SavedStatisticalTestListResponse(items=items)


def get_saved_statistical_test_detail(
    db: Session, project_id: uuid.UUID, saved_test_id: uuid.UUID, current_user: UserRead
) -> SavedStatisticalTestDetail:
    ensure_owned_project(db, project_id, current_user.id)
    st = get_saved_test_model(db, project_id, saved_test_id)
    left = get_dataset_model_for_project(db, project_id, st.left_dataset_id)
    right = get_dataset_model_for_project(db, project_id, st.right_dataset_id)

    runs = db.scalars(
        select(SavedStatisticalTestRun)
        .where(SavedStatisticalTestRun.saved_test_id == st.id)
        .order_by(SavedStatisticalTestRun.created_at.desc())
    ).all()
    runs_read = [_to_run_read(r) for r in runs]
    note = _comparison_note(runs_read)
    return SavedStatisticalTestDetail(
        saved_test=_to_saved_read(st, left_name=left.name, right_name=right.name),
        runs=runs_read,
        comparison_note=note,
    )


def update_saved_statistical_test(
    db: Session,
    project_id: uuid.UUID,
    saved_test_id: uuid.UUID,
    payload: SavedStatisticalTestUpdate,
    current_user: UserRead,
) -> SavedStatisticalTestRead:
    ensure_owned_project(db, project_id, current_user.id)
    st = get_saved_test_model(db, project_id, saved_test_id)
    if payload.name is not None:
        st.name = payload.name.strip()
    if payload.description is not None:
        st.description = payload.description
    db.commit()
    db.refresh(st)
    left = get_dataset_model_for_project(db, project_id, st.left_dataset_id)
    right = get_dataset_model_for_project(db, project_id, st.right_dataset_id)
    return _to_saved_read(st, left_name=left.name, right_name=right.name)


def delete_saved_statistical_test(
    db: Session, project_id: uuid.UUID, saved_test_id: uuid.UUID, current_user: UserRead
) -> None:
    """Remove a saved test and the history of its runs.

    The runs go with it: `saved_statistical_test_runs.saved_test_id` is
    `ON DELETE CASCADE`, so there is no separate sweep to forget and no way to
    leave a run pointing at a test that is gone.
    """
    ensure_owned_project(db, project_id, current_user.id)
    saved = get_saved_test_model(db, project_id, saved_test_id)
    db.delete(saved)
    db.commit()


def run_saved_statistical_test(
    db: Session,
    project_id: uuid.UUID,
    saved_test_id: uuid.UUID,
    current_user: UserRead,
    storage_backend: Any,
) -> SavedStatisticalTestRunRead:
    ensure_owned_project(db, project_id, current_user.id)
    st = get_saved_test_model(db, project_id, saved_test_id)

    try:
        payload = DatasetStatisticalTestRequest(
            test_type=st.test_type,  # type: ignore[arg-type]
            column_name=st.column_name,
        )
    except ValidationError as exc:
        run = SavedStatisticalTestRun(
            id=uuid.uuid4(),
            saved_test_id=st.id,
            project_id=st.project_id,
            status="failed",
            executed_by_user_id=current_user.id,
            result_json=None,
            warnings_json=None,
            error_message=f"Invalid saved test configuration: {exc}",
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return _to_run_read(run)

    run = SavedStatisticalTestRun(
        id=uuid.uuid4(),
        saved_test_id=st.id,
        project_id=st.project_id,
        status="failed",
        executed_by_user_id=current_user.id,
        result_json=None,
        warnings_json=None,
        error_message=None,
    )
    db.add(run)
    db.flush()

    try:
        result = run_dataset_statistical_test(
            db,
            project_id=st.project_id,
            left_dataset_id=st.left_dataset_id,
            right_dataset_id=st.right_dataset_id,
            payload=payload,
            current_user=current_user,
            storage_backend=storage_backend,
        )
    except BadRequestError as exc:
        run.error_message = exc.detail
        run.status = "failed"
    except NotFoundError as exc:
        run.error_message = exc.detail
        run.status = "failed"
    except Exception as exc:  # noqa: BLE001 — persist unexpected failures for history
        run.error_message = str(exc)
        run.status = "failed"
    else:
        run.status = "succeeded"
        run.result_json = result.model_dump(mode="json")
        run.warnings_json = list(result.warnings) if result.warnings else None

    db.commit()
    db.refresh(run)
    return _to_run_read(run)


def list_saved_statistical_test_runs(
    db: Session, project_id: uuid.UUID, saved_test_id: uuid.UUID, current_user: UserRead
) -> SavedStatisticalTestRunsResponse:
    ensure_owned_project(db, project_id, current_user.id)
    get_saved_test_model(db, project_id, saved_test_id)
    runs = db.scalars(
        select(SavedStatisticalTestRun)
        .where(
            SavedStatisticalTestRun.saved_test_id == saved_test_id,
            SavedStatisticalTestRun.project_id == project_id,
        )
        .order_by(SavedStatisticalTestRun.created_at.desc())
    ).all()
    return SavedStatisticalTestRunsResponse(items=[_to_run_read(r) for r in runs])
