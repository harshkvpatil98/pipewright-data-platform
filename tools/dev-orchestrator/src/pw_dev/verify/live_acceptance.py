"""Required live acceptance: run a declared scenario against a server this
runner started from the candidate checkout, and fail closed on everything else.

`repo:smoke` is an *optional* script. It prints advice, it exits 0 when
`SMOKE_SKIP_NETWORK=1`, and when it does probe the network it is satisfied by
any process answering `/api/v1/health/live` on port 8000 -- including a gateway
started last week from a different checkout. That is useful as a smoke test and
it is not acceptance evidence for a phase whose promise is an authenticated
end-to-end workflow.

This runner exists for the second job, and the difference is structural:

* **it starts the server itself**, from the candidate's own virtualenv, in the
  candidate's own directory, on an ephemeral port it chose. There is no way for
  an unrelated server to answer, because the runner talks only to the child it
  launched and asserts that child is alive, is the candidate's interpreter, and
  is running inside the candidate;
* **the scenario is data, the runner is code.** A scenario declares requests
  and expectations and *nothing else*. What program starts, with what
  environment, against what database and storage, is fixed here, in a file
  `workspace.guard.ALWAYS_FORBIDDEN` makes unwritable by every task -- for the
  same reason the check registry is. An earlier version let the scenario name
  the module to launch, which meant a worker could point it at
  `python -m http.server`, assert `GET /` returns 200, and pass a Phase 18 gate
  without starting Pipewright at all;

* **the process under test is proved to be this checkout's code.** Before the
  server starts, the candidate interpreter is asked where it resolves
  `api_gateway` and the services from, and every origin must be inside the
  candidate. Pipewright installs its packages with `pip install -e`, so a
  virtualenv borrowed from the original checkout resolves them *there* -- and
  `api_gateway.config` then loads the operator's real `apps/api-gateway/.env`,
  pointing the "disposable" run at their actual database. That is refused
  rather than detected afterwards;
* **absence is a non-pass.** No scenario file, no launcher, a server that never
  became ready, a step that did not execute, a step the scenario marked skipped,
  or a missing credential all exit non-zero with a distinct code. Nothing here
  returns success for work that has not been done yet;
* **resources are disposable and owned.** The database URL, storage directory,
  signing secret and admin credentials are generated per invocation inside a
  temporary work directory, by this file. A scenario cannot set, override or
  read any of them. Teardown terminates the process group this runner created
  and removes the directory this runner made, and nothing else.

## Exit codes

| code | meaning | recorded outcome |
|---|---|---|
| 0 | every declared step executed and passed | `pass` |
| 1 | a step ran and failed an expectation | `fail` |
| 20 | the server under test never became ready | `infra_unavailable` |
| 21 | no scenario, malformed scenario, or a credential it needs was not created | `not_run` |
| 22 | the scenario declared a step that did not execute | `skip` |
| 2 | the runner could not execute at all | `error` |

A timeout is handled above this process: the check has a deadline and the
verification runner records `timeout`, which is not a pass either.

## The scenario document

Read from `scripts/live-acceptance/<name>.json` in the candidate. It carries
requests and expectations only:

```json
{
  "schema_version": "live_acceptance/v1",
  "name": "phase-18-time-travel",
  "readiness": {"path": "/api/v1/health/live", "timeout_seconds": 120},
  "steps": [{"name": "login", "method": "POST", "path": "/api/v1/auth/login",
             "json": {"username": "{test_username}", "password": "{test_password}"},
             "expect_status": 200, "capture": {"token": "/access_token"}}]
}
```

`launcher` and `env` keys are **refused**, not ignored: a scenario written
against the older shape must be rewritten rather than silently losing the
control it thought it had.

Placeholders are substituted by the runner and by nothing else:
`{test_username}`, `{test_password}` and `{capture:x}` for a value an earlier
step captured. A `$` is not expanded anywhere, so a scenario cannot reach the
operator's environment for a real credential.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

EXIT_PASS = 0
EXIT_FAIL = 1
EXIT_ERROR = 2
EXIT_INFRA = 20
EXIT_NOT_RUN = 21
EXIT_SKIPPED = 22

SCENARIO_DIR = "scripts/live-acceptance"
SCHEMA_VERSION = "live_acceptance/v1"

#: What may be started, and how. Chosen by the *controller* -- the check
#: registry passes a launcher name in the argv it owns -- never by a scenario.
#: A worker that could name the module to launch could satisfy an acceptance
#: gate with `python -m http.server`.
#:
#: `modules` are the packages whose import origin must resolve inside the
#: candidate before the server is allowed to start. `env` is built by
#: `_launcher_env` from runner-generated values only.
LAUNCHERS: dict[str, dict] = {
    "pipewright-gateway": {
        "description": "the Pipewright API gateway under uvicorn",
        "module": "uvicorn",
        "args": ["api_gateway.main:app", "--host", "127.0.0.1", "--port", "{port}"],
        "cwd": "apps/api-gateway",
        "modules": ("api_gateway", "shared_python", "service_auth", "service_datasets"),
    },
    # Selected only by this package's own tests, which pass it explicitly. The
    # registered check never does, so a scenario cannot reach it.
    "pw-dev-fixture": {
        "description": "the fixture application used by pw-dev's own tests",
        "module": "fixture_app",
        "args": ["--port", "{port}"],
        "cwd": ".",
        "modules": ("fixture_app",),
    },
}

#: Keys a scenario may not carry. They used to be honoured, which is how a
#: scenario could choose the program and its environment.
REFUSED_SCENARIO_KEYS = ("launcher", "env", "cleanup_paths", "modules")


class ScenarioError(Exception):
    """The scenario could not be used. Always a non-pass, never a failure of the code."""

    def __init__(self, message: str, code: int = EXIT_NOT_RUN) -> None:
        self.code = code
        super().__init__(message)


@dataclass
class StepResult:
    name: str
    executed: bool
    passed: bool
    detail: str
    status: int | None = None
    duration_seconds: float = 0.0


@dataclass
class Evidence:
    """What this invocation actually did, written next to the check's log."""

    scenario: str
    launcher: str = ""
    base_url: str | None = None
    server_pid: int | None = None
    server_pgid: int | None = None
    server_executable: str | None = None
    server_cwd: str | None = None
    module_origins: dict = field(default_factory=dict)
    steps: list[StepResult] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "scenario": self.scenario,
            "launcher": self.launcher,
            "base_url": self.base_url,
            "server_pid": self.server_pid,
            "server_pgid": self.server_pgid,
            "server_executable": self.server_executable,
            "server_cwd": self.server_cwd,
            "module_origins": self.module_origins,
            "steps": [vars(step) for step in self.steps],
            "problems": self.problems,
        }


