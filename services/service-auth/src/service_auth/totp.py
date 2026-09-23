"""Time-based one-time passwords (RFC 6238), with no third-party dependency.

TOTP is small and exact enough to implement directly rather than pull in a
library for: it is an HMAC of the time-step, truncated to six digits. Doing it
here keeps the one security primitive that guards second-factor login inside
code we can read and test against the RFC's own vectors, rather than trusting a
transitive dependency nobody audits.

The shared secret is base32 (what authenticator apps expect). Verification
accepts a small window of adjacent steps so a clock a few seconds off, or a
code typed as it rolls over, still works -- without widening it into a barn
door.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from urllib.parse import quote

#: 30-second steps and 6 digits are the near-universal authenticator defaults;
#: choosing anything else just breaks Google Authenticator and its clones.
STEP_SECONDS = 30
DIGITS = 6
#: How many steps either side of "now" a code is accepted. One step (±30s)
#: covers clock skew and the type-as-it-rolls case; more would weaken it.
DEFAULT_WINDOW = 1


def generate_secret(length: int = 20) -> str:
    """A fresh base32 secret. 20 bytes = 160 bits, the RFC 4226 recommendation."""
    return base64.b32encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def _b32decode(secret: str) -> bytes:
    # Authenticator secrets are shown without padding and often lower-cased;
    # normalise before decoding so a hand-typed secret still works.
    cleaned = secret.strip().replace(" ", "").upper()
    padding = "=" * (-len(cleaned) % 8)
    return base64.b32decode(cleaned + padding)


def _code_for_counter(secret: str, counter: int, digits: int = DIGITS) -> str:
    key = _b32decode(secret)
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(binary % (10**digits)).zfill(digits)


def code_at(secret: str, *, timestamp: int, digits: int = DIGITS, step: int = STEP_SECONDS) -> str:
    """The code for a given unix time -- the seam tests inject a fixed clock at."""
    return _code_for_counter(secret, timestamp // step, digits)


def verify(
    secret: str,
    code: str,
    *,
    timestamp: int,
    window: int = DEFAULT_WINDOW,
    digits: int = DIGITS,
    step: int = STEP_SECONDS,
) -> bool:
    """True if `code` matches within +/- `window` steps. Constant-time compared,
    and a malformed code is simply false rather than an error."""
    candidate = (code or "").strip().replace(" ", "")
    if not candidate.isdigit() or len(candidate) != digits:
        return False
    counter = timestamp // step
    for drift in range(-window, window + 1):
        expected = _code_for_counter(secret, counter + drift, digits)
        if hmac.compare_digest(expected, candidate):
            return True
    return False


def provisioning_uri(secret: str, *, account_name: str, issuer: str) -> str:
    """The otpauth:// URI an authenticator app scans (or is fed by hand)."""
    label = quote(f"{issuer}:{account_name}")
    params = (
        f"secret={secret}"
        f"&issuer={quote(issuer)}"
        f"&algorithm=SHA1&digits={DIGITS}&period={STEP_SECONDS}"
    )
    return f"otpauth://totp/{label}?{params}"


def qr_svg(uri: str) -> str:
    """An inline SVG QR code for a provisioning URI, so enrolment is a scan.

    segno is pure Python (no native library), so this adds no build step; the
    SVG is returned as a string the client drops straight into the page.
    """
    import io

    import segno

    buffer = io.BytesIO()
    # Bake black-on-white into the SVG so it scans on any page background,
    # light or dark, without the page needing a raw white container behind it.
    segno.make(uri, error="m").save(
        buffer, kind="svg", scale=5, border=2, xmldecl=False, dark="#000000", light="#ffffff"
    )
    return buffer.getvalue().decode("utf-8")
