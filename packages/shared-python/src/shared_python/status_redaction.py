"""Strip sensitive-looking keys from status payloads before they leave the API."""

from __future__ import annotations

import re
from typing import Any

_UNSAFE = re.compile(
    r"(secret|password|token|credential|api[_-]?key|authorization|bearer|private[_-]?key)",
    re.IGNORECASE,
)


def redact_value(value: Any) -> Any:
    if isinstance(value, dict):
        return redact_details(value)
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def redact_details(details: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, raw in details.items():
        key_s = str(key)
        if _UNSAFE.search(key_s):
            out[key_s] = "[redacted]"
        else:
            out[key_s] = redact_value(raw)
    return out
