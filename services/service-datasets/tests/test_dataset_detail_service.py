import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_by_project, get_dataset_preview, get_dataset_profile
from shared_python.errors import NotFoundError


@patch("service_datasets.service.get_dataset_by_project")
def test_get_dataset_preview_reads_stored_preview(get_dataset_by_project) -> None:
    dataset_id = uuid.uuid4()
    get_dataset_by_project.return_value = SimpleNamespace(
        id=dataset_id,
        preview_json={"columns": ["a"], "rows": [{"a": 1}]},
    )
    user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    response = get_dataset_preview(object(), uuid.uuid4(), dataset_id, user)
    assert response.columns == ["a"]
    assert response.rows == [{"a": 1}]


@patch("service_datasets.service.get_dataset_by_project")
def test_get_dataset_profile_reads_stored_profile(get_dataset_by_project) -> None:
    dataset_id = uuid.uuid4()
    get_dataset_by_project.return_value = SimpleNamespace(
        id=dataset_id,
        profile_json={"row_count": 3},
    )
    user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    response = get_dataset_profile(object(), uuid.uuid4(), dataset_id, user)
    assert response.profile == {"row_count": 3}


@patch("service_datasets.service.ensure_owned_project", side_effect=NotFoundError("Project not found."))
def test_get_dataset_by_project_enforces_project_ownership(_ensure_owned_project) -> None:
    user = UserRead(
        id=uuid.uuid4(),
        username="platform-admin",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    try:
        get_dataset_by_project(object(), uuid.uuid4(), uuid.uuid4(), user)
    except NotFoundError as exc:
        assert exc.detail == "Project not found."
    else:
        raise AssertionError("Expected project ownership enforcement to raise NotFoundError.")
