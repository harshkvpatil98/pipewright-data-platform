from __future__ import annotations

import os
import time
from typing import Any

from shared_python.server_files import OutsideServerFiles, confine


def check_local_export_connection(config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    """The folder exists inside the server's shared files folder and can be written to."""
    start = time.perf_counter()
    try:
        folder = confine(str(config.get("path") or ""))
    except OutsideServerFiles as exc:
        return False, str(exc), None, []
    if not folder.exists():
        return False, f"There is no folder at {folder}.", None, []
    if not folder.is_dir():
        return False, f"{folder} is a file, not a folder.", None, []
    if not os.access(folder, os.W_OK):
        return False, f"The server cannot write to {folder}.", None, []
    latency_ms = (time.perf_counter() - start) * 1000.0
    return True, f"The folder {folder} is ready to receive files.", latency_ms, []
