"""Path-scope validation.

This is the *policy* layer: which repository paths a task is allowed to have
written. It runs against the integration diff, so it catches a write wherever it
came from. It is not, on its own, a permission boundary -- a check performed
after the fact cannot prevent a write. The boundary lives in `sandbox.py`; this
decides whether an observed change is admissible.

Some paths are refused for every task regardless of what a specification says,
because an agent that can edit the verification registry or the publisher can
approve its own work.

## Literal paths and patterns

One rule, stated once, and applied by every caller in this package:

**a pattern is a glob if and only if it contains `*` or `?`. Every other
character, `[` and `]` included, is literal.**

This repository is a Next.js App Router application, so real file paths look
like `apps/web/src/app/projects/[projectId]/datasets/[datasetId]/page.tsx`.
Under `fnmatch` -- which this module used to call -- `[projectId]` is a
character class, so that literal path was *refused* while the unrelated
`apps/web/src/app/projects/p/datasets/d/page.tsx` was *allowed*: wrong in both
directions at once. A glob character class has no use here and a dynamic route
segment appears in dozens of paths, so brackets are literal and the ambiguity is
gone rather than merely documented.

Glob semantics otherwise follow the familiar ones:

* `*` and `?` match within a single path segment and never cross `/`;
* `**` as a whole segment matches zero or more segments;
* a pattern with no wildcard at all is a literal path, and also covers
  everything beneath it, so `services/service-datasets` owns its subtree.

Forbidden patterns are evaluated before allowed ones and win, always.
"""

from __future__ import annotations

import importlib.machinery as machinery
import re
from functools import lru_cache
from pathlib import Path, PurePosixPath

from ..errors import PolicyViolation

#: Every file suffix this interpreter will import a module from.
_IMPORTABLE_SUFFIXES = tuple(sorted(set(
    machinery.SOURCE_SUFFIXES + machinery.BYTECODE_SUFFIXES
    + machinery.EXTENSION_SUFFIXES
)))

#: Never writable by any task, in any run. Controller state, provider
#: configuration, verification definitions, the publisher, and Git's own
#: metadata. A task that asks for one of these is a policy violation, not a
#: scope to be widened.
#: Names CPython imports by itself during interpreter startup, and every file
#: suffix that would satisfy such an import. Built from `importlib.machinery`
#: rather than written out, so a suffix this interpreter supports cannot be
#: missed by having been forgotten here.
STARTUP_HOOK_NAMES = ("sitecustomize", "usercustomize")

_STARTUP_HOOK_PATTERNS = tuple(
    pattern
    for name in STARTUP_HOOK_NAMES
    for pattern in (
        *(f"**/{name}{suffix}" for suffix in _IMPORTABLE_SUFFIXES),
        f"**/{name}",          # a package directory
        f"**/{name}/**",       # and everything in it
    )
)

