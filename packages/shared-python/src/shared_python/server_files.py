"""The one folder on the server that people may point the platform at.

Reading files from "a folder on the server" and delivering files to one are
useful on a single machine and dangerous if the folder can be anything: a
project editor who could set it to `/` could read the platform's own secrets
or overwrite its files. So every server path goes through `confine`: it must
resolve inside `SERVER_FILES_ROOT` (default `data/server-files`, relative to
the process), and a relative path is taken to mean "inside that folder".
"""

from __future__ import annotations

import os
from pathlib import Path

ENVIRONMENT_VARIABLE = "SERVER_FILES_ROOT"
DEFAULT_ROOT = "data/server-files"


class OutsideServerFiles(ValueError):
    """A path that would leave the server-files folder."""


def server_files_root() -> Path:
    return Path(os.environ.get(ENVIRONMENT_VARIABLE) or DEFAULT_ROOT).expanduser().resolve()


def confine(path: str) -> Path:
    """The absolute path for `path`, which must lie inside the server-files folder."""
    root = server_files_root()
    candidate = Path((path or "").strip() or ".").expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    resolved = candidate.resolve()
    if resolved != root and root not in resolved.parents:
        raise OutsideServerFiles(
            f"Only folders inside {root} can be used. Ask whoever runs Pipewright to put the files "
            f"there, or to change {ENVIRONMENT_VARIABLE}."
        )
    return resolved
