from __future__ import annotations

import json
from typing import Any


def parse_cors_origins(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        if value.startswith("["):
            return [str(item) for item in json.loads(value)]
        return [item.strip() for item in value.split(",") if item.strip()]
    raise ValueError("Invalid CORS origins value")
