"""The one email primitive every mail path shares."""

from __future__ import annotations

from service_notifications.senders.email_sender import email_configured, send_plain_email


def test_without_smtp_the_answer_is_a_sentence_not_an_exception(monkeypatch):
    monkeypatch.delenv("EXTERNAL_NOTIFICATION_SMTP_HOST", raising=False)
    ok, reason = send_plain_email(to="a@b.c", subject="s", body="b")
    assert ok is False and "SMTP is not configured" in reason
    assert email_configured() is False


def test_a_bad_recipient_is_refused_before_any_connection(monkeypatch):
    monkeypatch.setenv("EXTERNAL_NOTIFICATION_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("EXTERNAL_NOTIFICATION_SMTP_FROM", "noreply@example")
    ok, reason = send_plain_email(to="not-an-address", subject="s", body="b")
    assert ok is False and reason == "Invalid recipient."
    assert email_configured() is True


def test_attachments_are_built_into_the_message(monkeypatch):
    """Capture the message at the SMTP boundary and check the attachment rode
    along with the right name and type -- the report path depends on it."""
    import smtplib

    sent: list = []

    class _SMTP:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def starttls(self):
            pass

        def login(self, *args):
            pass

        def send_message(self, msg):
            sent.append(msg)

    monkeypatch.setattr(smtplib, "SMTP", _SMTP)
    monkeypatch.setenv("EXTERNAL_NOTIFICATION_SMTP_HOST", "smtp.example")
    monkeypatch.setenv("EXTERNAL_NOTIFICATION_SMTP_FROM", "noreply@example")
    ok, _ = send_plain_email(
        to="a@b.c", subject="Weekly", body="attached",
        attachments=[("weekly.csv", b"a,b\n1,2\n", "text/csv")],
    )
    assert ok is True
    [msg] = sent
    parts = [part for part in msg.iter_attachments()]
    assert [p.get_filename() for p in parts] == ["weekly.csv"]
    assert parts[0].get_content_type() == "text/csv"
    assert parts[0].get_payload(decode=True) == b"a,b\n1,2\n"
