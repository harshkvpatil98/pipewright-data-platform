"""The one place this tool starts a process.

Rules enforced here rather than at each call site:

* commands are argument arrays -- there is no code path that builds a shell
  string, so nothing a model returns can become a shell token;
* `cwd` is explicit and must exist;
* the environment is built from an allowlist, not inherited;
* stdin is always bound (`codex exec` hangs forever reading a piped stdin that
  nobody closes -- it prints "Reading additional input from stdin..." and waits);
* stdout and stderr are capped, and the cap is reported rather than hidden;
* the child gets its own process group, so a timeout kills the whole tree and
  not just the launcher script. `codex` and `claude` are both Node wrappers
  around another binary; killing the wrapper alone leaves the real process
  running.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_MAX_OUTPUT_BYTES = 8 * 1024 * 1024

# Both provider CLIs authenticate through the OS keychain on macOS, and that
# lookup needs more of the session environment than HOME alone: an environment
# containing only PATH and HOME makes `claude -p` report "Not logged in".
# USER, LOGNAME and SHELL are what it actually needs, so the allowlist is the
# smallest set that was observed to work rather than a guess.
BASE_ENV_ALLOWLIST = (
    "PATH", "HOME", "USER", "LOGNAME", "SHELL", "LANG", "LC_ALL", "TZ",
    "TERM", "TMPDIR",
    # Where the connector verification servers are, when an operator has
    # started them. `connectors:servers` and the container tests read these and
    # record `infra_unavailable` without them -- which is honest, and was
    # unreachable: the operator could start the servers, export the URLs that
    # `docker-compose.connectors.yml` documents, and the check still could not
    # see them because nothing forwarded the names. CI sets the same three.
    "CONNECTORS_TEST_POSTGRES_URL", "CONNECTORS_TEST_MYSQL_URL",
    "CONNECTORS_TEST_MARIADB_URL",
)

# Never forwarded, even if a caller adds them to the allowlist. The Git ones
# would override the repository-local identity the publisher sets; the provider
# ones would silently move authentication onto a billable API route.
ENV_DENYLIST = frozenset({
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM", "GIT_CONFIG_COUNT",
    "ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "ANTHROPIC_BASE_URL",
    "OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_ORGANIZATION",
    "AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN",
    "GITHUB_TOKEN", "GH_TOKEN", "NPM_TOKEN",
    # Set by the Claude Code session that may be running this tool. Leaking
    # them into a child `claude -p` makes the child think it is a nested
    # session of its parent.
    "CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CLAUDE_CODE_SSE_PORT",
    "CLAUDE_CODE_MESSAGING_SOCKET", "CLAUDE_CODE_MESSAGING_TOKEN",
    "CLAUDE_CODE_EXECPATH", "CLAUDE_CODE_SESSION_ID",
    "CLAUDE_CODE_CHILD_SESSION", "CLAUDE_PID", "CLAUDE_EFFORT",
    "CLAUDE_CODE_SAFE_MODE", "CLAUDE_CODE_SIMPLE",
})


def build_env(
    *,
    allowlist: tuple[str, ...] = BASE_ENV_ALLOWLIST,
    overrides: dict[str, str] | None = None,
    source: dict[str, str] | None = None,
    trusted_overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build a child environment from an allowlist plus explicit overrides.

    `overrides` cannot set a denylisted name. `trusted_overrides` can, and
    exists for exactly one caller: the publisher setting `GIT_AUTHOR_*` and
    `GIT_COMMITTER_*` on its own commit.

    The two are separate because they answer opposite questions. The denylist
    stops an *inherited* `GIT_AUTHOR_NAME` from re-authoring a commit. The
    publisher is not inheriting one — it is asserting the owner's identity, and
    setting those variables explicitly is what guarantees the commit carries it
    whatever the surrounding shell says. Collapsing the two would either stop the
    publisher doing its job or let an inherited value through.
    """
    source = os.environ if source is None else source
    env: dict[str, str] = {}
    for name in allowlist:
        if name in ENV_DENYLIST:
            continue
        value = source.get(name)
        if value is not None:
            env[name] = value
    for name, value in (overrides or {}).items():
        if name in ENV_DENYLIST:
            raise ValueError(f"{name} is on the denylist and cannot be overridden")
        env[name] = value
    for name, value in (trusted_overrides or {}).items():
        env[name] = value
    env.setdefault("PATH", os.defpath)
    return env


