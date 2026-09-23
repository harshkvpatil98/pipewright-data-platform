"""Getting a generated report to the people who asked for it.

Generation and delivery are different facts. A report can be produced
perfectly and still not arrive -- SMTP down, a webhook revoked, no address on
file -- and the delivery record has to say which happened. So every channel a
report is configured for is attempted independently and recorded by outcome:

* **in-app** -- the creator's bell, always;
* **the notification target** the report names (a Slack webhook gets a message
  with a link; an email target gets the file attached);
* **each recipient address** -- the file attached, one message per person, so
  one bad address does not stop the others.

Nothing here raises: a delivery failure is written into the delivery row and
summarised in its message. The senders are module attributes so a test can
swap them without a network.
"""

from __future__ import annotations

import os
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_notifications.at_rest_config import notification_target_config_for_internal_use
from service_notifications.constants import EXTERNAL_TARGET_EMAIL, EXTERNAL_TARGET_SLACK_WEBHOOK
from service_notifications.models import ExternalNotificationTarget
from service_notifications.senders import email_sender as _email
from service_notifications.senders import slack_sender as _slack
from service_notifications.service import create_user_notification
from shared_python.logging import get_logger

logger = get_logger(__name__)

#: Kept as module attributes on purpose: tests replace them, production leaves
#: them alone.
send_email = _email.send_plain_email
post_slack = _slack._post_webhook  # noqa: SLF001 - the webhook primitive is what a report needs


def web_base_url() -> str:
    """The public web address, for links in messages. The same setting the
    gateway reads (`WEB_BASE_URL`); read here directly so the worker, which has
    no request, can build links too."""
    return os.getenv("WEB_BASE_URL", "").strip().rstrip("/")


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.0f} KB"
    return f"{size / (1024 * 1024):.1f} MB"


def resolve_target(
    db: Session, *, project_id, target_id
) -> ExternalNotificationTarget | None:
    """A notification target of THIS project, or None. A report must not be able
    to post into another project's channel."""
    if target_id is None:
        return None
    return db.scalar(
        select(ExternalNotificationTarget).where(
            ExternalNotificationTarget.id == target_id,
            ExternalNotificationTarget.project_id == project_id,
        )
    )


def deliver_report(
    db: Session,
    *,
    report,
    filename: str,
    content: bytes,
    media_type: str,
    row_count: int,
) -> tuple[list[dict[str, Any]], str]:
    """Attempt every configured channel. Returns (per-channel outcomes, a
    one-line summary for the delivery record)."""
    channels: list[dict[str, Any]] = []
    link = (
        f"{web_base_url()}/projects/{report.project_id}/reports" if web_base_url() else ""
    )
    size = _human_size(len(content))
    headline = f"{report.name} is ready"
    detail = f"{filename} — {row_count:,} row(s), {size}."
    body = detail + (f"\n\nOpen the reports page: {link}" if link else "")

    # 1. In-app, for the person who set it up.
    if report.created_by_user_id is not None:
        try:
            create_user_notification(
                db,
                user_id=report.created_by_user_id,
                project_id=report.project_id,
                type="report",
                level="info",
                title=headline,
                message=detail,
            )
            channels.append({"channel": "in_app", "ok": True, "detail": "notified the report's owner"})
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            logger.exception("report_in_app_notify_failed report_id=%s", report.id)
            channels.append({"channel": "in_app", "ok": False, "detail": str(exc)[:300]})

    # 2. The named notification target.
    target = resolve_target(
        db, project_id=report.project_id, target_id=getattr(report, "notification_target_id", None)
    )
    if getattr(report, "notification_target_id", None) is not None and target is None:
        channels.append({"channel": "target", "ok": False, "detail": "the notification target no longer exists"})
    elif target is not None and not target.enabled:
        channels.append({"channel": target.target_type, "target": target.name, "ok": False,
                         "detail": "the notification target is disabled"})
    elif target is not None:
        try:
            config = notification_target_config_for_internal_use(
                target.target_type, target.config_json if isinstance(target.config_json, dict) else {}
            )
            if target.target_type == EXTERNAL_TARGET_SLACK_WEBHOOK:
                label = config.get("channel_label")
                prefix = f"[{label}] " if isinstance(label, str) and label.strip() else ""
                ok, reason = post_slack(
                    config=config,
                    text=f"{prefix}*{headline}*\n{detail}" + (f"\n<{link}|Open the reports page>" if link else ""),
                )
                channels.append({"channel": "slack", "target": target.name, "ok": ok, "detail": reason})
            elif target.target_type == EXTERNAL_TARGET_EMAIL:
                ok, reason = send_email(
                    to=str(config.get("recipient_email") or ""),
                    subject=headline,
                    body=body,
                    sender=config.get("sender_email"),
                    attachments=[(filename, content, media_type)],
                )
                channels.append({"channel": "email", "target": target.name, "ok": ok, "detail": reason})
            else:
                channels.append({"channel": target.target_type, "target": target.name, "ok": False,
                                 "detail": "this target type cannot carry a report"})
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            logger.exception("report_target_delivery_failed report_id=%s", report.id)
            channels.append({"channel": target.target_type, "target": target.name, "ok": False,
                             "detail": str(exc)[:300]})

    # 3. Each recipient address, independently.
    for address in list(getattr(report, "recipients_json", None) or []):
        try:
            ok, reason = send_email(
                to=str(address), subject=headline, body=body,
                attachments=[(filename, content, media_type)],
            )
        except Exception as exc:  # noqa: BLE001 - recorded, never raised
            ok, reason = False, str(exc)[:300]
        channels.append({"channel": "email", "recipient": str(address), "ok": ok, "detail": reason})

    return channels, summarise(channels, row_count)


def summarise(channels: list[dict[str, Any]], row_count: int) -> str:
    """"12 rows. Slack: posted · email: 2 sent, 1 failed" -- the truth, short."""
    parts = [f"{row_count:,} row(s)."]
    slack = [c for c in channels if c["channel"] == "slack"]
    if slack:
        parts.append("Slack: " + ("posted" if all(c["ok"] for c in slack) else "failed"))
    emails = [c for c in channels if c["channel"] == "email"]
    if emails:
        sent = sum(1 for c in emails if c["ok"])
        failed = len(emails) - sent
        text = f"email: {sent} sent"
        if failed:
            text += f", {failed} failed"
        parts.append(text)
    broken = [c for c in channels if c["channel"] == "target" or (not c["ok"] and c["channel"] not in {"slack", "email", "in_app"})]
    if broken:
        parts.append("target: " + broken[0]["detail"])
    return " · ".join(parts)
