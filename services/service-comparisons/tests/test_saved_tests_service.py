from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from service_auth.schemas import UserRead
from service_comparisons.saved_tests_service import _comparison_note, create_saved_statistical_test
from service_comparisons.schemas import (
    DatasetStatisticalTestResult,
    SavedStatisticalTestCreate,
    SavedStatisticalTestRunRead,
    StatisticalTestDatasetSide,
)
from shared_python.errors import BadRequestError, NotFoundError


def _user() -> UserRead:
    return UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def _minimal_result(p_value: float) -> DatasetStatisticalTestResult:
    lid, rid = uuid.uuid4(), uuid.uuid4()
    return DatasetStatisticalTestResult(
        test_type="welch_t_test",
        column_name="x",
        left_dataset=StatisticalTestDatasetSide(id=lid, name="L", sample_size=10),
        right_dataset=StatisticalTestDatasetSide(id=rid, name="R", sample_size=10),
        p_value=p_value,
        statistic=1.0,
    )


def test_comparison_note_two_successful_runs() -> None:
    reads = [
        SavedStatisticalTestRunRead(
            id=uuid.uuid4(),
            saved_test_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            status="succeeded",
            executed_by_user_id=None,
            result=_minimal_result(0.01),
            error_message=None,
            warnings_json=None,
            created_at=datetime.now(UTC),
        ),
        SavedStatisticalTestRunRead(
            id=uuid.uuid4(),
            saved_test_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            status="succeeded",
            executed_by_user_id=None,
            result=_minimal_result(0.4),
            error_message=None,
            warnings_json=None,
            created_at=datetime.now(UTC),
        ),
    ]
    note = _comparison_note(reads)
    assert note is not None
    assert "0.01" in note or "1e-2" in note or "latest" in note.lower()


def test_comparison_note_insufficient_runs() -> None:
    reads = [
        SavedStatisticalTestRunRead(
            id=uuid.uuid4(),
            saved_test_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            status="succeeded",
            executed_by_user_id=None,
            result=_minimal_result(0.01),
            error_message=None,
            warnings_json=None,
            created_at=datetime.now(UTC),
        ),
    ]
    assert _comparison_note(reads) is None


@patch("service_comparisons.saved_tests_service.get_dataset_model_for_project")
@patch("service_comparisons.saved_tests_service.ensure_owned_project")
def test_create_saved_rejects_same_dataset(ensure_owned, get_ds) -> None:
    ensure_owned.return_value = None
    db = MagicMock()
    pid = uuid.uuid4()
    did = uuid.uuid4()
    user = _user()
    payload = SavedStatisticalTestCreate(
        name="n",
        left_dataset_id=did,
        right_dataset_id=did,
        test_type="welch_t_test",
        column_name="x",
    )
    with pytest.raises(BadRequestError, match="different"):
        create_saved_statistical_test(db, pid, payload, user)
    get_ds.assert_not_called()


@patch("service_comparisons.saved_tests_service.get_dataset_model_for_project")
@patch("service_comparisons.saved_tests_service.ensure_owned_project")
def test_create_saved_calls_add_and_commit(ensure_owned, get_ds) -> None:
    ensure_owned.return_value = None
    pid = uuid.uuid4()
    lid, rid = uuid.uuid4(), uuid.uuid4()
    left = MagicMock()
    left.name = "L"
    left.schema_json = {"columns": [{"name": "x"}]}
    right = MagicMock()
    right.name = "R"
    right.schema_json = {"columns": [{"name": "x"}]}
    get_ds.side_effect = [left, right]

    db = MagicMock()
    user = _user()
    payload = SavedStatisticalTestCreate(
        name="n",
        left_dataset_id=lid,
        right_dataset_id=rid,
        test_type="welch_t_test",
        column_name="x",
    )

    def fake_refresh(obj: object) -> None:
        setattr(obj, "created_at", datetime.now(UTC))
        setattr(obj, "updated_at", datetime.now(UTC))

    db.refresh.side_effect = fake_refresh
    create_saved_statistical_test(db, pid, payload, user)
    db.add.assert_called_once()
    db.commit.assert_called_once()


@patch("service_comparisons.saved_tests_service.ensure_owned_project", side_effect=NotFoundError("missing"))
def test_create_saved_requires_project(_e) -> None:
    db = MagicMock()
    user = _user()
    payload = SavedStatisticalTestCreate(
        name="n",
        left_dataset_id=uuid.uuid4(),
        right_dataset_id=uuid.uuid4(),
        test_type="welch_t_test",
        column_name="x",
    )
    with pytest.raises(NotFoundError):
        create_saved_statistical_test(db, uuid.uuid4(), payload, user)


@patch("service_comparisons.saved_tests_service.run_dataset_statistical_test")
@patch("service_comparisons.saved_tests_service.get_saved_test_model")
@patch("service_comparisons.saved_tests_service.ensure_owned_project")
def test_run_saved_marks_failed_on_bad_request(ensure_owned, get_model, run_test) -> None:
    ensure_owned.return_value = None
    st = MagicMock()
    st.id = uuid.uuid4()
    st.project_id = uuid.uuid4()
    st.left_dataset_id = uuid.uuid4()
    st.right_dataset_id = uuid.uuid4()
    st.test_type = "welch_t_test"
    st.column_name = "x"
    get_model.return_value = st
    run_test.side_effect = BadRequestError("bad")

    db = MagicMock()
    added: list[object] = []
    db.add.side_effect = lambda o: added.append(o)
    db.flush.side_effect = lambda: None

    def fake_refresh(obj: object) -> None:
        if getattr(obj, "created_at", None) is None:
            setattr(obj, "created_at", datetime.now(UTC))

    db.refresh.side_effect = fake_refresh

    from service_comparisons.saved_tests_service import run_saved_statistical_test

    run_saved_statistical_test(db, st.project_id, st.id, _user(), object())

    assert len(added) == 1
    run = added[0]
    assert run.status == "failed"
    assert run.error_message == "bad"
    db.commit.assert_called_once()
