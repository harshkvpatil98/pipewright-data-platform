from __future__ import annotations

import time
from pathlib import Path
from typing import Any


def check_local_export_connection(config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    warnings: list[str] = []
    path = Path(config["path"]).expanduser()
    start = time.perf_counter()
    try:
        resolved = path.resolve()
    except OSError:
        return False, "Invalid path.", None, warnings

    if not resolved.exists():
        return False, "Path does not exist.", None, warnings
    if not resolved.is_dir():
        return False, "Path is not a directory.", None, warnings

    latency_ms = (time.perf_counter() - start) * 1000.0
    return True, "Directory exists and is accessible.", latency_ms, warnings
