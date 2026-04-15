from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from service_auth.schemas import UserRead
from service_comparisons.schemas import DatasetStatisticalTestRequest
from service_comparisons.service import get_dataset_comparison_summary, get_run_comparison_summary
from service_comparisons.testing_service import run_dataset_statistical_test
from shared_python.errors import BadRequestError, NotFoundError


@patch("service_comparisons.service.ensure_owned_project")
def test_get_dataset_comparison_rejects_same_id(ensure_owned_project) -> None:
    ensure_owned_project.return_value = object()
    user = UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    pid = uuid.uuid4()
    did = uuid.uuid4()
    try:
        get_dataset_comparison_summary(object(), pid, did, did, user)
    except BadRequestError as exc:
        assert "itself" in exc.detail.lower()
    else:
        raise AssertionError("expected BadRequestError")


@patch("service_comparisons.testing_service.ensure_owned_project")
def test_statistical_test_rejects_self_compare(ensure_owned_project) -> None:
    ensure_owned_project.return_value = object()
    user = UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    did = uuid.uuid4()
    try:
        run_dataset_statistical_test(
            object(),
            project_id=uuid.uuid4(),
            left_dataset_id=did,
            right_dataset_id=did,
            payload=DatasetStatisticalTestRequest(test_type="welch_t_test", column_name="x"),
            current_user=user,
            storage_backend=object(),
        )
    except BadRequestError as exc:
        assert "itself" in exc.detail.lower()
    else:
        raise AssertionError("expected BadRequestError")


@patch("service_comparisons.testing_service.ensure_owned_project", side_effect=NotFoundError("Project not found."))
def test_statistical_test_requires_project(_ensure) -> None:
    user = UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    try:
        run_dataset_statistical_test(
            object(),
            project_id=uuid.uuid4(),
            left_dataset_id=uuid.uuid4(),
            right_dataset_id=uuid.uuid4(),
            payload=DatasetStatisticalTestRequest(test_type="welch_t_test", column_name="x"),
            current_user=user,
            storage_backend=object(),
        )
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError")


@patch("service_comparisons.service.ensure_owned_project", side_effect=NotFoundError("Project not found."))
def test_get_dataset_comparison_requires_project(_ensure) -> None:
    user = UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    try:
        get_dataset_comparison_summary(object(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), user)
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError")


@patch("service_comparisons.service.ensure_owned_project", side_effect=NotFoundError("Project not found."))
def test_get_run_comparison_requires_project(_ensure) -> None:
    user = UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    try:
        get_run_comparison_summary(object(), uuid.uuid4(), uuid.uuid4(), user)
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError")
