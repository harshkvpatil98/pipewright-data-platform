"""The single-head check, against revision graphs built for the purpose.

`alembic heads` was the registered command. It prints the heads and exits 0 --
with two heads, and with none. Both were reproduced against this repository's
own Alembic before this check was written, which is why "the command succeeded"
is not the assertion here: the number of heads is.

Every migration directory below is a fixture built in `tmp_path`. Nothing here
reads or changes `apps/api-gateway/alembic/`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from pw_dev.verify import alembic_heads
from pw_dev.verify.registry import Registry

SCRIPT = Path(alembic_heads.__file__)

INI = """[alembic]
script_location = %(here)s
sqlalchemy.url = sqlite:///unused.db
"""

ENV = """from alembic import context


def run_migrations_offline():
    pass


def run_migrations_online():
    pass
"""

REVISION = '''"""FIXTURE revision {name}."""
revision = "{name}"
down_revision = {parent}


def upgrade():
    pass


def downgrade():
    pass
'''


def migration_dir(root: Path, revisions: list[tuple[str, str | None]]) -> Path:
    project = root / "project"
    versions = project / "versions"
    versions.mkdir(parents=True)
    (project / "alembic.ini").write_text(INI, encoding="utf-8")
    (project / "env.py").write_text(ENV, encoding="utf-8")
    (project / "script.py.mako").write_text("", encoding="utf-8")
    for name, parent in revisions:
        (versions / f"{name}.py").write_text(
            REVISION.format(name=name, parent=repr(parent)), encoding="utf-8")
    return project


def run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(SCRIPT), str(project)],
        capture_output=True, text=True, timeout=120, check=False,
    )


def test_exactly_one_head_passes(tmp_path: Path):
    project = migration_dir(tmp_path, [("a1", None), ("b1", "a1"), ("c1", "b1")])
    result = run(project)
    assert result.returncode == 0, result.stderr
    assert "1 head(s)" in result.stdout
    assert "PASS" in result.stdout
    assert alembic_heads.resolve_heads(project) == (["c1"], [])


def test_two_heads_fail(tmp_path: Path):
    """Two workers each allocating a revision from the same parent."""
    project = migration_dir(tmp_path, [("a1", None), ("b1", "a1"), ("b2", "a1")])
    result = run(project)
    assert result.returncode == 1
    assert "2 heads" in result.stderr
    assert "merge them into one chain" in result.stderr
    heads, problems = alembic_heads.resolve_heads(project)
    assert sorted(heads) == ["b1", "b2"] and not problems


def test_no_heads_fail(tmp_path: Path):
    project = migration_dir(tmp_path, [])
    result = run(project)
    assert result.returncode == 1
    assert "no head revision" in result.stderr
    assert alembic_heads.resolve_heads(project) == ([], [])


def test_a_dangling_parent_is_a_non_pass(tmp_path: Path):
    project = migration_dir(tmp_path, [("a1", None), ("b1", "does-not-exist")])
    result = run(project)
    assert result.returncode == 1
    heads, problems = alembic_heads.resolve_heads(project)
    assert problems, "an unresolvable graph is not one head"


def test_a_missing_configuration_is_a_non_pass(tmp_path: Path):
    result = run(tmp_path / "nowhere")
    assert result.returncode == 1
    assert "no alembic.ini" in result.stderr
    assert "Unknown is not one" in result.stderr


def test_an_unreadable_revision_is_a_non_pass(tmp_path: Path):
    project = migration_dir(tmp_path, [("a1", None)])
    (project / "versions" / "broken.py").write_text("this is not python(", encoding="utf-8")
    result = run(project)
    assert result.returncode == 1
    heads, problems = alembic_heads.resolve_heads(project)
    assert problems or not heads


@pytest.mark.parametrize("revisions", [
    [("a1", None)],
    [("a1", None), ("b1", "a1")],
])
def test_the_command_alembic_heads_alone_would_have_passed_all_of_these(
        tmp_path: Path, revisions):
    """Documenting the gap this check closes, not just asserting the new behaviour.

    `alembic heads` exits 0 for one head, for two, and for none. Only the count
    distinguishes them, so only the count can be the gate.
    """
    project = migration_dir(tmp_path, revisions)
    plain = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "alembic", "heads"],
        cwd=project, capture_output=True, text=True, timeout=120, check=False,
    )
    assert plain.returncode == 0

    forked = migration_dir(tmp_path / "forked", [("a1", None), ("b1", "a1"), ("b2", "a1")])
    plain_forked = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, "-m", "alembic", "heads"],
        cwd=forked, capture_output=True, text=True, timeout=120, check=False,
    )
    assert plain_forked.returncode == 0, "this is the failure the old check let through"
    assert run(forked).returncode == 1, "and this is the one that catches it"


def test_the_registered_check_runs_the_assertion_and_gates(tmp_path: Path):
    check = Registry().get("alembic:heads")
    argv, _ = check.render(Path("/candidate"))
    assert argv[1].endswith("pw_dev/verify/alembic_heads.py")
    assert argv[2] == "/candidate/apps/api-gateway"
    assert "-m" not in argv or argv[argv.index("-m") + 1] != "alembic", (
        "the bare `alembic heads` command is not what this check runs"
    )
    assert check.gate, "one head is not something a plan may omit"


def test_the_assertion_script_is_never_writable_by_a_task():
    from pw_dev.workspace.guard import PathGuard, PathViolation

    with pytest.raises(PathViolation, match="forbidden"):
        PathGuard(["**"]).check(
            "tools/dev-orchestrator/src/pw_dev/verify/alembic_heads.py")


def test_the_check_opens_no_database(tmp_path: Path):
    """It reads migration scripts. It does not connect, upgrade or downgrade."""
    project = migration_dir(tmp_path, [("a1", None)])
    (project / "alembic.ini").write_text(
        INI.replace("sqlite:///unused.db", "postgresql://nobody@127.0.0.1:1/none"),
        encoding="utf-8")
    result = run(project)
    assert result.returncode == 0, result.stderr
    assert not (project / "unused.db").exists()