# --------------------------------------------------------------------- loading
def load_scenario(repo: Path, name: str) -> dict:
    path = repo / SCENARIO_DIR / f"{name}.json"
    if not path.is_file():
        raise ScenarioError(
            f"no live acceptance scenario at {path.relative_to(repo)}. The phase that "
            f"promises this workflow has not written it yet, and a check with no scenario "
            f"is recorded as not_run -- it does not pass."
        )
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ScenarioError(f"{path.relative_to(repo)} could not be read as JSON: {exc}") from None
    if not isinstance(document, dict):
        raise ScenarioError(f"{path.relative_to(repo)} is not a JSON object")
    if document.get("schema_version") != SCHEMA_VERSION:
        raise ScenarioError(
            f"{path.relative_to(repo)} declares schema_version "
            f"{document.get('schema_version')!r}; this runner executes {SCHEMA_VERSION!r}"
        )
    for required in ("name", "readiness", "steps"):
        if required not in document:
            raise ScenarioError(f"{path.relative_to(repo)} has no {required!r}")
    present = [key for key in REFUSED_SCENARIO_KEYS if key in document]
    if present:
        raise ScenarioError(
            f"{path.relative_to(repo)} declares {present}, which a scenario does not "
            f"control. What starts, with what environment, and what is cleaned up are "
            f"decided by the runner; a scenario supplies requests and expectations. "
            f"Remove these keys rather than leaving them to be ignored."
        )
    if not isinstance(document["steps"], list) or not document["steps"]:
        raise ScenarioError(
            f"{path.relative_to(repo)} declares no steps. An empty scenario is not a "
            f"passing scenario."
        )
    return document


