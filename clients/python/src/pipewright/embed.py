"""Sign an embedded dashboard's link on your own server (A8, Y4).

    from pipewright import embed_link

    src = embed_link(
        "https://pipewright.example.com", embed_id, secret,
        minutes=10, filters=[{"column": "customer_id", "value": customer.id}],
    )

The link is a JSON Web Token signed with HS256, so any language's JWT
library makes the same one; this needs nothing but the standard library.
Make one as each page loads: a short link that leaks is soon useless, and
the filters, fixed by the signature, show each customer only their rows.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _part(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def embed_token(embed_id: str, secret: str, *, minutes: float = 10, filters: list[dict[str, Any]] | None = None,
                now: float | None = None) -> str:
    claims: dict[str, Any] = {"embed": str(embed_id), "exp": int((now or time.time()) + minutes * 60)}
    if filters:
        claims["filters"] = filters
    head = _part(json.dumps({"alg": "HS256", "typ": "JWT"}, separators=(",", ":")).encode())
    body = _part(json.dumps(claims, separators=(",", ":")).encode())
    signature = hmac.new(secret.encode(), f"{head}.{body}".encode(), hashlib.sha256).digest()
    return f"{head}.{body}.{_part(signature)}"


def embed_link(url: str, embed_id: str, secret: str, *, minutes: float = 10,
               filters: list[dict[str, Any]] | None = None) -> str:
    """The address to put in the frame: Pipewright's web address, then /embed/<token>."""
    return f"{url.rstrip('/')}/embed/{embed_token(embed_id, secret, minutes=minutes, filters=filters)}"
