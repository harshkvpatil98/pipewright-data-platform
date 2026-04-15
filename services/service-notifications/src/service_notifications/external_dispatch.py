from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from service_notifications.at_rest_config import notification_target_config_for_internal_use
from service_notifications.constants import EXTERNAL_TARGET_EMAIL, EXTERNAL_TARGET_SLACK_WEBHOOK
from service_notifications.models import ExternalNotificationTarget
from service_notifications.senders.email_sender import send_email_event_message
from service_notifications.senders.slack_sender import send_slack_event_message
from shared_python.logging import get_logger

logger = get_logger(__name__)


def dispatch_external_notifications(
    db: Session,
    *,
    project_id: uuid.UUID,
    event_type: str,
    title: str,
    message: str,
    level: str,
) -> None:
    """Best-effort fan-out to enabled external targets. Must not raise."""
    try:
        stmt = select(ExternalNotificationTarget).where(
            and_(
                ExternalNotificationTarget.project_id == project_id,
                ExternalNotificationTarget.enabled.is_(True),
            )
        )
        rows = db.scalars(stmt).all()
        for row in rows:
            try:
                subscribed = row.subscribed_event_types_json
                if not isinstance(subscribed, list) or event_type not in subscribed:
                    continue
                raw_cfg: dict[str, Any] = row.config_json if isinstance(row.config_json, dict) else {}
                try:
                    cfg = notification_target_config_for_internal_use(row.target_type, raw_cfg)
                except Exception:
                    logger.exception("external_target_decrypt_failed", extra={"target_id": str(row.id)})
                    continue
                if row.target_type == EXTERNAL_TARGET_EMAIL:
                    ok, _msg = send_email_event_message(
                        config=cfg,
                        title=title,
                        message=message,
                        level=level,
                        event_type=event_type,
                    )
                    if not ok:
                        logger.warning("external_email_dispatch_failed", extra={"target_id": str(row.id)})
                elif row.target_type == EXTERNAL_TARGET_SLACK_WEBHOOK:
                    ok, _msg = send_slack_event_message(
                        config=cfg,
                        title=title,
                        message=message,
                        level=level,
                        event_type=event_type,
                    )
                    if not ok:
                        logger.warning("external_slack_dispatch_failed", extra={"target_id": str(row.id)})
            except Exception:
                logger.exception("external_target_dispatch_failed", extra={"target_id": str(row.id)})
    except Exception:
        logger.exception("external_notification_fanout_query_failed")