def substitute(value, mapping: dict[str, str]):
    """Fill `{placeholder}` occurrences. Unknown placeholders are an error."""
    if isinstance(value, str):
        def replace(match: re.Match) -> str:
            key = match.group(1)
            if key not in mapping:
                raise ScenarioError(
                    f"the scenario uses {{{key}}}, which this runner does not provide. "
                    f"Available: {', '.join(sorted(mapping))}. A credential the runner did "
                    f"not create is not available to a scenario."
                )
            return mapping[key]
        return re.sub(r"\{([A-Za-z0-9_:.-]+)\}", replace, value)
    if isinstance(value, list):
        return [substitute(item, mapping) for item in value]
    if isinstance(value, dict):
        return {key: substitute(item, mapping) for key, item in value.items()}
    return value


# ---------------------------------------------------------------- the server
def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def candidate_interpreter(repo: Path) -> Path:
    interpreter = repo / ".venv" / "bin" / "python"
    if not interpreter.exists():
        raise ScenarioError(
            f"{interpreter} does not exist, so no server can be started from this "
            f"checkout. The check did not run, which is not the same as passing."
        )
    return interpreter


def assert_modules_resolve_inside(repo: Path, modules: tuple[str, ...],
                                  evidence: "Evidence") -> None:
    """Refuse to start unless the interpreter resolves this checkout's code.

    Pipewright installs its packages with `pip install -e`, so a virtualenv
    that belongs to another checkout imports *that* checkout's source. The
    gateway would then be the operator's gateway: `api_gateway.config` loads
    `apps/api-gateway/.env` relative to the module file, so it would pick up
    their real `DATABASE_URL` and the "disposable" run would be pointed at
    their actual database.

    Asking the interpreter where it resolves each package, before anything
    starts, is the only way to know. A module that cannot be imported, or that
    resolves outside the candidate, is a non-pass -- not a warning.
    """
    interpreter = candidate_interpreter(repo)
    probe = (
        "import json, importlib.util as u;"
        f"print(json.dumps({{m: (u.find_spec(m).origin if u.find_spec(m) else None) "
        f"for m in {list(modules)!r}}}))"
    )
    try:
        result = subprocess.run(  # noqa: S603 - fixed argv, candidate interpreter
            [str(interpreter), "-c", probe], cwd=str(repo), capture_output=True,
            text=True, timeout=120, check=False,
            env={"PATH": os.environ.get("PATH", "/usr/bin:/bin"),
                 "PYTHONDONTWRITEBYTECODE": "1"},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScenarioError(f"could not ask {interpreter} where it resolves "
                            f"{list(modules)}: {exc}") from None
    if result.returncode != 0:
        raise ScenarioError(
            f"{interpreter} could not report module origins: "
            f"{result.stderr.strip()[:300]}"
        )
    try:
        origins = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ScenarioError(
            f"could not parse module origins from {interpreter}") from None

    root = str(repo.resolve())
    problems = []
    for module, origin in sorted(origins.items()):
        if not origin:
            problems.append(f"{module} is not importable")
            continue
        if not str(Path(origin).resolve()).startswith(root + os.sep):
            problems.append(f"{module} resolves to {origin}, outside the candidate")
    evidence.module_origins = origins
    if problems:
        raise ScenarioError(
            "the environment in this checkout does not run this checkout's code: "
            + "; ".join(problems)
            + ". A server started here would be testing a different tree, so the "
              "check did not run."
        )


def _launcher_env(workdir: str, mapping: dict[str, str]) -> dict[str, str]:
    """The child's whole environment, built here and not extendable.

    Every value that decides *what data the server touches* is generated per
    invocation inside the temporary work directory: a SQLite file nobody else
    has, an upload root nobody else has, a signing secret nobody else has, and
    an administrator whose password exists for the length of this process. The
    operator's environment is not inherited beyond `PATH` and `LANG`, so an
    unset variable falls back to a Pipewright default rather than to whatever
    happens to be exported.
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "HOME": workdir,
        "TMPDIR": workdir,
        "PYTHONDONTWRITEBYTECODE": "1",
        # Disposable stores. Absolute, and under the directory teardown removes.
        "DATABASE_URL": f"sqlite+pysqlite:///{workdir}/acceptance.db",
        "UPLOAD_ROOT_PATH": f"{workdir}/uploads",
        "APP_ENV": "test",
        "LOG_LEVEL": "WARNING",
        "AUTH_JWT_SECRET": mapping["jwt_secret"],
        # Test credentials, for this process only.
        "PW_DEV_LIVE_ACCEPTANCE": "1",
        "PW_DEV_LIVE_ADMIN_USERNAME": mapping["test_username"],
        "PW_DEV_LIVE_ADMIN_PASSWORD": mapping["test_password"],
        # The fixture launcher's store, for this package's own tests.
        "FIXTURE_STORE": f"{workdir}/store",
    }


def build_argv(repo: Path, launcher: dict, mapping: dict[str, str]) -> list[str]:
    """The argv for a *controller-selected* launcher. No scenario input reaches it."""
    interpreter = candidate_interpreter(repo)
    args = [str(arg).replace("{port}", mapping["port"]) for arg in launcher["args"]]
    return [str(interpreter), "-m", launcher["module"], *args]


def start_server(repo: Path, launcher: dict, mapping: dict[str, str],
                 log_path: Path) -> tuple[subprocess.Popen, Path]:
    argv = build_argv(repo, launcher, mapping)
    cwd = (repo / launcher["cwd"]).resolve()
    if not str(cwd).startswith(str(repo.resolve())):
        raise ScenarioError(f"launcher cwd {launcher['cwd']!r} resolves outside the checkout")
    if not cwd.is_dir():
        raise ScenarioError(
            f"{launcher['cwd']!r} is not a directory in this checkout, so "
            f"{launcher['description']} cannot be started here"
        )
    handle = log_path.open("wb")
    try:
        process = subprocess.Popen(  # noqa: S603 - argv built entirely by this file
            argv, cwd=str(cwd), env=_launcher_env(mapping["workdir"], mapping),
            stdout=handle, stderr=subprocess.STDOUT, start_new_session=True,
        )
    except Exception:
        handle.close()
        raise
    process._pw_dev_log = handle  # closed in teardown
    return process, cwd


def wait_ready(process: subprocess.Popen, base_url: str, path: str,
               timeout_seconds: float) -> None:
    deadline = time.monotonic() + timeout_seconds
    last = "no attempt completed"
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise ScenarioError(
                f"the server under test exited with status {process.returncode} before it "
                f"became ready", EXIT_INFRA,
            )
        try:
            with urllib.request.urlopen(base_url + path, timeout=5) as response:  # noqa: S310
                if 200 <= response.status < 300:
                    return
                last = f"HTTP {response.status}"
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = str(exc)
        time.sleep(0.25)
    raise ScenarioError(
        f"the server under test did not answer {path} within {timeout_seconds}s "
        f"(last: {last}). Infrastructure that was not reachable is not a pass.",
        EXIT_INFRA,
    )


def assert_still_running(process: subprocess.Popen, repo: Path,
                         evidence: Evidence) -> None:
    """The child this runner launched is still the thing answering.

    Identity was established before the port was ever opened: the launcher is
    fixed by the controller, the interpreter is the candidate's, and every
    module origin was proved to resolve inside the candidate. What remains to
    check during the run is that the same process is still alive -- an earlier
    version inspected `ps` output for the substring "python", which a process
    named `python` satisfies whatever it is running.
    """
    if process.poll() is not None:
        raise ScenarioError(
            f"the server under test exited with status {process.returncode} during the "
            f"run; the steps after that point did not execute", EXIT_INFRA,
        )


# ----------------------------------------------------------------- the steps
def pointer(document, path: str):
    """A minimal JSON pointer, so an expectation names a field rather than a substring."""
    current = document
    for raw in path.strip("/").split("/"):
        if raw == "":
            continue
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            try:
                current = current[int(token)]
            except (ValueError, IndexError):
                raise KeyError(path) from None
        elif isinstance(current, dict):
            if token not in current:
                raise KeyError(path)
            current = current[token]
        else:
            raise KeyError(path)
    return current


def run_step(step: dict, base_url: str, mapping: dict[str, str]) -> tuple[StepResult, dict]:
    name = str(step.get("name") or "(unnamed)")
    if step.get("skip"):
        return StepResult(name, executed=False, passed=False,
                          detail="the scenario marked this step skipped"), {}
    method = str(step.get("method") or "GET").upper()
    path = substitute(str(step.get("path") or "/"), mapping)
    headers = {k: substitute(str(v), mapping) for k, v in (step.get("headers") or {}).items()}
    body = None
    if step.get("json") is not None:
        body = json.dumps(substitute(step["json"], mapping)).encode("utf-8")
        headers.setdefault("Content-Type", "application/json")

    request = urllib.request.Request(base_url + path, data=body, method=method,  # noqa: S310
                                     headers=headers)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=step.get("timeout_seconds", 60)) as response:  # noqa: S310
            status = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read()
    except (urllib.error.URLError, OSError) as exc:
        return StepResult(name, executed=True, passed=False,
                          detail=f"the request did not complete: {exc}",
                          duration_seconds=round(time.monotonic() - started, 3)), {}

    duration = round(time.monotonic() - started, 3)
    try:
        document = json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        document = None

    expected_status = step.get("expect_status", 200)
    if status != expected_status:
        return StepResult(name, True, False,
                          f"expected HTTP {expected_status}, got {status}; body "
                          f"{raw[:200]!r}", status, duration), {}

    for expectation in step.get("expect") or []:
        target = expectation.get("pointer", "")
        try:
            actual = pointer(document, target)
        except KeyError:
            return StepResult(name, True, False,
                              f"the response has no {target!r}", status, duration), {}
        if "equals" in expectation and actual != expectation["equals"]:
            return StepResult(name, True, False,
                              f"{target} is {actual!r}, expected {expectation['equals']!r}",
                              status, duration), {}
        if "not_equals" in expectation and actual == expectation["not_equals"]:
            return StepResult(name, True, False,
                              f"{target} is {actual!r}, which the scenario forbids",
                              status, duration), {}
        if expectation.get("present") and actual is None:
            return StepResult(name, True, False, f"{target} is null", status, duration), {}

    captured: dict[str, str] = {}
    for key, target in (step.get("capture") or {}).items():
        try:
            captured[f"capture:{key}"] = str(pointer(document, target))
        except KeyError:
            return StepResult(name, True, False,
                              f"cannot capture {key!r}: the response has no {target!r}",
                              status, duration), {}

    return StepResult(name, True, True, f"HTTP {status}", status, duration), captured


# ------------------------------------------------------------------- driving
def execute(repo: Path, name: str, launcher_name: str,
            evidence_path: Path | None) -> tuple[int, Evidence]:
    evidence = Evidence(scenario=name, launcher=launcher_name)
    workdir = Path(tempfile.mkdtemp(prefix=f"pw-dev-live-{name}-"))
    process: subprocess.Popen | None = None
    pgid: int | None = None
    try:
        launcher = LAUNCHERS.get(launcher_name)
        if launcher is None:
            raise ScenarioError(
                f"{launcher_name!r} is not a launcher this runner knows. Known: "
                f"{', '.join(sorted(LAUNCHERS))}. A launcher is chosen by the check "
                f"registry, not by a scenario."
            )
        scenario = load_scenario(repo, name)
        assert_modules_resolve_inside(repo, launcher["modules"], evidence)

        port = free_port()
        mapping = {
            "port": str(port),
            "repo": str(repo.resolve()),
            "workdir": str(workdir),
            "test_username": "pw-dev-acceptance",
            "test_password": secrets.token_urlsafe(24),
            "jwt_secret": secrets.token_urlsafe(32),
        }
        base_url = f"http://127.0.0.1:{port}"
        evidence.base_url = base_url
        evidence.server_executable = str((repo / ".venv" / "bin" / "python").resolve())

        (workdir / "uploads").mkdir(parents=True, exist_ok=True)
        (workdir / "store").mkdir(parents=True, exist_ok=True)

        server_log = workdir / "server.log"
        process, cwd = start_server(repo, launcher, mapping, server_log)
        evidence.server_pid = process.pid
        evidence.server_cwd = str(cwd)
        try:
            pgid = os.getpgid(process.pid)
        except OSError:
            pgid = process.pid
        evidence.server_pgid = pgid

        readiness = scenario["readiness"]
        wait_ready(process, base_url, str(readiness.get("path", "/")),
                   float(readiness.get("timeout_seconds", 120)))
        assert_still_running(process, repo, evidence)

        # Only the placeholders a scenario may use. `workdir`, `repo`, `port`
        # and `jwt_secret` are deliberately absent: a scenario has no business
        # naming a path on this machine or the key the server signs with.
        step_mapping = {
            "test_username": mapping["test_username"],
            "test_password": mapping["test_password"],
        }

        declared = len(scenario["steps"])
        for step in scenario["steps"]:
            result, captured = run_step(step, base_url, step_mapping)
            evidence.steps.append(result)
            step_mapping.update(captured)
            if not result.executed or not result.passed:
                break
            assert_still_running(process, repo, evidence)

        executed = [s for s in evidence.steps if s.executed]
        failed = [s for s in evidence.steps if s.executed and not s.passed]
        skipped = [s for s in evidence.steps if not s.executed]

        if failed:
            evidence.problems.append(f"{failed[0].name}: {failed[0].detail}")
            return EXIT_FAIL, evidence
        if skipped:
            evidence.problems.append(
                f"{len(skipped)} declared step(s) did not execute, starting at "
                f"{skipped[0].name!r}. A scenario that skipped part of itself is not "
                f"acceptance evidence."
            )
            return EXIT_SKIPPED, evidence
        if len(executed) != declared:
            evidence.problems.append(
                f"the scenario declares {declared} step(s) and {len(executed)} ran")
            return EXIT_SKIPPED, evidence
        return EXIT_PASS, evidence

    except ScenarioError as exc:
        evidence.problems.append(str(exc))
        return exc.code, evidence
    except Exception as exc:  # noqa: BLE001 - the runner itself failing is `error`
        evidence.problems.append(f"the live acceptance runner could not complete: {exc!r}")
        return EXIT_ERROR, evidence
    finally:
        _teardown(process, pgid)
        if evidence_path is not None:
            try:
                evidence_path.parent.mkdir(parents=True, exist_ok=True)
                evidence_path.write_text(
                    json.dumps(evidence.to_dict(), indent=2), encoding="utf-8")
            except OSError:
                pass
        shutil.rmtree(workdir, ignore_errors=True)


def _teardown(process: subprocess.Popen | None, pgid: int | None) -> None:
    """Terminate the process group this runner created, and only that one.

    The group id is recorded the moment the child is spawned, and the group is
    signalled whether or not its leader is still alive: a launcher that forks a
    server and exits leaves a process holding the port, and an earlier version
    signalled nothing in exactly that case because it only acted when
    `poll()` was `None`.
    """
    if pgid is not None:
        for signal_number in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(pgid, signal_number)
            except (ProcessLookupError, PermissionError, OSError):
                break
            deadline = time.monotonic() + (20 if signal_number == signal.SIGTERM else 5)
            while time.monotonic() < deadline:
                try:
                    os.killpg(pgid, 0)
                except (ProcessLookupError, PermissionError, OSError):
                    break
                time.sleep(0.1)
            else:
                continue
            break
    if process is not None:
        try:
            process.wait(timeout=10)
        except (subprocess.TimeoutExpired, OSError):
            pass
        handle = getattr(process, "_pw_dev_log", None)
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass


def main(argv: list[str]) -> int:
    if len(argv) not in (3, 4):
        print("usage: live_acceptance.py <repo> <scenario-name> <launcher> [evidence.json]",
              file=sys.stderr)
        return EXIT_ERROR
    repo = Path(argv[0]).resolve()
    name = argv[1]
    launcher_name = argv[2]
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,63}$", name):
        print(f"live-acceptance: {name!r} is not a usable scenario name", file=sys.stderr)
        return EXIT_ERROR
    evidence_path = Path(argv[3]) if len(argv) == 4 else None

    code, evidence = execute(repo, name, launcher_name, evidence_path)
    print(f"live-acceptance[{name}]: server {evidence.base_url or '(not started)'}, "
          f"{sum(1 for s in evidence.steps if s.executed)} step(s) executed")
    for step in evidence.steps:
        state = "pass" if step.passed else ("skipped" if not step.executed else "FAIL")
        print(f"  {state:<7} {step.name} — {step.detail}")
    for problem in evidence.problems:
        print(f"live-acceptance[{name}]: {problem}", file=sys.stderr)
    verdict = {
        EXIT_PASS: "PASS — every declared step executed and passed",
        EXIT_FAIL: "FAIL — a step failed its expectation",
        EXIT_INFRA: "NOT A PASS — the server under test was not available",
        EXIT_NOT_RUN: "NOT A PASS — the scenario did not run",
        EXIT_SKIPPED: "NOT A PASS — declared steps did not execute",
        EXIT_ERROR: "NOT A PASS — the runner could not complete",
    }[code]
    print(f"live-acceptance[{name}]: {verdict}",
          file=sys.stdout if code == EXIT_PASS else sys.stderr)
    return code


if __name__ == "__main__":  # pragma: no cover - exercised as a subprocess
    raise SystemExit(main(sys.argv[1:]))
