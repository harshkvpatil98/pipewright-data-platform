"""Signed webhooks: JSON to a partner's address, every attempt recorded (A8).

A webhook target is an address that receives a POST for each event it
subscribes to. The body is JSON:

    {"id": "<delivery id>", "type": "workflow_run_failed", "occurred_at": "...",
     "project": {"id": "...", "name": "..."}, "title": "...", "message": "...",
     "level": "error"}

and the request carries `Pipewright-Signature: t=<unix seconds>,v1=<hex>`,
where v1 is HMAC-SHA256 over `"<t>." + body` with the target's signing
secret. A receiver recomputes it, compares in constant time, and refuses a
`t` more than five minutes old (`verify` here is the reference, and the API
guide shows the same in a few lines).

The first try is made at once with a short timeout; a timeout, a 5xx, a 408
or a 429 is tried twice more, a minute and then five minutes later, by the
background worker (`retry_due`). Any other 4xx means the receiver refused it
and is not repeated. Every address passes the outbound guard: never the cloud
metadata service, never this server unless loopback is allowed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.logging import get_logger
from shared_python.outbound import OutboundBlocked, httpx_request_guard

logger = get_logger(__name__)

SIGNATURE_HEADER = "Pipewright-Signature"
MAX_ATTEMPTS = 3
#: Seconds before the second and the third try.
RETRY_WAITS = (60, 300)
TIMEOUT_SECONDS = 5.0
TOLERANCE_SECONDS = 300
_RETRYABLE = {408, 429}


def new_secret() -> str:
    return "whsec_" + secrets.token_urlsafe(32)


def sign(secret: str, timestamp: int, body: bytes) -> str:
    return hmac.new(secret.encode(), f"{timestamp}.".encode() + body, hashlib.sha256).hexdigest()


def signature_header(secret: str, body: bytes, *, now: float | None = None) -> str:
    timestamp = int(now if now is not None else time.time())
    return f"t={timestamp},v1={sign(secret, timestamp, body)}"


def verify(secret: str, header: str, body: bytes, *, now: float | None = None,
           tolerance: int = TOLERANCE_SECONDS) -> bool:
    """What a receiver does: the reference implementation the guide follows."""
    try:
        parts = dict(item.split("=", 1) for item in header.split(","))
        timestamp = int(parts["t"])
        expected = sign(secret, timestamp, body)
        fresh = abs((now if now is not None else time.time()) - timestamp) <= tolerance
        return fresh and hmac.compare_digest(expected, parts.get("v1", ""))
    except (KeyError, ValueError):
        return False


def event_body(
    *, delivery_id: uuid.UUID, event_type: str, project_id: uuid.UUID, project_name: str | None,
    title: str, message: str, level: str, occurred_at: datetime | None = None,
) -> str:
    return json.dumps(
        {
            "id": str(delivery_id),
            "type": event_type,
            "occurred_at": (occurred_at or datetime.now(UTC)).isoformat(),
            "project": {"id": str(project_id), "name": project_name},
            "title": title,
            "message": message,
            "level": level,
        },
        separators=(",", ":"),
        ensure_ascii=False,
    )


def _post(url: str, secret: str, delivery_id: uuid.UUID, event_type: str, body: str) -> tuple[int | None, str | None]:
    """One try: (status code, error). A status of None means it never got an answer."""
    raw = body.encode()
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Pipewright-Webhooks/1",
        "Pipewright-Event": event_type,
        "Pipewright-Delivery": str(delivery_id),
        SIGNATURE_HEADER: signature_header(secret, raw),
    }
    try:
        with httpx.Client(timeout=TIMEOUT_SECONDS, event_hooks={"request": [httpx_request_guard]}) as client:
            response = client.post(url, content=raw, headers=headers)
    except OutboundBlocked as exc:
        return None, f"Refused: {exc}"
    except httpx.TimeoutException:
        return None, f"No answer within {TIMEOUT_SECONDS:.0f} seconds."
    except httpx.HTTPError as exc:
        return None, f"Could not connect: {type(exc).__name__}."
    if response.is_success:
        return response.status_code, None
    return response.status_code, f"The address answered {response.status_code}."


def attempt(db: Session, delivery: Any, *, url: str, secret: str) -> None:
    """Make the next try for `delivery` and record what happened."""
    from service_notifications.models import WebhookDelivery  # noqa: F401 - mapper registration

    status_code, error = _post(url, secret, delivery.id, delivery.event_type, delivery.body)
    now = datetime.now(UTC)
    delivery.attempts = int(delivery.attempts or 0) + 1
    delivery.last_status_code = status_code
    delivery.last_error = error
    if error is None:
        delivery.status, delivery.next_attempt_at, delivery.completed_at = "succeeded", None, now
        return
    refused = status_code is not None and 400 <= status_code < 500 and status_code not in _RETRYABLE
    blocked = error.startswith("Refused:")
    if refused or blocked or delivery.attempts >= MAX_ATTEMPTS:
        delivery.status, delivery.next_attempt_at, delivery.completed_at = "failed", None, now
        return
    delivery.status = "pending"
    delivery.next_attempt_at = now + timedelta(seconds=RETRY_WAITS[delivery.attempts - 1])


def deliver(
    db: Session, *, target: Any, config: dict[str, Any], event_type: str, title: str, message: str, level: str,
) -> Any:
    """Record and send one event to one webhook target, in its own transaction.

    A separate session, so the record stands whatever the caller's
    transaction does, and the caller's work is never committed by this.
    """
    from service_notifications.models import WebhookDelivery
    from service_projects.models import Project

    with Session(bind=db.get_bind()) as own:
        project = own.get(Project, target.project_id)
        delivery_id = uuid.uuid4()
        delivery = WebhookDelivery(
            id=delivery_id,
            target_id=target.id,
            project_id=target.project_id,
            event_type=event_type,
            body=event_body(
                delivery_id=delivery_id, event_type=event_type, project_id=target.project_id,
                project_name=project.name if project else None, title=title, message=message, level=level,
            ),
            status="pending",
            attempts=0,
        )
        own.add(delivery)
        own.flush()
        attempt(own, delivery, url=str(config.get("url") or ""), secret=str(config.get("signing_secret") or ""))
        own.commit()
        own.refresh(delivery)
        own.expunge(delivery)
        return delivery


def retry_due(db: Session, *, now: datetime | None = None, limit: int = 50) -> int:
    """Make the tries that are due. Run by the background worker. Returns how many."""
    from service_notifications.at_rest_config import notification_target_config_for_internal_use
    from service_notifications.models import ExternalNotificationTarget, WebhookDelivery

    moment = now or datetime.now(UTC)
    due = db.scalars(
        select(WebhookDelivery)
        .where(WebhookDelivery.status == "pending", WebhookDelivery.next_attempt_at <= moment)
        .order_by(WebhookDelivery.next_attempt_at)
        .limit(limit)
        .with_for_update(skip_locked=True)
    ).all()
    for delivery in due:
        target = db.get(ExternalNotificationTarget, delivery.target_id)
        if target is None or not target.enabled:
            delivery.status, delivery.next_attempt_at = "failed", None
            delivery.last_error = "The target was turned off before the next try."
            delivery.completed_at = moment
            continue
        try:
            config = notification_target_config_for_internal_use(target.target_type, dict(target.config_json or {}))
        except Exception:  # noqa: BLE001 - a key problem is recorded, not raised
            delivery.status, delivery.next_attempt_at = "failed", None
            delivery.last_error = "The target's saved settings could not be read."
            delivery.completed_at = moment
            continue
        attempt(db, delivery, url=str(config.get("url") or ""), secret=str(config.get("signing_secret") or ""))
    db.commit()
    return len(due)
