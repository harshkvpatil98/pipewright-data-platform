"""Emailed invitations and reset codes (P8).

When the server can send mail and the person has an address, the code goes to
them and the admin never sees it. When it cannot -- no sender configured, no
address, or the send fails -- the code comes back to the admin as before and
nothing is silently dropped.
"""

from __future__ import annotations

import uuid

from service_auth.models import User
from service_auth.service import deliver_one_time_code, mask_email


def _user(email: str | None) -> User:
    return User(id=uuid.uuid4(), username="ada", password_hash="x", role="viewer",
                is_active=False, email=email, display_name="Ada L.")


class _Sender:
    def __init__(self, ok: bool = True, raise_instead: bool = False) -> None:
        self.ok = ok
        self.raise_instead = raise_instead
        self.calls: list[dict] = []

    def __call__(self, *, to: str, subject: str, body: str):
        self.calls.append({"to": to, "subject": subject, "body": body})
        if self.raise_instead:
            raise OSError("smtp down")
        return (True, "Email sent.") if self.ok else (False, "SMTP error: refused")


def test_an_emailed_code_never_reaches_the_admin():
    sender = _Sender()
    result = deliver_one_time_code(
        user=_user("ada@acme.com"), code="ABCDEFGH", purpose="activation",
        expires_in_minutes=30, web_base_url="https://pw.example/", email_sender=sender,
    )
    assert result.emailed is True and result.code is None
    assert result.emailed_to == "a***@acme.com"
    [call] = sender.calls
    assert call["to"] == "ada@acme.com"
    assert "invited" in call["subject"].lower()
    # The link carries the code and lands on the sign-in page's redeem form.
    assert "https://pw.example/login?code=ABCDEFGH" in call["body"]
    assert "Username: ada" in call["body"]
    assert "30 minutes" in call["body"]


def test_without_a_sender_or_an_address_the_code_is_returned():
    no_sender = deliver_one_time_code(
        user=_user("ada@acme.com"), code="C1", purpose="reset",
        expires_in_minutes=30, web_base_url="http://x", email_sender=None,
    )
    assert no_sender.code == "C1" and no_sender.emailed is False and no_sender.email_error is None
    no_address = deliver_one_time_code(
        user=_user(None), code="C2", purpose="reset",
        expires_in_minutes=30, web_base_url="http://x", email_sender=_Sender(),
    )
    assert no_address.code == "C2" and no_address.emailed is False


def test_a_failed_send_returns_the_code_and_says_why():
    sender = _Sender(ok=False)
    result = deliver_one_time_code(
        user=_user("ada@acme.com"), code="C3", purpose="reset",
        expires_in_minutes=30, web_base_url="http://x", email_sender=sender,
    )
    assert result.code == "C3" and result.emailed is False
    assert result.email_error == "SMTP error: refused"
    assert "Reset your" in sender.calls[0]["subject"]


def test_a_sender_that_raises_cannot_lose_the_code():
    result = deliver_one_time_code(
        user=_user("ada@acme.com"), code="C4", purpose="activation",
        expires_in_minutes=30, web_base_url="http://x", email_sender=_Sender(raise_instead=True),
    )
    assert result.code == "C4" and result.emailed is False
    assert "smtp down" in (result.email_error or "")


def test_mask_email_keeps_the_domain_and_one_letter():
    assert mask_email("alice@acme.com") == "a***@acme.com"
    assert mask_email("nonsense") == "***"
