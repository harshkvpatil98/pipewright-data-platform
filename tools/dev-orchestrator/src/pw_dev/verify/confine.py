"""A write boundary for verification itself.

Workers have been confined since the beginning: a worker is a model writing
code, so the tool has always assumed it might write in the wrong place.
Verification was not confined, and the argument for that was circular —
verification *runs the phase's own code*, because running it is what
verification means. A `conftest.py` that a task legitimately owns is imported
by pytest before the first test, with the controller's privileges, in the
controller's `HOME`.

So the boundary here is not "stop candidate code running". It is "decide in
advance what running it may touch":

* a **disposable HOME**, created empty for each check. Anything a check leaves
  in `~` — an npm cache, a tool's state directory, a credential helper's
  store — lands there and is thrown away, and anything it tries to *read* from
  the operator's real home is simply not there;
* **writes** limited to the checkout under test plus the few shared caches the
  declared checks genuinely need. Everything else is denied by default, which
  covers the original checkout, its `.git`, the controller's own run state,
  every other worktree, and the operator's credentials without having to
  enumerate them;
* an **honest outcome** when the boundary cannot be applied. A check that was
  supposed to run confined and did not has not produced the evidence it claims
  to produce, so the runner records that rather than a pass.

What this does *not* do is restrict reads or network. A check that builds the
web application reaches a package cache; one that runs live acceptance starts a
server and talks to it over a local socket. Confining those too would need a
much larger piece of work — a disposable network namespace and a vendored
toolchain — and pretending otherwise would be the same overclaim this module
exists to remove. The limitation is stated in the report the runner records.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..workspace.sandbox import sandbox_wrapper

#: Directories the checkout deliberately shares with the repository it came
#: from, rather than copying. A candidate is a `git worktree`, so it has no
#: installed JavaScript dependencies; the controller links it to the original's.
#: A link is followed on write, so the *original* directory has to be writable
#: or `npm run build` cannot write the build cache it is expected to write.
#:
#: This is a real hole, and a narrow one: it is a dependency tree that `npm ci`
#: reproduces, it holds no source and no credentials, and the alternative — a
#: private copy per checkout — costs gigabytes per run.
#:
#: Which directories those are is not guessed here. The checkout is asked:
#: anything named `node_modules` that is a symlink resolving back inside the
#: original is one the controller linked, and nothing else is granted. A
#: candidate that somehow has its own directory needs no hole and is given none.
SHARED_CACHE_NAME = "node_modules"

#: How far down to look. Workspaces live one or two levels in; a `node_modules`
#: deeper than this belongs to a dependency, not to the repository.
SHARED_CACHE_DEPTH = 3


@dataclass(frozen=True)
class Confinement:
    """What a check is allowed to touch, and whether that is actually enforced."""

    mode: str
    home: Path
    write_roots: tuple[Path, ...] = ()
    profile_path: Path | None = None
    wrap: Callable[[list[str]], list[str]] | None = field(default=None, repr=False)
    detail: str = ""

    @property
    def enforced(self) -> bool:
        return self.mode == "enforced" and self.wrap is not None

    @property
    def failed(self) -> bool:
        """Confinement was required by policy and could not be applied."""
        return self.mode == "enforced" and self.wrap is None

    def apply(self, argv: list[str]) -> list[str]:
        return self.wrap(argv) if self.wrap is not None else list(argv)

    def to_dict(self) -> dict:
        return {
            "mode": self.mode,
            "enforced": self.enforced,
            "home": str(self.home),
            "write_roots": [str(root) for root in self.write_roots],
            "profile": str(self.profile_path) if self.profile_path else None,
            "detail": self.detail,
            # Said plainly, in the evidence, so nobody reads "enforced" as more
            # than it is.
            "covers": "file writes",
            "does_not_cover": "reads and network access",
        }


def slug(check_id: str) -> str:
    """A filesystem-safe name for a check id like `repo:live-acceptance`."""
    return re.sub(r"[^A-Za-z0-9._-]+", "-", check_id).strip("-") or "check"


def disposable_home(root: Path, check_id: str) -> Path:
    """An empty HOME for one check, replacing whatever was there last time.

    Replaced rather than reused: a check that leaves state behind must not be
    able to hand it to the next one, and a check that reads `~/.something`
    should find nothing regardless of what ran before it.
    """
    home = Path(root) / "verify-home" / slug(check_id)
    if home.exists():
        shutil.rmtree(home, ignore_errors=True)
    home.mkdir(parents=True, exist_ok=True)
    return home


def shared_cache_roots(checkout: Path, repo_root: Path | None) -> list[Path]:
    """The original's directories this checkout actually reaches through a link.

    Discovered rather than declared, so the grant always matches what the
    controller linked. Only symlinks are considered, and only ones that resolve
    inside the original checkout: a real directory is already covered by the
    grant on the checkout itself, and a link pointing somewhere else entirely is
    not something this function will quietly make writable.
    """
    if repo_root is None:
        return []
    repo_root = Path(repo_root).resolve()
    checkout = Path(checkout).resolve()
    roots: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > SHARED_CACHE_DEPTH:
            return
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.name.startswith(".") or entry.name == ".git":
                continue
            if entry.name == SHARED_CACHE_NAME:
                if entry.is_symlink():
                    try:
                        target = entry.resolve(strict=True)
                    except OSError:
                        continue
                    if target == repo_root or repo_root in target.parents:
                        if target not in roots:
                            roots.append(target)
                # Never descend into a dependency tree.
                continue
            if entry.is_dir() and not entry.is_symlink():
                walk(entry, depth + 1)

    walk(checkout, 1)
    return roots


def for_check(
    check_id: str, *, checkout: Path, run_dir: Path, mode: str,
    repo_root: Path | None = None, scratch: Path | None = None,
) -> Confinement:
    """Decide and, where the host allows it, build the boundary for one check."""
    checkout = Path(checkout).resolve()
    run_dir = Path(run_dir)
    home = disposable_home(run_dir, check_id)

    if mode == "off":
        return Confinement(
            mode="off", home=home,
            detail="isolation is configured off; this check ran with the "
                   "controller's own write access",
        )

    write_roots = [checkout, home, *shared_cache_roots(checkout, repo_root)]
    if scratch is not None:
        # Temporary files and caches for this checkout's checks. Outside
        # the checkout so verifying a tree does not change it.
        write_roots.append(Path(scratch))
    profile_path = run_dir / "sandbox" / f"verify-{slug(check_id)}.sb"

    if mode != "enforced":
        return Confinement(
            mode=mode, home=home, write_roots=tuple(write_roots),
            detail=f"isolation resolved to {mode!r}, which this host cannot enforce; "
                   f"the disposable HOME applies but writes were not confined",
        )

    wrap = sandbox_wrapper(write_roots, profile_path)
    if wrap is None:
        return Confinement(
            mode="enforced", home=home, write_roots=tuple(write_roots),
            profile_path=profile_path,
            detail="isolation is configured enforced but no write-confinement "
                   "mechanism was available when the check was about to run",
        )
    return Confinement(
        mode="enforced", home=home, write_roots=tuple(write_roots),
        profile_path=profile_path, wrap=wrap,
        detail=f"writes confined to {len(write_roots)} root(s) with a disposable HOME",
    )
