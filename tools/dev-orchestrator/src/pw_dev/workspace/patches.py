"""Controller-owned patch bundles.

A worker's output leaves its worktree as a patch the controller reads, checks
against the task's path scope, and applies. The worker does not commit and the
controller does not merge branches: a bundle is inspectable, and a branch merge
is not.

Binary content is carried too (`--binary`), so a new PNG or Parquet fixture is
not silently dropped between the worktree and the candidate.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..errors import PwDevError
from ..util.hashing import digest_text
from . import git
from .guard import PathGuard, PathViolation


class PatchError(PwDevError):
    """A bundle could not be produced or applied."""


@dataclass(frozen=True)
class PatchBundle:
    task_id: str
    base_commit: str
    diff: str
    changed_paths: list[str]
    digest: str
    empty: bool

    def stat(self) -> str:
        return f"{len(self.changed_paths)} paths, {len(self.diff)} bytes"


#: Paths that are never part of a candidate, as Git pathspecs.
#:
#: Two kinds. The controller's own scratch, which a worker did not write. And
#: the debris a *check* leaves behind: running the tests to verify a tree is not
#: a change to that tree, but `__pycache__` and friends land in it all the same,
#: and would otherwise be reported as an out-of-scope write -- or block
#: publication as a temporary artefact the controller itself created.
EPHEMERAL = (
    ".pw-dev-worktree", ".pw-dev-scratch", ".pw-dev",
    "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
    ".next", ".turbo", ".coverage", "node_modules", ".venv",
)

CONTROLLER_SCRATCH = tuple(
    spec
    for name in EPHEMERAL
    for spec in (f":(exclude){name}", f":(exclude){name}/**", f":(exclude)**/{name}",
                 f":(exclude)**/{name}/**")
) + (":(exclude)*.pyc", ":(exclude)**/*.pyc")

# Deliberately *not* excluded: `.orig`, `.rej`, `.DS_Store`, `.env`. Those are a
# worker's leftovers or a mistake, and the publisher refuses to commit them.
# Dropping them quietly would turn a signal into a silence.


def export_bundle(worktree_path: Path, task_id: str, base_commit: str) -> PatchBundle:
    """Capture everything a worker changed, tracked or not."""
    repo = Path(worktree_path)
    # Stage untracked files so they appear in the diff. Staging inside a
    # throwaway worktree is bookkeeping, not a commit.
    git.git(repo, ["add", "-A", "--", ".", *CONTROLLER_SCRATCH], check=False)
    result = git.git(
        repo,
        ["diff", "--cached", "--binary", "--no-color", "--no-ext-diff", "--src-prefix=a/",
         "--dst-prefix=b/", base_commit, "--", ".", *CONTROLLER_SCRATCH],
        check=False, timeout=600,
    )
    if not result.ok and result.returncode not in (0, 1):
        raise PatchError(f"could not export a patch for {task_id}: {result.stderr[:500]}")
    diff = result.stdout
    names = git.out(
        repo, ["diff", "--cached", "--name-only", base_commit, "--", ".", *CONTROLLER_SCRATCH],
        check=False,
    )
    paths = sorted({p for p in names.splitlines() if p})
    return PatchBundle(
        task_id=task_id, base_commit=base_commit, diff=diff, changed_paths=paths,
        digest=digest_text(diff), empty=not paths,
    )


def apply_bundle(
    target: Path, bundle: PatchBundle, *, guard: PathGuard | None = None,
    three_way: bool = True,
) -> list[str]:
    """Apply a bundle to the integration checkout.

    The path scope is checked *before* anything is written, so an out-of-scope
    change is refused rather than applied and then reported.
    """
    if bundle.empty:
        return []
    if guard is not None:
        ok, violations = guard.partition(bundle.changed_paths)
        if violations:
            raise PathViolation(
                violations[0].path,
                f"{bundle.task_id} changed {len(violations)} path(s) outside its ownership: "
                + "; ".join(f"{v.path} ({v.reason})" for v in violations[:5]),
            )
        del ok

    argv = ["apply", "--index", "--whitespace=nowarn"]
    if three_way:
        argv.append("--3way")
    result = git.git(target, [*argv, "-"], check=False, input_text=bundle.diff, timeout=600)
    if not result.ok:
        raise PatchError(
            f"{bundle.task_id} did not apply cleanly: "
            f"{(result.stderr or result.stdout).strip()[:1000]}"
        )
    return list(bundle.changed_paths)


def would_conflict(target: Path, bundle: PatchBundle) -> bool:
    """Dry-run an apply. Used to route a conflict instead of discovering it late."""
    if bundle.empty:
        return False
    result = git.git(
        target, ["apply", "--check", "--3way", "-"], check=False,
        input_text=bundle.diff, timeout=600,
    )
    return not result.ok


def conflicting_paths(target: Path) -> list[str]:
    names = git.out(target, ["diff", "--name-only", "--diff-filter=U"], check=False)
    return [p for p in names.splitlines() if p]
