"""Path-scope validation.

This is the *policy* layer: which repository paths a task is allowed to have
written. It runs against the integration diff, so it catches a write wherever it
came from. It is not, on its own, a permission boundary -- a check performed
after the fact cannot prevent a write. The boundary lives in `sandbox.py`; this
decides whether an observed change is admissible.

Some paths are refused for every task regardless of what a specification says,
because an agent that can edit the verification registry or the publisher can
approve its own work.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path, PurePosixPath

from ..errors import PolicyViolation

#: Never writable by any task, in any run. Controller state, provider
#: configuration, verification definitions, the publisher, and Git's own
#: metadata. A task that asks for one of these is a policy violation, not a
#: scope to be widened.
ALWAYS_FORBIDDEN = (
    ".git/**", ".git",
    ".pw-dev/**", ".pw-dev",
    "tools/dev-orchestrator/src/pw_dev/verify/**",
    "tools/dev-orchestrator/src/pw_dev/publish/**",
    "tools/dev-orchestrator/pw-dev.toml",
    ".env", ".env.*", "**/.env", "**/.env.*",
    "**/id_rsa", "**/id_ed25519", "**/*.pem", "**/*.key",
    ".github/workflows/**",
)


class PathViolation(PolicyViolation):
    """A path a task may not write, with the reason it was refused.

    Subclasses `PolicyViolation` so the run loop treats it as what it is -- an
    agent asking for something the policy forbids, which blocks the run with an
    explanation -- rather than letting it escape as an unhandled error.
    """

    def __init__(self, path: str, reason: str) -> None:
        self.path = path
        self.reason = reason
        super().__init__(f"{path}: {reason}")


def normalise(raw: str) -> str:
    """Repository-relative POSIX path, or raise.

    Rejects absolute paths, `..` traversal, NUL bytes and home expansion before
    any of them reach a filesystem call.
    """
    if not raw or not raw.strip():
        raise PathViolation(raw, "empty path")
    if "\x00" in raw:
        raise PathViolation(raw, "contains a NUL byte")
    candidate = raw.strip().replace("\\", "/")
    if candidate.startswith("~"):
        raise PathViolation(raw, "home-directory expansion is not allowed")
    # A Windows drive path is not absolute to PurePosixPath, so it would pass the
    # check below and then be created as a literal `C:` directory in the
    # repository. Refuse it as the absolute path it is meant to be.
    if re.match(r"^[A-Za-z]:(?:/|$)", candidate):
        raise PathViolation(raw, "drive-letter paths are not repository-relative")
    if candidate.startswith("//"):
        raise PathViolation(raw, "UNC paths are not repository-relative")
    pure = PurePosixPath(candidate)
    if pure.is_absolute():
        raise PathViolation(raw, "absolute paths are not allowed")
    parts = [p for p in pure.parts if p not in (".",)]
    if any(part == ".." for part in parts):
        raise PathViolation(raw, "'..' traversal is not allowed")
    if not parts:
        raise PathViolation(raw, "resolves to the repository root")
    return "/".join(parts)


def _matches(path: str, pattern: str) -> bool:
    pattern = pattern.strip().replace("\\", "/")
    if not pattern:
        return False
    if fnmatch.fnmatchcase(path, pattern):
        return True
    # A bare directory pattern covers everything under it.
    if not any(ch in pattern for ch in "*?["):
        prefix = pattern.rstrip("/")
        return path == prefix or path.startswith(prefix + "/")
    # `a/**` should also cover `a/b/c`, which fnmatch's `*` does not cross.
    if pattern.endswith("/**"):
        prefix = pattern[:-3]
        return path == prefix or path.startswith(prefix + "/")
    return False


class PathGuard:
    """Decides whether one task may write one path."""

    def __init__(self, allowed: list[str], forbidden: list[str] | None = None) -> None:
        self.allowed = [p.strip().replace("\\", "/") for p in allowed if p and p.strip()]
        self.forbidden = list(ALWAYS_FORBIDDEN) + [
            p.strip().replace("\\", "/") for p in (forbidden or []) if p and p.strip()
        ]

    def check(self, raw_path: str) -> str:
        path = normalise(raw_path)
        for pattern in self.forbidden:
            if _matches(path, pattern):
                raise PathViolation(
                    path,
                    f"matches the forbidden pattern {pattern!r}"
                    + (
                        " (controller state, credentials, Git metadata and the "
                        "verification/publication code are never writable by a task)"
                        if pattern in ALWAYS_FORBIDDEN else ""
                    ),
                )
        if not self.allowed:
            raise PathViolation(path, "this task declares no writable paths")
        for pattern in self.allowed:
            if _matches(path, pattern):
                return path
        raise PathViolation(
            path, f"outside this task's declared ownership ({', '.join(self.allowed)})"
        )

    def partition(self, paths: list[str]) -> tuple[list[str], list[PathViolation]]:
        """Split observed changes into admissible ones and violations."""
        ok: list[str] = []
        bad: list[PathViolation] = []
        for raw in paths:
            try:
                ok.append(self.check(raw))
            except PathViolation as violation:
                bad.append(violation)
        return ok, bad

    def overlaps(self, other: "PathGuard") -> list[str]:
        """Patterns two tasks both claim. Used to refuse concurrent dispatch."""
        shared = []
        for mine in self.allowed:
            for theirs in other.allowed:
                if mine == theirs or _matches(mine.rstrip("/*"), theirs) or _matches(
                    theirs.rstrip("/*"), mine
                ):
                    shared.append(f"{mine} ~ {theirs}")
        return shared


def resolve_within(root: Path, raw_path: str) -> Path:
    """Join a checked relative path to a root, refusing anything that escapes.

    Resolves symlinks first: a symlink inside the worktree pointing at the
    original checkout would otherwise turn an in-scope write into an out-of-tree
    one.
    """
    relative = normalise(raw_path)
    root = Path(root).resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError:
        raise PathViolation(raw_path, f"resolves outside {root}") from None
    return candidate