@dataclass(frozen=True)
class ProcResult:
    """Everything the controller records about one external command."""

    argv: list[str]
    cwd: str
    returncode: int | None
    stdout: str
    stderr: str
    duration_seconds: float
    timed_out: bool
    cancelled: bool
    truncated: bool
    started_at: float
    env_keys: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Exit status zero and no timeout.

        Deliberately not the same question as "did the work succeed": both
        provider CLIs can exit zero while reporting an error in their structured
        output, and `claude -p` exits 1 while still emitting a valid result
        object. Callers check both.
        """
        return self.returncode == 0 and not self.timed_out and not self.cancelled


class _Capture:
    """A bounded byte sink. Keeps the head of the stream and counts the rest."""

    def __init__(self, limit: int) -> None:
        self.limit = limit
        self.chunks: list[bytes] = []
        self.size = 0
        self.total = 0

    def feed(self, data: bytes) -> None:
        self.total += len(data)
        if self.size >= self.limit:
            return
        room = self.limit - self.size
        piece = data[:room]
        self.chunks.append(piece)
        self.size += len(piece)

    @property
    def truncated(self) -> bool:
        return self.total > self.size

    def text(self) -> str:
        body = b"".join(self.chunks).decode("utf-8", errors="replace")
        if self.truncated:
            body += (
                f"\n[pw-dev: output truncated at {self.limit} bytes; "
                f"{self.total} bytes were produced]"
            )
        return body


def run(
    argv: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout: float,
    stdin_data: str | None = None,
    max_output_bytes: int = DEFAULT_MAX_OUTPUT_BYTES,
    on_stdout_line: "callable | None" = None,
    cancel_check: "callable | None" = None,
) -> ProcResult:
    """Run `argv` under the stated bounds and return everything observed.

    Never raises for a non-zero exit: an exit status is data the caller has to
    interpret alongside the structured output, not an exception.
    """
    if not argv:
        raise ValueError("argv must not be empty")
    if any(not isinstance(token, str) for token in argv):
        raise TypeError("argv must be a list of strings")
    cwd = Path(cwd)
    if not cwd.is_dir():
        raise FileNotFoundError(f"cwd does not exist: {cwd}")
    if shutil.which(argv[0], path=env.get("PATH", os.defpath)) is None and not Path(argv[0]).exists():
        raise FileNotFoundError(f"executable not found on the child PATH: {argv[0]}")

    started = time.monotonic()
    popen_kwargs: dict = {
        "cwd": str(cwd),
        "env": env,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.PIPE,
        "stdin": subprocess.PIPE if stdin_data is not None else subprocess.DEVNULL,
    }
    if sys.platform != "win32":
        popen_kwargs["start_new_session"] = True  # its own process group

    process = subprocess.Popen(argv, **popen_kwargs)  # noqa: S603 - argv array, no shell
    # Recorded now, while the leader is certainly alive. After it exits its
    # group id is no longer readable from it, and a process it left behind is
    # exactly the one that has to be reaped.
    group_id: int | None = None
    if sys.platform != "win32":
        try:
            group_id = os.getpgid(process.pid)
        except OSError:
            group_id = process.pid

    out = _Capture(max_output_bytes)
    err = _Capture(max_output_bytes)
    timed_out = False
    cancelled = False

    import threading

    def _pump(stream, sink: _Capture, line_hook) -> None:
        try:
            if line_hook is None:
                for chunk in iter(lambda: stream.read(65536), b""):
                    sink.feed(chunk)
            else:
                for line in stream:
                    sink.feed(line)
                    try:
                        line_hook(line.decode("utf-8", errors="replace").rstrip("\n"))
                    except Exception:  # noqa: BLE001 - a bad hook must not kill the run
                        pass
        except (ValueError, OSError):
            pass
        finally:
            try:
                stream.close()
            except OSError:
                pass

    threads = [
        threading.Thread(target=_pump, args=(process.stdout, out, on_stdout_line), daemon=True),
        threading.Thread(target=_pump, args=(process.stderr, err, None), daemon=True),
    ]
    for thread in threads:
        thread.start()

    if stdin_data is not None and process.stdin is not None:
        try:
            process.stdin.write(stdin_data.encode("utf-8"))
        except (BrokenPipeError, OSError):
            pass
        finally:
            try:
                process.stdin.close()
            except OSError:
                pass

    deadline = started + timeout
    poll_interval = 0.1
    while True:
        if process.poll() is not None:
            break
        now = time.monotonic()
        if now >= deadline:
            timed_out = True
            _terminate_tree(process)
            break
        if cancel_check is not None and cancel_check():
            cancelled = True
            _terminate_tree(process)
            break
        time.sleep(min(poll_interval, max(0.0, deadline - now)))

    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:  # pragma: no cover - only after SIGKILL failed
        pass
    for thread in threads:
        thread.join(timeout=10)

    # After *every* path, not only timeout and cancellation. A command whose
    # main process exits normally can leave a detached child behind -- and a
    # worker that wanted one would arrange exactly that, then have it wait for
    # the environment rebuild and edit the interpreter before checks run. The
    # group this call created is this call's to clean up.
    _reap_group(group_id)

    return ProcResult(
        argv=list(argv),
        cwd=str(cwd),
        returncode=process.returncode,
        stdout=out.text(),
        stderr=err.text(),
        duration_seconds=round(time.monotonic() - started, 3),
        timed_out=timed_out,
        cancelled=cancelled,
        truncated=out.truncated or err.truncated,
        started_at=started,
        env_keys=sorted(env),
    )


def _reap_group(group_id: int | None) -> None:
    """Terminate anything still alive in the group this run created.

    Silent when the group is already gone, which is the ordinary case: a
    well-behaved command leaves nothing behind and this costs one failed
    `killpg`.
    """
    if group_id is None or sys.platform == "win32":  # pragma: no cover - POSIX host
        return
    try:
        os.killpg(group_id, 0)
    except OSError:
        return  # nothing left
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(group_id, signal_number)
        except OSError:
            return
        deadline = time.monotonic() + (5.0 if signal_number == signal.SIGTERM else 2.0)
        while time.monotonic() < deadline:
            try:
                os.killpg(group_id, 0)
            except OSError:
                return
            time.sleep(0.05)


def _terminate_tree(process: subprocess.Popen) -> None:
    """SIGTERM the whole group, then SIGKILL what is left.

    Signalling the process alone is not enough: both provider CLIs are Node
    launchers that exec a platform binary, and a `claude -p` or `codex exec`
    child survives its wrapper being killed.
    """
    if sys.platform == "win32":  # pragma: no cover - this tool targets POSIX hosts
        process.terminate()
        return
    try:
        group = os.getpgid(process.pid)
    except (ProcessLookupError, OSError):
        return
    for sig, grace in ((signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        try:
            os.killpg(group, sig)
        except (ProcessLookupError, PermissionError, OSError):
            return
        waited = 0.0
        while waited < grace:
            if process.poll() is not None:
                return
            time.sleep(0.05)
            waited += 0.05


def process_group_alive(pid: int) -> bool:
    """Whether a recorded pid is still running. Used by crash recovery."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
