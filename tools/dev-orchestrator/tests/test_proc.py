"""The subprocess runner: environment, stdin, bounds, and process-tree cleanup."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest

from pw_dev.util import proc


def test_env_is_built_from_an_allowlist_not_inherited():
    source = {"PATH": "/bin", "HOME": "/home/x", "SECRET_TOKEN": "s3cret", "USER": "x"}
    env = proc.build_env(source=source)
    assert env["PATH"] == "/bin"
    assert env["USER"] == "x"
    assert "SECRET_TOKEN" not in env


def test_denylisted_names_never_reach_a_child():
    source = {
        "PATH": "/bin", "HOME": "/h",
        "GIT_AUTHOR_NAME": "someone else",
        "ANTHROPIC_API_KEY": "sk-ant-should-not-travel",
        "CLAUDECODE": "1",
    }
    env = proc.build_env(
        allowlist=(*proc.BASE_ENV_ALLOWLIST, "GIT_AUTHOR_NAME", "ANTHROPIC_API_KEY", "CLAUDECODE"),
        source=source,
    )
    assert "GIT_AUTHOR_NAME" not in env
    assert "ANTHROPIC_API_KEY" not in env
    assert "CLAUDECODE" not in env


def test_a_denylisted_name_cannot_be_forced_through_overrides():
    with pytest.raises(ValueError, match="denylist"):
        proc.build_env(overrides={"GIT_COMMITTER_EMAIL": "someone@else"})


def test_argv_must_be_a_list_of_strings(tmp_path: Path):
    with pytest.raises(TypeError):
        proc.run([sys.executable, 3], cwd=tmp_path, env=proc.build_env(), timeout=5)  # type: ignore[list-item]


def test_stdin_is_always_bound(tmp_path: Path):
    """A child that reads stdin must see EOF, not block forever.

    `codex exec` reads stdin when it is a pipe and waits for EOF. Left unbound
    under an orchestrator, that is a hang the timeout eventually kills — after
    burning the whole task budget on nothing.
    """
    result = proc.run(
        [sys.executable, "-c", "import sys; sys.stdout.write(repr(sys.stdin.read()))"],
        cwd=tmp_path, env=proc.build_env(), timeout=20,
    )
    assert result.ok
    assert result.stdout == "''"


def test_stdin_data_is_delivered(tmp_path: Path):
    result = proc.run(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read().upper())"],
        cwd=tmp_path, env=proc.build_env(), timeout=20, stdin_data="hello",
    )
    assert result.stdout == "HELLO"


def test_output_is_capped_and_the_cap_is_reported(tmp_path: Path):
    result = proc.run(
        [sys.executable, "-c", "print('x' * 200000)"],
        cwd=tmp_path, env=proc.build_env(), timeout=30, max_output_bytes=1000,
    )
    assert result.truncated
    assert len(result.stdout) < 2000
    assert "truncated" in result.stdout
    assert "200" in result.stdout  # the real size is stated, not hidden


def test_timeout_kills_the_whole_process_tree(tmp_path: Path):
    """A timeout must not leave a grandchild running.

    Both provider CLIs are launchers that exec another binary. Terminating only
    the process we started leaves the real one alive, holding the worktree.
    """
    marker = tmp_path / "grandchild.pid"
    script = (
        "import os, subprocess, sys, time\n"
        f"child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    result = proc.run(
        [sys.executable, "-c", script], cwd=tmp_path, env=proc.build_env(), timeout=2,
    )
    assert result.timed_out
    assert not result.ok

    grandchild = int(marker.read_text())
    deadline = time.time() + 10
    while time.time() < deadline:
        if not proc.process_group_alive(grandchild):
            break
        time.sleep(0.1)
    assert not proc.process_group_alive(grandchild), (
        f"pid {grandchild} survived the timeout; the process group was not cleaned up"
    )


def test_cancellation_stops_a_running_child(tmp_path: Path):
    calls = {"n": 0}

    def cancel() -> bool:
        calls["n"] += 1
        return calls["n"] > 3

    result = proc.run(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        cwd=tmp_path, env=proc.build_env(), timeout=60, cancel_check=cancel,
    )
    assert result.cancelled
    assert not result.timed_out
    assert not result.ok


def test_nonzero_exit_is_data_not_an_exception(tmp_path: Path):
    result = proc.run(
        [sys.executable, "-c", "import sys; sys.exit(7)"],
        cwd=tmp_path, env=proc.build_env(), timeout=20,
    )
    assert result.returncode == 7
    assert not result.ok


def test_missing_executable_is_reported_clearly(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="not found"):
        proc.run(["definitely-not-a-real-binary-xyz"], cwd=tmp_path,
                 env=proc.build_env(), timeout=5)


def test_missing_cwd_is_refused(tmp_path: Path):
    with pytest.raises(FileNotFoundError, match="cwd"):
        proc.run([sys.executable, "-c", "pass"], cwd=tmp_path / "nope",
                 env=proc.build_env(), timeout=5)


def test_the_child_really_does_get_its_own_process_group(tmp_path: Path):
    if sys.platform == "win32":  # pragma: no cover
        pytest.skip("POSIX process groups")
    result = proc.run(
        [sys.executable, "-c", "import os; print(os.getpgrp())"],
        cwd=tmp_path, env=proc.build_env(), timeout=20,
    )
    assert result.ok
    assert int(result.stdout.strip()) != os.getpgrp()
