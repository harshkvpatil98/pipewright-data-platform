"""Per-worker checkouts.

Each writing worker gets its own worktree, created from *its own prerequisite
commit* rather than from the run's base. A task that depends on the contract
task must start from the tree that contains those contracts; branching every
task from the original base and merging later is how two workers independently
invent two incompatible versions of the same interface.

The controller owns the integration checkpoints. Workers never commit, push,
merge, rebase, or change Git configuration -- the controller reads their trees
and produces the checkpoint itself.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from ..errors import StateError
from ..util.hashing import tree_fingerprint
from . import git


@dataclass(frozen=True)
class Worktree:
    task_id: str
    path: Path
    branch: str
    base_commit: str

    def fingerprint(self) -> str:
        return tree_fingerprint(self.path)


class WorktreeManager:
    """Allocates, snapshots and tears down task checkouts."""

    def __init__(self, repo_root: Path, run_dir: Path, run_id: str) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.run_dir = Path(run_dir).resolve()
        self.run_id = run_id
        self.root = self.run_dir / "worktrees"
        self.root.mkdir(parents=True, exist_ok=True)

    def branch_name(self, task_id: str, attempt: int) -> str:
        safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in task_id)
        return f"pw-dev/{self.run_id}/{safe}-a{attempt}"

    def create(self, task_id: str, *, base_commit: str, attempt: int = 1) -> Worktree:
        """Allocate a fresh checkout at `base_commit`."""
        path = self.root / f"{task_id}-a{attempt}"
        if path.exists():
            self.destroy(path)
        branch = self.branch_name(task_id, attempt)
        git.git(self.repo_root, ["branch", "-D", branch], check=False)
        git.add_worktree(self.repo_root, path, base_commit, branch)
        self._write_marker(path, task_id)
        return Worktree(task_id=task_id, path=path, branch=branch, base_commit=base_commit)

    def _write_marker(self, path: Path, task_id: str) -> None:
        """Record which task owns a checkout, for anyone reading the run directory.

        Written *beside* the worktree rather than inside it. A marker file in the
        tree is controller bookkeeping that would appear in the worker's patch
        bundle, get reported as a write outside the task's declared ownership,
        and block a run that did nothing wrong.
        """
        markers = self.root / ".markers"
        markers.mkdir(parents=True, exist_ok=True)
        (markers / f"{task_id}.txt").write_text(
            f"run={self.run_id}\ntask={task_id}\nroot={path}\n", encoding="utf-8"
        )

    def destroy(self, path: Path) -> None:
        git.remove_worktree(self.repo_root, path)
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    def cleanup(self, *, keep: bool = False) -> None:
        """Remove every worktree for this run.

        `keep=True` leaves them in place, which is what a BLOCKED or PAUSED run
        does: throwing away a partially finished checkout destroys recoverable
        work.
        """
        if keep:
            return
        for child in sorted(self.root.glob("*")):
            if child.is_dir() and child.name != ".markers":
                self.destroy(child)
        git.git(self.repo_root, ["worktree", "prune"], check=False)

    def prune_branches(self) -> None:
        """Delete this run's task branches. Only ever touches `pw-dev/<run-id>/*`."""
        prefix = f"pw-dev/{self.run_id}/"
        listing = git.out(self.repo_root, ["branch", "--list", f"{prefix}*"], check=False)
        for line in listing.splitlines():
            name = line.strip().lstrip("* ").strip()
            if name.startswith(prefix):
                git.git(self.repo_root, ["branch", "-D", name], check=False)

    def verify_distinct(self, worktree: Worktree) -> None:
        """Refuse a checkout that would put worker writes in the user's source tree.

        The default state directory is `.pw-dev/` inside the repository, which is
        gitignored and excluded from every tree fingerprint, so worktrees under it
        are their own directories and writing there touches nothing the user
        owns. Anywhere *else* inside the checkout is refused: that is the case
        this guard exists for.
        """
        resolved = worktree.path.resolve()
        if resolved == self.repo_root:
            raise StateError(
                f"{worktree.task_id} was allocated the original checkout; refusing to run "
                "a worker against the user's working tree"
            )
        try:
            resolved.relative_to(self.repo_root)
        except ValueError:
            return  # entirely outside the repository
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise StateError(
                f"{worktree.task_id}'s worktree {resolved} is inside the original checkout "
                f"but outside the run's worktree directory ({self.root}); worker writes "
                f"would land in the user's tree"
            ) from None
