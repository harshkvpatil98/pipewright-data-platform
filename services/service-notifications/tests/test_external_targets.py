from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from service_auth.schemas import UserRead
from service_notifications.at_rest_config import (
    notification_target_config_for_internal_use,
    persist_notification_target_config_at_rest,
)
from service_notifications.external_dispatch import dispatch_external_notifications
from service_notifications.outcomes import _persist_notification  # noqa: PLC2701
from service_notifications.redaction import redact_config_for_api
from service_notifications.target_schemas import ExternalNotificationTargetCreate, ExternalNotificationTargetUpdate
from service_notifications.targets_service import (
    create_target,
    list_targets,
    send_notification_target_test,
    update_target,
)
from service_notifications.validators import validate_and_normalize_config, validate_subscribed_event_types
from shared_python.errors import BadRequestError, NotFoundError


def _user(*, uid: uuid.UUID | None = None) -> UserRead:
    return UserRead(
        id=uid or uuid.uuid4(),
        username="u1",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


def test_validate_email_config() -> None:
    c = validate_and_normalize_config(
        target_type="email",
        config={"recipient_email": "a@b.co", "subject_prefix": "[Platform]"},
    )
    assert c["recipient_email"] == "a@b.co"


def test_validate_email_rejects_invalid() -> None:
    with pytest.raises(ValueError):
        validate_and_normalize_config(target_type="email", config={"recipient_email": "not-an-email"})


def test_validate_slack_requires_https() -> None:
    with pytest.raises(ValueError):
        validate_and_normalize_config(
            target_type="slack_webhook",
            config={"webhook_url": "http://hooks.slack.com/services/x"},
        )


def test_validate_slack_ok() -> None:
    c = validate_and_normalize_config(
        target_type="slack_webhook",
        config={"webhook_url": "https://hooks.slack.com/services/T/B/xxxxx", "channel_label": "ops"},
    )
    assert c["webhook_url"].startswith("https://")


def test_subscribed_events() -> None:
    assert validate_subscribed_event_types(["schedule_run_failed", "schedule_run_failed"]) == ["schedule_run_failed"]


def test_subscribed_events_unknown() -> None:
    with pytest.raises(ValueError):
        validate_subscribed_event_types(["unknown_event"])


def test_redact_slack_url() -> None:
    r = redact_config_for_api(
        target_type="slack_webhook",
        config={"webhook_url": "https://hooks.slack.com/services/T000/B000/SECRETTOKEN"},
    )
    assert "SECRETTOKEN" not in r["webhook_url"]
    assert "hooks.slack.com" in r["webhook_url"]


def test_redact_email() -> None:
    r = redact_config_for_api(
        target_type="email",
        config={"recipient_email": "alice@example.com"},
    )
    assert "alice" not in r["recipient_email"] or "***" in r["recipient_email"]


@patch("service_notifications.targets_service.ensure_owned_project")
def test_create_list_target(mock_ensure: MagicMock) -> None:
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    row = MagicMock()
    row.id = uuid.uuid4()
    row.project_id = pid
    row.name = "Email ops"
    row.target_type = "email"
    row.enabled = True
    row.config_json = {"recipient_email": "ops@example.com"}
    row.subscribed_event_types_json = ["dataset_publish_failed"]
    row.created_by_user_id = uid
    row.created_at = datetime.now(UTC)
    row.updated_at = datetime.now(UTC)
    db = MagicMock()
    sc = MagicMock()
    sc.all.return_value = [row]
    db.scalars.return_value = sc

    out = list_targets(db, project_id=pid, current_user=_user(uid=uid))
    assert len(out.items) == 1
    assert out.items[0].name == "Email ops"
    mock_ensure.assert_called_once()


@patch("service_notifications.targets_service._to_read")
@patch("service_notifications.targets_service.ensure_owned_project")
@patch("service_notifications.targets_service.ExternalNotificationTarget")
def test_create_persists(mock_model: MagicMock, mock_ensure: MagicMock, mock_to_read: MagicMock) -> None:
    pid = uuid.uuid4()
    uid = uuid.uuid4()
    inst = MagicMock()
    mock_model.return_value = inst
    mock_to_read.return_value = MagicMock()
    db = MagicMock()
    payload = ExternalNotificationTargetCreate(
        name="Slack",
        target_type="slack_webhook",
        enabled=True,
        config_json={"webhook_url": "https://hooks.slack.com/services/T/B/x"},
        subscribed_event_types=["transformation_run_succeeded"],
    )
    create_target(db, project_id=pid, current_user=_user(uid=uid), payload=payload)
    db.add.assert_called_once_with(inst)
    db.commit.assert_called_once()
    mock_to_read.assert_called_once()
    stored = mock_model.call_args.kwargs["config_json"]
    assert stored["webhook_url"].startswith("enc:v1:")


@patch("service_notifications.targets_service._to_read")
@patch("service_notifications.targets_service.ensure_owned_project")
def test_update_slack_preserves_masked_webhook(mock_ensure: MagicMock, mock_to_read: MagicMock) -> None:
    pid = uuid.uuid4()
    tid = uuid.uuid4()
    uid = uuid.uuid4()
    row = MagicMock()
    row.id = tid
    row.project_id = pid
    row.target_type = "slack_webhook"
    row.name = "Slack"
    row.enabled = True
    row.subscribed_event_types_json = ["schedule_run_failed"]
    row.config_json = persist_notification_target_config_at_rest(
        "slack_webhook",
        {"webhook_url": "https://hooks.slack.com/services/T/B/SECRETTOKEN", "channel_label": "c1"},
    )
    db = MagicMock()
    db.get.return_value = row
    mock_to_read.return_value = MagicMock()
    update_target(
        db,
        project_id=pid,
        target_id=tid,
        current_user=_user(uid=uid),
        payload=ExternalNotificationTargetUpdate(config_json={"webhook_url": "***", "channel_label": "c2"}),
    )
    plain = notification_target_config_for_internal_use("slack_webhook", row.config_json)
    assert "SECRETTOKEN" in plain["webhook_url"]
    assert plain["channel_label"] == "c2"


@patch("service_notifications.targets_service.ensure_owned_project")
def test_update_not_found(mock_ensure: MagicMock) -> None:
    db = MagicMock()
    db.get.return_value = None
    with pytest.raises(NotFoundError):
        update_target(
            db,
            project_id=uuid.uuid4(),
            target_id=uuid.uuid4(),
            current_user=_user(),
            payload=ExternalNotificationTargetUpdate(name="x"),
        )


@patch("service_notifications.targets_service.send_slack_test_message")
@patch("service_notifications.targets_service.ensure_owned_project")
def test_test_slack_success(mock_ensure: MagicMock, mock_send: MagicMock) -> None:
    mock_send.return_value = (True, "ok")
    tid = uuid.uuid4()
    pid = uuid.uuid4()
    row = MagicMock()
    row.project_id = pid
    row.target_type = "slack_webhook"
    row.config_json = {"webhook_url": "https://hooks.slack.com/services/T/B/x"}
    db = MagicMock()
    db.get.return_value = row
    res = send_notification_target_test(db, project_id=pid, target_id=tid, current_user=_user())
    assert res.success is True
    mock_send.assert_called_once()


@patch("service_notifications.targets_service.send_email_test_message")
@patch("service_notifications.targets_service.ensure_owned_project")
def test_test_email_failure(mock_ensure: MagicMock, mock_send: MagicMock) -> None:
    mock_send.return_value = (False, "SMTP not configured")
    tid = uuid.uuid4()
    pid = uuid.uuid4()
    row = MagicMock()
    row.project_id = pid
    row.target_type = "email"
    row.config_json = {"recipient_email": "a@b.co"}
    db = MagicMock()
    db.get.return_value = row
    res = send_notification_target_test(db, project_id=pid, target_id=tid, current_user=_user())
    assert res.success is False
    assert "SMTP" in res.message


@patch("service_notifications.external_dispatch.send_slack_event_message")
@patch("service_notifications.external_dispatch.send_email_event_message")
def test_dispatch_calls_matching_targets(mock_email: MagicMock, mock_slack: MagicMock) -> None:
    mock_email.return_value = (True, "sent")
    mock_slack.return_value = (True, "sent")
    pid = uuid.uuid4()
    e1 = MagicMock()
    e1.id = uuid.uuid4()
    e1.project_id = pid
    e1.name = "e"
    e1.target_type = "email"
    e1.enabled = True
    e1.config_json = {"recipient_email": "a@b.co"}
    e1.subscribed_event_types_json = ["schedule_run_failed"]
    e2 = MagicMock()
    e2.id = uuid.uuid4()
    e2.project_id = pid
    e2.name = "s"
    e2.target_type = "slack_webhook"
    e2.enabled = True
    e2.config_json = persist_notification_target_config_at_rest(
        "slack_webhook",
        {"webhook_url": "https://hooks.slack.com/services/T/B/x"},
    )
    e2.subscribed_event_types_json = ["dataset_publish_succeeded"]
    db = MagicMock()
    sc = MagicMock()
    sc.all.return_value = [e1, e2]
    db.scalars.return_value = sc

    dispatch_external_notifications(
        db,
        project_id=pid,
        event_type="schedule_run_failed",
        title="t",
        message="m",
        level="error",
    )
    mock_email.assert_called_once()
    mock_slack.assert_not_called()


@patch("service_notifications.external_dispatch.send_slack_event_message")
def test_dispatch_decrypts_slack_config(mock_slack: MagicMock) -> None:
    mock_slack.return_value = (True, "sent")
    pid = uuid.uuid4()
    e2 = MagicMock()
    e2.id = uuid.uuid4()
    e2.project_id = pid
    e2.name = "s"
    e2.target_type = "slack_webhook"
    e2.enabled = True
    e2.config_json = persist_notification_target_config_at_rest(
        "slack_webhook",
        {"webhook_url": "https://hooks.slack.com/services/T/B/xyzzy"},
    )
    e2.subscribed_event_types_json = ["dataset_publish_succeeded"]
    db = MagicMock()
    sc = MagicMock()
    sc.all.return_value = [e2]
    db.scalars.return_value = sc
    dispatch_external_notifications(
        db,
        project_id=pid,
        event_type="dataset_publish_succeeded",
        title="t",
        message="m",
        level="info",
    )
    mock_slack.assert_called_once()
    cfg = mock_slack.call_args.kwargs["config"]
    assert cfg["webhook_url"] == "https://hooks.slack.com/services/T/B/xyzzy"


@patch("service_notifications.external_dispatch.send_email_event_message")
def test_dispatch_email_failure_logged(mock_email: MagicMock) -> None:
    mock_email.return_value = (False, "fail")
    pid = uuid.uuid4()
    e1 = MagicMock()
    e1.id = uuid.uuid4()
    e1.target_type = "email"
    e1.enabled = True
    e1.config_json = {"recipient_email": "a@b.co"}
    e1.subscribed_event_types_json = ["schedule_run_failed"]
    db = MagicMock()
    sc = MagicMock()
    sc.all.return_value = [e1]
    db.scalars.return_value = sc
    dispatch_external_notifications(
        db,
        project_id=pid,
        event_type="schedule_run_failed",
        title="t",
        message="m",
        level="error",
    )


@patch("service_notifications.outcomes.dispatch_external_notifications")
@patch("service_notifications.outcomes.create_user_notification")
def test_persist_notification_fanout(mock_create: MagicMock, mock_fanout: MagicMock) -> None:
    db = MagicMock()
    pid = uuid.uuid4()
    _persist_notification(
        db,
        user_id=uuid.uuid4(),
        project_id=pid,
        type="transformation_run_failed",
        level="error",
        title="T",
        message="M",
    )
    mock_create.assert_called_once()
    mock_fanout.assert_called_once()


@patch("service_notifications.outcomes.dispatch_external_notifications")
@patch("service_notifications.outcomes.create_user_notification")
def test_persist_external_failure_does_not_raise(mock_create: MagicMock, mock_fanout: MagicMock) -> None:
    mock_fanout.side_effect = RuntimeError("boom")
    db = MagicMock()
    pid = uuid.uuid4()
    _persist_notification(
        db,
        user_id=uuid.uuid4(),
        project_id=pid,
        type="transformation_run_failed",
        level="error",
        title="T",
        message="M",
    )
    mock_create.assert_called_once()


@patch("service_notifications.senders.slack_sender.httpx.Client")
def test_slack_sender_success(mock_client_cls: MagicMock) -> None:
    from service_notifications.senders.slack_sender import send_slack_test_message

    resp = MagicMock()
    resp.status_code = 200
    client = MagicMock()
    client.post.return_value = resp
    mock_client_cls.return_value.__enter__.return_value = client

    ok, msg = send_slack_test_message(config={"webhook_url": "https://hooks.slack.com/services/T/B/x"})
    assert ok is True
    client.post.assert_called_once()


@patch("service_notifications.senders.slack_sender.httpx.Client")
def test_slack_sender_http_error(mock_client_cls: MagicMock) -> None:
    from service_notifications.senders.slack_sender import send_slack_test_message

    import httpx

    mock_client_cls.return_value.__enter__.side_effect = httpx.ConnectError("nope")

    ok, msg = send_slack_test_message(config={"webhook_url": "https://hooks.slack.com/services/T/B/x"})
    assert ok is False


@patch("service_notifications.senders.email_sender.smtp_configured")
def test_email_sender_not_configured(mock_cfg: MagicMock) -> None:
    from service_notifications.senders.email_sender import send_email_test_message

    mock_cfg.return_value = False
    ok, msg = send_email_test_message(config={"recipient_email": "a@b.co"})
    assert ok is False
    assert "SMTP" in msg


@patch("service_notifications.senders.email_sender.smtplib.SMTP")
@patch("service_notifications.senders.email_sender.smtp_configured")
@patch("service_notifications.senders.email_sender.get_smtp_settings")
def test_email_sender_success(mock_gs: MagicMock, mock_cfg: MagicMock, mock_smtp: MagicMock) -> None:
    from service_notifications.senders.email_sender import send_email_test_message

    mock_cfg.return_value = True
    mock_gs.return_value = {
        "host": "smtp.example.com",
        "port": 587,
        "user": "u",
        "password": "p",
        "use_tls": True,
        "default_from": "from@example.com",
    }
    ctx = MagicMock()
    mock_smtp.return_value.__enter__.return_value = ctx

    ok, msg = send_email_test_message(config={"recipient_email": "a@b.co"})
    assert ok is True
    ctx.send_message.assert_called_once()


@patch("service_notifications.targets_service.ensure_owned_project")
def test_create_invalid_payload(mock_ensure: MagicMock) -> None:
    db = MagicMock()
    with pytest.raises(BadRequestError):
        create_target(
            db,
            project_id=uuid.uuid4(),
            current_user=_user(),
            payload=ExternalNotificationTargetCreate(
                name="x",
                target_type="email",
                config_json={},
                subscribed_event_types=["schedule_run_failed"],
            ),
        )
