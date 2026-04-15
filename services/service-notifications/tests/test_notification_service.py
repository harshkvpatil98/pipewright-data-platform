from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from service_auth.schemas import UserRead
from service_notifications.models import UserNotification
from service_notifications.service import create_user_notification, mark_notification_read
from shared_python.errors import NotFoundError


def _user(*, uid: uuid.UUID | None = None) -> UserRead:
    return UserRead(
        id=uid or uuid.uuid4(),
        username="u1",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


@patch("service_notifications.service.UserNotificationRead.model_validate")
@patch("service_notifications.service.UserNotification")
def test_create_user_notification_adds_row(mock_cls: MagicMock, mock_validate: MagicMock) -> None:
    inst = MagicMock()
    mock_cls.return_value = inst
    mock_validate.return_value = MagicMock()
    db = MagicMock()
    uid = uuid.uuid4()
    create_user_notification(
        db,
        user_id=uid,
        project_id=None,
        type="transformation_run_succeeded",
        level="success",
        title="Transformation run succeeded",
        message="ok",
    )
    db.add.assert_called_once_with(inst)
    db.commit.assert_called_once()
    mock_cls.assert_called_once()


def test_mark_read_enforces_owner() -> None:
    owner = uuid.uuid4()
    other = uuid.uuid4()
    nid = uuid.uuid4()
    row = MagicMock(spec=UserNotification)
    row.user_id = owner
    row.is_read = False

    db = MagicMock()
    db.get.return_value = row

    with pytest.raises(NotFoundError):
        mark_notification_read(db, notification_id=nid, current_user=_user(uid=other))