ALWAYS_FORBIDDEN = (
    ".git/**", ".git",
    ".pw-dev/**", ".pw-dev",
    "tools/dev-orchestrator/src/pw_dev/verify/**",
    "tools/dev-orchestrator/src/pw_dev/publish/**",
    "tools/dev-orchestrator/pw-dev.toml",
    ".env", ".env.*", "**/.env", "**/.env.*",
    "**/id_rsa", "**/id_ed25519", "**/*.pem", "**/*.key",
    ".github/workflows/**",
    # Python imports these automatically at interpreter startup, from anywhere
    # on `sys.path`. A checkout's first-party source roots are on the `sys.path`
    # of the interpreter the *controller* runs verification with, unsandboxed --
    # so a task able to add one of these would be choosing what executes during
    # every check, and could exit zero in silence. CPython ships neither; the
    # one on this machine belongs to Homebrew, which is luck, not a boundary.
    # Every importable form of the name, not one spelling of it: a package
    # directory, sourceless bytecode and a compiled extension all satisfy
    # `import sitecustomize` exactly as the `.py` does.
    *_STARTUP_HOOK_PATTERNS,
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


def is_pattern(raw: str) -> bool:
    """Whether this string is a glob. `[` and `]` are literal; see the module docstring."""
    return "*" in raw or "?" in raw


def _segments(raw: str) -> tuple[str, ...]:
    cleaned = raw.strip().replace("\\", "/").rstrip("/")
    return tuple(part for part in cleaned.split("/") if part not in ("", "."))


@lru_cache(maxsize=4096)
def _segment_globs_intersect(left: str, right: str) -> bool:
    """Can one path segment satisfy both single-segment globs?

    A small two-sided wildcard match: `*` consumes any run of characters on
    either side, `?` consumes exactly one. Used for overlap detection, where
    both sides may contain wildcards; plain matching only ever has wildcards on
    one side, and falls out of the same function.
    """

    @lru_cache(maxsize=None)
    def go(i: int, j: int) -> bool:
        while i < len(left) and j < len(right) and left[i] not in "*?" \
                and right[j] not in "*?" and left[i] == right[j]:
            i += 1
            j += 1
        if i < len(left) and left[i] == "*":
            return go(i + 1, j) or (j < len(right) and go(i, j + 1))
        if j < len(right) and right[j] == "*":
            return go(i, j + 1) or (i < len(left) and go(i + 1, j))
        if i == len(left) or j == len(right):
            return i == len(left) and j == len(right)
        if left[i] == "?" or right[j] == "?":
            return go(i + 1, j + 1)
        return left[i] == right[j] and go(i + 1, j + 1)

    return go(0, 0)


@lru_cache(maxsize=4096)
def _sequences_intersect(left: tuple[str, ...], right: tuple[str, ...]) -> bool:
    """Is there a path both segment sequences match? `**` spans zero or more."""
    if not left and not right:
        return True
    if not left:
        return all(segment == "**" for segment in right)
    if not right:
        return all(segment == "**" for segment in left)
    if left[0] == "**":
        return (_sequences_intersect(left[1:], right)
                or _sequences_intersect(left, right[1:]))
    if right[0] == "**":
        return (_sequences_intersect(left, right[1:])
                or _sequences_intersect(left[1:], right))
    if not _segment_globs_intersect(left[0], right[0]):
        return False
    return _sequences_intersect(left[1:], right[1:])


def _claim_forms(segments: tuple[str, ...]) -> tuple[tuple[str, ...], ...]:
    """Every sequence a declared pattern stands for.

    A wildcard-free pattern owns its subtree, so `services/service-datasets`
    also stands for `services/service-datasets/**`. Expanding it here, rather
    than special-casing it inside the comparison, is what makes the comparison
    exact. An earlier version compared the literal against a same-length prefix
    of the other pattern, and `apps/web` versus `**/package-lock.json` slipped
    through: both accept `apps/web/package-lock.json`, and the check said they
    did not overlap -- so the scheduler would have run both tasks at once.
    """
    if any(is_pattern(segment) or segment == "**" for segment in segments):
        return (segments,)
    return (segments, segments + ("**",))


def patterns_overlap(left: str, right: str) -> bool:
    """Whether two declared patterns can both claim the same file.

    Exact, not approximate: the answer is yes only when some concrete path
    satisfies both. Two tasks whose patterns overlap are never dispatched
    concurrently, so a false "no" would let two workers edit one file -- which
    is why this is decided rather than guessed from a shared prefix.
    """
    left_segments, right_segments = _segments(left), _segments(right)
    if not left_segments or not right_segments:
        return False
    return any(
        _sequences_intersect(mine, theirs)
        for mine in _claim_forms(left_segments)
        for theirs in _claim_forms(right_segments)
    )


def pattern_covers(outer: str, inner: str) -> bool:
    """Whether everything `inner` can claim is also claimed by `outer`.

    Containment, not intersection. `apps/web/**` intersects
    `**/package-lock.json` -- `apps/web/package-lock.json` satisfies both -- but
    a task that owns the web application has not thereby declared that it edits
    a lockfile, and serializing every frontend task against every backend one on
    that basis would be a worse answer than the question deserves.

    **Sound, and deliberately incomplete.** It returns `True` only for the two
    shapes where containment is a fact rather than an inference:

    1. the two patterns are the same;
    2. `outer` is a run of literal segments, optionally followed by `**`, and
       `inner` starts with exactly those literal segments. Every path `inner`
       can produce then begins with that prefix, which `outer` owns.

    Anything else is `False`, meaning *not established* rather than *false*.
    Every caller treats an unestablished containment as "no implicit lock" or
    "no finding", which is the safe direction: the path guard still refuses the
    write, and `patterns_overlap` -- which is exact -- still refuses the
    concurrency.

    The previous version expanded `inner`'s wildcards into placeholder text and
    matched that one witness against `outer`. One witness is not a proof:
    `pattern_covers("src/*p*", "src/*")` was `True` because the placeholder
    happened to contain a `p`, while `src/x` disproves it, and the placeholder's
    own letters made a legitimate claim like `**/*pw*` look like it contained
    `.git/**`.
    """
    outer_segments, inner_segments = _segments(outer), _segments(inner)
    if not outer_segments or not inner_segments:
        return False
    if outer_segments == inner_segments:
        return True

    prefix = outer_segments[:-1] if outer_segments[-1] == "**" else outer_segments
    if any(is_pattern(segment) or segment == "**" for segment in prefix):
        return False
    if not prefix:
        return outer_segments == ("**",)
    return inner_segments[:len(prefix)] == prefix


def matches(path: str, pattern: str) -> bool:
    """Whether a concrete repository path is claimed by one pattern."""
    return _matches(path, pattern)


def _matches(path: str, pattern: str) -> bool:
    """Whether a concrete repository path is claimed by one pattern."""
    pattern_segments = _segments(pattern)
    if not pattern_segments:
        return False
    path_segments = _segments(path)
    if _sequences_intersect(pattern_segments, path_segments):
        return True
    # A bare directory pattern covers everything under it.
    if not any(is_pattern(segment) or segment == "**" for segment in pattern_segments):
        return (len(path_segments) > len(pattern_segments)
                and path_segments[:len(pattern_segments)] == pattern_segments)
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
                if patterns_overlap(mine, theirs):
                    shared.append(f"{mine} ~ {theirs}")
        return shared

    def claims(self, pattern: str) -> bool:
        """Whether this guard's allowed set can reach anything `pattern` names."""
        return any(patterns_overlap(pattern, mine) for mine in self.allowed)

    def literal_roots(self) -> list[str]:
        """The concrete repository prefixes the allowed patterns are anchored at.

        The leading run of wildcard-free segments of each pattern, deduplicated
        and with descendants of another root dropped. Used to check, before a
        worker starts, that everything a task claims resolves inside its own
        checkout -- the same literal-versus-pattern rule as everywhere else, so
        a dynamic-route directory is an anchor rather than a wildcard.
        """
        roots: set[str] = set()
        for pattern in self.allowed:
            prefix: list[str] = []
            for segment in _segments(pattern):
                if segment == "**" or is_pattern(segment):
                    break
                prefix.append(segment)
            if prefix:
                roots.add("/".join(prefix))
        ordered = sorted(roots)
        return [
            root for root in ordered
            if not any(root != other and root.startswith(other + "/") for other in ordered)
        ]


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
