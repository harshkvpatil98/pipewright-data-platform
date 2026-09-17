"""Content digests and tree fingerprints.

A *fingerprint* answers one question: is this the same tree the evidence was
produced against? It has to include files Git does not track yet, because a new
untracked source file is exactly the kind of change that would otherwise slip
past a `git diff`-shaped check.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Iterable

_IGNORED_DIR_NAMES = {
    ".git", "node_modules", "__pycache__", ".venv", ".pytest_cache",
    ".ruff_cache", ".rush-global", ".next", ".turbo", "dist", "build",
    ".mypy_cache", ".pw-dev",
}


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest_text(text: str) -> str:
    return digest_bytes(text.encode("utf-8"))


def digest_json(document: Any) -> str:
    """Digest of a JSON document, independent of key order and whitespace."""
    return digest_text(json.dumps(document, sort_keys=True, separators=(",", ":")))


def digest_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _iter_files(root: Path) -> Iterable[Path]:
    stack = [root]
    while stack:
        current = stack.pop()
        try:
            entries = sorted(current.iterdir())
        except (PermissionError, FileNotFoundError):
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                if entry.name in _IGNORED_DIR_NAMES:
                    continue
                stack.append(entry)
            elif entry.is_file():
                yield entry


def tree_fingerprint(root: Path, *, extra_ignored: set[str] | None = None) -> str:
    """Fingerprint the working tree, tracked or not.

    Walks the filesystem rather than asking Git, so an untracked new file
    changes the fingerprint. Build outputs and dependency directories are
    skipped: a `next build` writing to `.next/` is not a change to the
    candidate, and including it would invalidate evidence the moment a check
    runs.
    """
    ignored = _IGNORED_DIR_NAMES | (extra_ignored or set())
    h = hashlib.sha256()
    root = root.resolve()
    entries = []
    for path in _iter_files(root):
        if any(part in ignored for part in path.relative_to(root).parts[:-1]):
            continue
        entries.append(path)
    for path in sorted(entries):
        relative = path.relative_to(root).as_posix()
        h.update(relative.encode("utf-8"))
        h.update(b"\0")
        h.update(digest_file(path).encode("ascii"))
        h.update(b"\0")
        # Mode matters: making a script executable is a real change.
        h.update(b"x" if path.stat().st_mode & 0o111 else b"-")
        h.update(b"\n")
    return "tree:" + h.hexdigest()


def git_tree_hash(repo: Path) -> str | None:
    """Git's own hash of the index tree, when the directory is a repository.

    Recorded alongside the filesystem fingerprint. It is the value that makes
    "the committed tree is exactly the approved tree" checkable against Git
    itself rather than against our own walk.
    """
    try:
        result = subprocess.run(
            ["git", "write-tree"],
            cwd=repo, capture_output=True, text=True, check=False, timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def short(digest: str, length: int = 12) -> str:
    """A readable prefix for logs. Never used for comparison."""
    body = digest.split(":", 1)[-1]
    return body[:length]
