"""Tamper detection for things a worker must never change.

This is the second half of the isolation story and it is *detection*, not
prevention. The enforced boundary in `sandbox.py` is what stops the write; this
notices if one happened anyway -- on a host running supervised, through a path
the profile granted for another reason, or because of a bug here.

Saying that plainly matters: a post-run digest comparison that gets described as
a guarantee is worse than no check, because it invites running unattended on a
host that cannot enforce anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..util.hashing import digest_file, tree_fingerprint


@dataclass
class Sentinel:
    """Digests of protected locations, taken before workers start."""

    files: dict[str, str] = field(default_factory=dict)
    trees: dict[str, str] = field(default_factory=dict)
    missing: list[str] = field(default_factory=list)

    @classmethod
    def capture(cls, *, files: list[Path], trees: list[Path]) -> "Sentinel":
        sentinel = cls()
        for path in files:
            path = Path(path)
            if path.is_file():
                sentinel.files[str(path)] = digest_file(path)
            else:
                sentinel.missing.append(str(path))
        for path in trees:
            path = Path(path)
            if path.is_dir():
                sentinel.trees[str(path)] = tree_fingerprint(path)
            else:
                sentinel.missing.append(str(path))
        return sentinel

    def diff(self) -> list[str]:
        """Protected locations whose contents changed since capture."""
        changes: list[str] = []
        for raw, expected in self.files.items():
            path = Path(raw)
            if not path.is_file():
                changes.append(f"{raw}: deleted")
            elif digest_file(path) != expected:
                changes.append(f"{raw}: contents changed")
        for raw, expected in self.trees.items():
            path = Path(raw)
            if not path.is_dir():
                changes.append(f"{raw}: directory removed")
            elif tree_fingerprint(path) != expected:
                changes.append(f"{raw}: tree changed")
        for raw in self.missing:
            if Path(raw).exists():
                changes.append(f"{raw}: created where nothing existed")
        return changes

    def to_dict(self) -> dict:
        return {"files": dict(self.files), "trees": dict(self.trees),
                "missing": list(self.missing)}


def protected_locations(repo_root: Path, state_dir: Path, run_dir: Path,
                        worktree_root: Path, exclude: Path | None = None) -> tuple[list[Path], list[Path]]:
    """What is watched during a run.

    Covers the operator's own checkout, controller state, the adopted policy,
    the verification registry, the publisher, Git metadata, and every *other*
    worker's checkout -- `exclude` is the one the current worker legitimately
    owns.
    """
    repo_root = Path(repo_root)
    pkg = Path(__file__).resolve().parent.parent
    files = [
        repo_root / "tools" / "dev-orchestrator" / "pw-dev.toml",
        pkg / "verify" / "registry.py",
        pkg / "publish" / "publisher.py",
        pkg / "publish" / "attribution.py",
        pkg / "workspace" / "guard.py",
        repo_root / ".git" / "config",
        repo_root / ".git" / "HEAD",
    ]
    trees = [state_dir / "runs" / run_dir.name / "evidence"]
    for child in sorted(Path(worktree_root).glob("*")):
        if child.is_dir() and (exclude is None or child.resolve() != Path(exclude).resolve()):
            trees.append(child)
    return [p for p in files], [p for p in trees]
