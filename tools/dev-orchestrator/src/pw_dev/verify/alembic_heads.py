"""Assert that a migration directory has exactly one head.

`alembic heads` was the registered check before this. It exits 0 when there are
two heads and it exits 0 when there are none -- both were reproduced against
this repository's own Alembic on 2026-09-17 -- so a green result proved that the
command ran, and nothing about the revision graph. Two workers each allocating a
revision is precisely the failure the check exists to catch, and that is the
case it passed.

This reads the revision graph through Alembic's own `ScriptDirectory` and states
the count. Exactly one head exits 0. Zero heads, several heads, a cycle, a
missing `down_revision` target, an unreadable revision file and an unloadable
configuration are all non-zero, each naming what it found.

It lives under `pw_dev/verify/`, which `workspace.guard.ALWAYS_FORBIDDEN` makes
unwritable by every task in every run. A check an agent can edit is not a check.
It reads only the migration scripts; it opens no database connection, so it runs
without Postgres and never touches migration history.
"""

from __future__ import annotations

import sys
from pathlib import Path

USAGE = "usage: alembic_heads.py <directory containing alembic.ini>"


def resolve_heads(project_dir: Path) -> tuple[list[str], list[str]]:
    """Return `(heads, problems)` for the Alembic project rooted at `project_dir`.

    A problem is anything that stops the graph being read. It is reported rather
    than raised so the caller can print every one of them.
    """
    ini = project_dir / "alembic.ini"
    if not ini.is_file():
        return [], [f"no alembic.ini at {ini}"]

    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
    except ImportError as exc:  # pragma: no cover - alembic is a hard dependency here
        return [], [f"alembic is not importable: {exc}"]

    try:
        config = Config(str(ini))
        # `prepend_sys_path` and `script_location` are resolved relative to the
        # ini file, not the process working directory.
        script = ScriptDirectory.from_config(config)
    except Exception as exc:  # noqa: BLE001 - every load failure is a non-pass
        return [], [f"could not load the Alembic configuration at {ini}: {exc!r}"]

    try:
        heads = list(script.get_heads())
    except Exception as exc:  # noqa: BLE001 - a cycle or a dangling parent lands here
        return [], [f"could not resolve the revision graph: {exc!r}"]

    problems: list[str] = []
    try:
        revisions = list(script.walk_revisions())
    except Exception as exc:  # noqa: BLE001
        problems.append(f"could not walk the revision history: {exc!r}")
        revisions = []

    known = {revision.revision for revision in revisions}
    for revision in revisions:
        for parent in revision.down_revision or ():
            if isinstance(revision.down_revision, str):
                parent = revision.down_revision
            if parent and parent not in known:
                problems.append(
                    f"{revision.revision} names a down_revision {parent!r} that does not exist"
                )
            if isinstance(revision.down_revision, str):
                break

    return sorted(heads), problems


def main(argv: list[str]) -> int:
    if len(argv) != 1:
        print(USAGE, file=sys.stderr)
        return 2
    project_dir = Path(argv[0]).resolve()
    heads, problems = resolve_heads(project_dir)

    for problem in problems:
        print(f"alembic:single-head: {problem}", file=sys.stderr)

    if problems and not heads:
        print("alembic:single-head: FAIL — the revision graph could not be read, so the "
              "number of heads is unknown. Unknown is not one.", file=sys.stderr)
        return 1

    print(f"alembic:single-head: {len(heads)} head(s) in {project_dir}: "
          f"{', '.join(heads) if heads else '(none)'}")

    if problems:
        return 1
    if len(heads) == 1:
        print("alembic:single-head: PASS — exactly one head.")
        return 0
    if not heads:
        print("alembic:single-head: FAIL — no head revision. Either the versions directory "
              "is empty or every revision is superseded; a migration chain with no head "
              "cannot be upgraded to.", file=sys.stderr)
        return 1
    print(f"alembic:single-head: FAIL — {len(heads)} heads. Two parallel revisions were "
          f"allocated from the same parent; merge them into one chain before publishing.",
          file=sys.stderr)
    return 1


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main(sys.argv[1:]))
