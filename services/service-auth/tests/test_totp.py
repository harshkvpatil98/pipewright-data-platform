"""TOTP against RFC 6238's own test vectors.

The one security primitive here is worth pinning to the standard directly: if
our HMAC-SHA1 truncation drifts from the RFC, every authenticator app in the
world computes a different code and MFA silently stops working. These are the
RFC 6238 Appendix B vectors (SHA-1), truncated to the six digits we issue.
"""

from __future__ import annotations

import base64

from service_auth import totp

# RFC 6238 secret: ASCII "12345678901234567890".
SECRET = base64.b32encode(b"12345678901234567890").decode().rstrip("=")

# {unix_time: 8-digit code from the RFC}; we compare the last six digits.
VECTORS = {
    59: "94287082",
    1111111109: "07081804",
    1111111111: "14050471",
    1234567890: "89005924",
    2000000000: "69279037",
}


def test_matches_rfc_6238_vectors() -> None:
    for timestamp, eight in VECTORS.items():
        assert totp.code_at(SECRET, timestamp=timestamp) == eight[-6:], timestamp


def test_verify_accepts_the_current_code() -> None:
    code = totp.code_at(SECRET, timestamp=1234567890)
    assert totp.verify(SECRET, code, timestamp=1234567890) is True


def test_verify_accepts_an_adjacent_step_for_clock_skew() -> None:
    prev = totp.code_at(SECRET, timestamp=1234567890 - 30)
    assert totp.verify(SECRET, prev, timestamp=1234567890) is True


def test_verify_rejects_a_far_off_code_and_junk() -> None:
    two_ago = totp.code_at(SECRET, timestamp=1234567890 - 90)
    assert totp.verify(SECRET, two_ago, timestamp=1234567890) is False
    assert totp.verify(SECRET, "not-a-code", timestamp=1234567890) is False
    assert totp.verify(SECRET, "", timestamp=1234567890) is False


def test_generated_secrets_are_distinct_and_usable() -> None:
    a, b = totp.generate_secret(), totp.generate_secret()
    assert a != b
    code = totp.code_at(a, timestamp=1234567890)
    assert totp.verify(a, code, timestamp=1234567890) is True


def test_provisioning_uri_carries_issuer_and_secret() -> None:
    uri = totp.provisioning_uri(SECRET, account_name="alice@acme.com", issuer="Pipewright")
    assert uri.startswith("otpauth://totp/")
    assert f"secret={SECRET}" in uri
    assert "issuer=Pipewright" in uri
