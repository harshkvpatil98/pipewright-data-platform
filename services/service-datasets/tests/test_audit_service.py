from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import patch

from service_auth.schemas import UserRead
from service_datasets.service import get_dataset_audit_summary
from shared_python.errors import NotFoundError


@patch("service_datasets.service.build_dataset_audit_summary")
@patch("service_datasets.service.get_dataset_model_for_project")
@patch("service_datasets.service.ensure_owned_project")
def test_get_dataset_audit_summary_requires_owned_project(
    ensure_owned_project,
    get_dataset_model_for_project,
    build_dataset_audit_summary,
) -> None:
    ensure_owned_project.side_effect = NotFoundError("Project not found.")
    user = UserRead(
        id=uuid.uuid4(),
        username="u",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    try:
        get_dataset_audit_summary(object(), uuid.uuid4(), uuid.uuid4(), user)
    except NotFoundError:
        pass
    else:
        raise AssertionError("expected NotFoundError")
    get_dataset_model_for_project.assert_not_called()
    build_dataset_audit_summary.assert_not_called()
