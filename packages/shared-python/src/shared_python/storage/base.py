from __future__ import annotations

import re
from pathlib import PurePosixPath


def sanitize_filename(file_name: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", file_name.strip()).strip(".-")
    return normalized or "upload"


# Keeping paths relative and normalized prevents path traversal and backend-specific path leakage.
def normalize_relative_path(relative_path: str) -> str:
    normalized = PurePosixPath(relative_path)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError("Invalid storage path.")
    return normalized.as_posix()
