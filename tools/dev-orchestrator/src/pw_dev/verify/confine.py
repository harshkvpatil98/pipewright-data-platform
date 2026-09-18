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
  store — lands there and is thrown away. It redirects where `~` *points*; it
  does not stop anything reading the operator's real home by absolute path,
  because reads are not confined at all;
* **writes** limited to the checkout under test plus the few shared caches the
  declared checks genuinely need. Everything else is denied by default, which
  covers the original checkout, its `.git`, the controller's own run state,
  every other worktree, and the operator's credentials without having to
  enumerate them;
* an **honest outcome** when the boundary cannot be applied. A check that was
  supposed to run confined and did not has not produced the evidence it claims
  to produce, so the runner records that rather than a pass.

One more thing it cannot do, and it is worth naming precisely because it looks
like it should: **a write rule names a path, and a file has as many paths as
something cares to give it.** Anything writable on this filesystem can hold a
hard link to a file in a denied directory — same inode, different name — and
writing through the link changes the denied file. That is not a hole in a
particular rule, it is what path-based write confinement is; carving the link's
directory out only moves where the link is made. Containing it needs the
immutable files somewhere a check cannot link from: a read-only mount, or a
container. Until then, a dependency tree or a source file can be modified by a
check that means to, and `node_modules` is outside the fingerprint, so that
particular modification is not visible afterwards either.

What this does *not* do is restrict reads, network access, or process control.
A check that builds the web application reaches a package cache; one that runs
live acceptance starts a server and talks to it over a local socket. Candidate
code can therefore still read any file this user can read, reach the network and
local services, and signal this user's processes. Confining those too would need
a much larger piece of work — a disposable network namespace and a vendored
toolchain — and pretending otherwise would be the same overclaim this module
exists to remove. The limitation is recorded in the evidence, not only here.
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from ..workspace.sandbox import sandbox_wrapper

#: Kept out of the write grant even though they sit inside the checkout.
#:
#: `.venv` holds the interpreter the *next* check will run, and the manifest
#: that decides where it imports from. `.git` is the worktree's indirection into
#: the original repository's object store. Both are the controller's to prepare,
#: neither is a check's to rewrite, and leaving them writable meant one check
#: could arrange what the next one executed — while neither directory counts
#: towards the tree fingerprint, so nothing would have looked different
#: afterwards.
CARVED_OUT = (".venv", ".git")

#: Also carved out, and for the same reason. A dependency tree holds programs
#: later checks execute -- `next`, `tsc`, `eslint` -- and `node_modules` is
#: excluded from the tree fingerprint, so replacing one of them would change
#: what runs without changing anything a later comparison looks at. The trees
#: are the controller's copy; a check reads them and does not edit them.
CARVED_OUT_TREES = ("node_modules",)

#: Re-opened inside a carved-out dependency tree. Some tools insist on keeping
#: their cache beside the code they read — Vitest writes its results to
#: `node_modules/.vite`, and denying it stops the suite running at all. These
#: are caches; `node_modules/.bin`, where the executables live, is not among
#: them and stays closed.
TREE_CACHES = (".vite", ".cache", ".tmp")

#: Workspaces live one or two levels in; deeper than this belongs to a
#: dependency of a dependency, which is inside a tree already carved out.
TREE_SEARCH_DEPTH = 3


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
            "covers": "file writes, by path",
            "does_not_cover": ("reads, network and local services, process control, "
                               "and writes reaching a denied file through another "
                               "name for it such as a hard link"),
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


def _dependency_trees(checkout: Path) -> list[Path]:
    """Every dependency tree inside the checkout, at any workspace depth.

    A symlink named `node_modules` is not one. Following it would let the
    checkout choose which directory got denied -- and, worse, which directory a
    cache re-grant below it resolved into.
    """
    checkout = Path(checkout).resolve()
    found: list[Path] = []

    def walk(directory: Path, depth: int) -> None:
        if depth > TREE_SEARCH_DEPTH:
            return
        try:
            entries = sorted(directory.iterdir())
        except OSError:
            return
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.name in CARVED_OUT_TREES:
                if entry.is_dir():
                    found.append(entry)
                continue
            if entry.name.startswith(".") or not entry.is_dir():
                continue
            walk(entry, depth + 1)

    walk(checkout, 1)
    return found


def _safe_regrants(trees: list[Path]) -> list[Path]:
    """Caches that may be reopened inside a denied tree, canonically checked.

    A re-grant is the last matching rule, so it overrides the denial above it.
    That makes it exactly as dangerous as it is useful: a cache path that
    resolved somewhere else would reopen wherever it pointed -- including
    `node_modules/.bin`, or something outside the checkout entirely.

    So the path is canonicalised and required to still be inside the canonical
    tree it belongs to, and nothing on the way to it may be a link. A cache that
    does not exist yet is created here, by the controller, so that the check
    finds a real directory rather than an opportunity.
    """
    safe: list[Path] = []
    for tree in trees:
        canonical_tree = tree.resolve()
        for name in TREE_CACHES:
            cache = tree / name
            # Emptied and recreated for every check, by the controller. A
            # re-granted directory is writable, and a writable directory inside
            # an otherwise denied tree can hold a *hard link* to a denied file —
            # same inode, reachable under a permitted name. Removing the
            # directory removes the alias with it, so no link survives from one
            # check to the next.
            try:
                if cache.is_symlink() or cache.is_file():
                    cache.unlink()
                elif cache.is_dir():
                    shutil.rmtree(cache)
                cache.mkdir(parents=True)
            except OSError:
                continue
            try:
                canonical = cache.resolve(strict=True)
            except OSError:
                continue
            if canonical != canonical_tree and canonical_tree not in canonical.parents:
                continue
            if canonical.name not in TREE_CACHES:
                continue
            safe.append(canonical)
    return safe


def for_check(
    check_id: str, *, checkout: Path, run_dir: Path, mode: str,
    scratch: Path | None = None,
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

    write_roots = [checkout, home]
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

    denials = [checkout / name for name in CARVED_OUT]
    trees = _dependency_trees(checkout)
    denials.extend(trees)
    regrants = _safe_regrants(trees)
    wrap = sandbox_wrapper(write_roots, profile_path, denials, regrants)
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
