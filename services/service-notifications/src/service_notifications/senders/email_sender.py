from __future__ import annotations

import smtplib
from email.message import EmailMessage
from typing import Any

from service_notifications.senders.smtp_settings import get_smtp_settings, smtp_configured


def send_email_test_message(*, config: dict[str, Any]) -> tuple[bool, str]:
    subject = "Platform notification test"
    body = "This is a test message from the Pipewright external notification target."
    return _send_email(config=config, subject=subject, body=body)


def send_email_event_message(
    *,
    config: dict[str, Any],
    title: str,
    message: str,
    level: str,
    event_type: str,
) -> tuple[bool, str]:
    prefix = (config.get("subject_prefix") or "").strip()
    subject = f"{prefix} [{level.upper()}] {title}" if prefix else f"[{level.upper()}] {title}"
    body = f"Event: {event_type}\n\n{message}"
    return _send_email(config=config, subject=subject[:900], body=body)


def _send_email(*, config: dict[str, Any], subject: str, body: str) -> tuple[bool, str]:
    recipient = config.get("recipient_email")
    if not isinstance(recipient, str) or not recipient.strip():
        return False, "Invalid recipient."
    return send_plain_email(
        to=recipient, subject=subject, body=body, sender=config.get("sender_email")
    )


def email_configured() -> bool:
    """Can this server send mail at all? The invite and report paths ask before
    promising anything."""
    return smtp_configured() and bool(get_smtp_settings()["default_from"])


def send_plain_email(
    *,
    to: str,
    subject: str,
    body: str,
    sender: str | None = None,
    attachments: list[tuple[str, bytes, str]] | None = None,
) -> tuple[bool, str]:
    """Send one message through the configured SMTP server.

    The one email primitive: notification targets, invitations and report
    deliveries all go through here, so there is a single place that knows the
    server, the retry story and the failure sentences. `attachments` are
    `(filename, bytes, media_type)` triples. Returns (ok, human sentence) and
    never raises -- a mail failure is reported to the caller, not thrown at it.
    """
    if not smtp_configured():
        return False, "SMTP is not configured on the server (set EXTERNAL_NOTIFICATION_SMTP_HOST)."
    if not isinstance(to, str) or "@" not in to:
        return False, "Invalid recipient."

    smtp = get_smtp_settings()
    mail_from = sender or smtp["default_from"]
    if not mail_from:
        return False, "No sender address (set sender_email on the target or EXTERNAL_NOTIFICATION_SMTP_FROM)."

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = mail_from
    msg["To"] = to
    msg.set_content(body)
    for filename, payload, media_type in attachments or []:
        maintype, _, subtype = (media_type or "application/octet-stream").partition("/")
        msg.add_attachment(payload, maintype=maintype, subtype=subtype or "octet-stream", filename=filename)

    host = smtp["host"]
    port = int(smtp["port"])
    use_tls = bool(smtp["use_tls"])
    user = smtp["user"]
    password = smtp["password"]

    try:
        if use_tls:
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls()
                if user and password is not None:
                    server.login(user, str(password))
                server.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as server:
                if user and password is not None:
                    server.login(user, str(password))
                server.send_message(msg)
    except OSError as e:
        return False, f"SMTP error: {e}"
    except smtplib.SMTPException as e:
        return False, f"SMTP error: {e}"

    return True, "Email sent."
