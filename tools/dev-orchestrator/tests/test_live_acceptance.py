"""The required live acceptance path, and the difference between it and a smoke test.

Every fixture here is labelled as a fixture. The application under test is a
forty-line stdlib HTTP server written for these tests; it is not Pipewright, and
none of this is evidence that any Pipewright workflow works. What it establishes
is that the *mechanism* fails closed: a missing scenario, a dead server, a
skipped step, a failed expectation and a credential the runner did not create
are each a distinct non-pass, and an unrelated healthy server satisfies nothing.

The real Phase 18 scenario is written by Phase 18. Until it exists,
`repo:live-acceptance` records `not_run` -- which is exactly what these tests
pin down, so its absence cannot be mistaken for success.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from pw_dev.verify import live_acceptance
from pw_dev.verify.registry import Registry
from pw_dev.verify.runner import SUCCESS_OUTCOMES, VerificationRunner

RUNNER = Path(live_acceptance.__file__)

#: A labelled fixture application. It authenticates with the credentials the
#: runner generated, and reports the storage directory the runner gave it.
FIXTURE_APP = '''
"""FIXTURE application for pw-dev's live acceptance tests. Not part of Pipewright."""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer

USER = os.environ["PW_DEV_LIVE_ADMIN_USERNAME"]
PASSWORD = os.environ["PW_DEV_LIVE_ADMIN_PASSWORD"]
STORE = os.environ["FIXTURE_STORE"]
DATABASE_URL = os.environ["DATABASE_URL"]
JWT_SECRET = os.environ["AUTH_JWT_SECRET"]
TOKEN = "fixture-token-" + PASSWORD[:8]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body):
        raw = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path == "/health":
            return self._send(200, {"status": "ok"})
        if self.path == "/whoami":
            if self.headers.get("Authorization") != "Bearer " + TOKEN:
                return self._send(401, {"detail": "unauthenticated"})
            return self._send(200, {
                "user": USER,
                "store_exists": os.path.isdir(STORE),
                "database_url": DATABASE_URL,
                "home": os.environ.get("HOME", ""),
                "signed_with": JWT_SECRET[:6],
            })
        self._send(404, {"detail": "no such route"})

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        if self.path == "/login":
            if body.get("username") == USER and body.get("password") == PASSWORD:
                return self._send(200, {"access_token": TOKEN})
            return self._send(401, {"detail": "bad credentials"})
        self._send(404, {"detail": "no such route"})


os.makedirs(STORE, exist_ok=True)
if "--fail-to-start" in sys.argv:
    raise SystemExit(1)
port = int(sys.argv[sys.argv.index("--port") + 1])
HTTPServer(("127.0.0.1", port), Handler).serve_forever()
'''


def _scenario(**overrides) -> dict:
    document = {
        "schema_version": "live_acceptance/v1",
        "name": "fixture",
        "readiness": {"path": "/health", "timeout_seconds": 30},
        "steps": [
            {"name": "login", "method": "POST", "path": "/login",
             "json": {"username": "{test_username}", "password": "{test_password}"},
             "expect_status": 200, "capture": {"token": "/access_token"}},
            {"name": "authenticated-read", "method": "GET", "path": "/whoami",
             "headers": {"Authorization": "Bearer {capture:token}"},
             "expect_status": 200,
             "expect": [{"pointer": "/user", "equals": "pw-dev-acceptance"},
                        {"pointer": "/store_exists", "equals": True}]},
        ],
    }
    document.update(overrides)
    return document


@pytest.fixture
def candidate(tmp_path: Path) -> Path:
    """A checkout with the fixture application and this interpreter as its venv."""
    repo = tmp_path / "candidate"
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / ".venv" / "bin" / "python").symlink_to(sys.executable)
    (repo / "scripts" / "live-acceptance").mkdir(parents=True)
    (repo / "fixture_app.py").write_text(FIXTURE_APP, encoding="utf-8")
    # The registered check runs the copy of the runner inside the checkout it is
    # verifying, because that is the tree under test. `ALWAYS_FORBIDDEN` keeps
    # that copy identical to this one: no task may write it.
    vendored = repo / "tools" / "dev-orchestrator" / "src" / "pw_dev" / "verify"
    vendored.mkdir(parents=True)
    (vendored / "live_acceptance.py").write_text(
        RUNNER.read_text(encoding="utf-8"), encoding="utf-8")
    return repo


def write_scenario(repo: Path, name: str, document: dict) -> None:
    document = dict(document, name=name)
    (repo / "scripts" / "live-acceptance" / f"{name}.json").write_text(
        json.dumps(document, indent=1), encoding="utf-8")


LAUNCHER = "pw-dev-fixture"


def invoke(repo: Path, name: str,
           launcher: str = LAUNCHER) -> subprocess.CompletedProcess:
    return subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(RUNNER), str(repo), name, launcher],
        capture_output=True, text=True, timeout=180, check=False,
    )


# ------------------------------------------------------------------ it can pass
def test_a_complete_scenario_passes_and_records_every_step(candidate: Path, tmp_path: Path):
    write_scenario(candidate, "complete", _scenario())
    evidence_path = tmp_path / "evidence.json"
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(RUNNER), str(candidate), "complete", LAUNCHER,
         str(evidence_path)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert result.returncode == live_acceptance.EXIT_PASS, result.stderr
    assert "PASS" in result.stdout

    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert [step["name"] for step in evidence["steps"]] == ["login", "authenticated-read"]
    assert all(step["executed"] and step["passed"] for step in evidence["steps"])
    assert evidence["server_pid"] and evidence["base_url"].startswith("http://127.0.0.1:")


# -------------------------------------------------------- everything else fails
def test_a_missing_scenario_is_not_run_rather_than_passed(candidate: Path):
    result = invoke(candidate, "phase-18-time-travel")
    assert result.returncode == live_acceptance.EXIT_NOT_RUN
    assert "has not written it yet" in result.stderr


def test_an_empty_scenario_does_not_pass(candidate: Path):
    write_scenario(candidate, "empty", _scenario(steps=[]))
    result = invoke(candidate, "empty")
    assert result.returncode == live_acceptance.EXIT_NOT_RUN
    assert "declares no steps" in result.stderr


def test_a_server_that_never_starts_is_infrastructure_not_failure(candidate: Path):
    write_scenario(candidate, "dead", _scenario())
    (candidate / "fixture_app.py").write_text(
        "import sys\nraise SystemExit(1)\n", encoding="utf-8")
    result = invoke(candidate, "dead")
    assert result.returncode == live_acceptance.EXIT_INFRA
    assert "before it became ready" in result.stderr


def test_a_skipped_step_is_recorded_as_skipped(candidate: Path):
    scenario = _scenario()
    scenario["steps"][1]["skip"] = True
    write_scenario(candidate, "partial", scenario)
    result = invoke(candidate, "partial")
    assert result.returncode == live_acceptance.EXIT_SKIPPED
    assert "did not execute" in result.stderr


def test_a_failed_expectation_fails(candidate: Path):
    scenario = _scenario()
    scenario["steps"][1]["expect"][0]["equals"] = "somebody-else"
    write_scenario(candidate, "wrong", scenario)
    result = invoke(candidate, "wrong")
    assert result.returncode == live_acceptance.EXIT_FAIL
    assert "expected 'somebody-else'" in result.stderr


def test_a_scenario_cannot_ask_for_a_credential_the_runner_did_not_create(candidate: Path):
    scenario = _scenario()
    scenario["steps"][0]["json"]["password"] = "{OPERATOR_PASSWORD}"
    write_scenario(candidate, "borrowed", scenario)
    result = invoke(candidate, "borrowed")
    assert result.returncode == live_acceptance.EXIT_NOT_RUN
    assert "did not create is not available" in result.stderr


# ------------------------- the scenario does not choose the program ----------
@pytest.mark.parametrize("key,value", [
    ("launcher", {"module": "http.server", "args": ["--port", "{port}"], "cwd": "."}),
    ("env", {"DATABASE_URL": "postgresql://operator@localhost:5432/production"}),
    ("cleanup_paths", ["/etc"]),
    ("modules", ["http.server"]),
])
def test_a_scenario_that_tries_to_control_the_runner_is_refused(
        candidate: Path, key: str, value):
    """The hole this closes: a worker naming `http.server`, asserting `GET /`
    returns 200, and passing a Phase 18 acceptance gate without starting
    Pipewright at all."""
    scenario = _scenario()
    scenario[key] = value
    write_scenario(candidate, "grabby", scenario)
    result = invoke(candidate, "grabby")
    assert result.returncode == live_acceptance.EXIT_NOT_RUN
    assert "does not control" in result.stderr


def test_an_unknown_launcher_is_refused(candidate: Path):
    write_scenario(candidate, "fine", _scenario())
    result = invoke(candidate, "fine", launcher="http.server")
    assert result.returncode == live_acceptance.EXIT_NOT_RUN
    assert "is not a launcher this runner knows" in result.stderr


def test_the_registered_check_fixes_the_launcher_to_the_gateway():
    check = Registry().get("repo:live-acceptance")
    assert "pipewright-gateway" in check.argv
    assert "pw-dev-fixture" not in check.argv
    launcher = live_acceptance.LAUNCHERS["pipewright-gateway"]
    assert launcher["module"] == "uvicorn"
    assert launcher["args"][0] == "api_gateway.main:app"
    assert "api_gateway" in launcher["modules"]


def test_the_environment_is_built_by_the_runner_and_is_disposable(candidate: Path):
    """Database, storage, signing secret, HOME and TMPDIR are all per-invocation."""
    write_scenario(candidate, "env", _scenario(steps=[
        {"name": "login", "method": "POST", "path": "/login",
         "json": {"username": "{test_username}", "password": "{test_password}"},
         "expect_status": 200, "capture": {"token": "/access_token"}},
        {"name": "inspect", "method": "GET", "path": "/whoami",
         "headers": {"Authorization": "Bearer {capture:token}"},
         "expect_status": 200,
         "expect": [{"pointer": "/store_exists", "equals": True}]},
    ]))
    evidence_path = candidate / "evidence.json"
    result = subprocess.run(  # noqa: S603 - fixed argv
        [sys.executable, str(RUNNER), str(candidate), "env", LAUNCHER,
         str(evidence_path)],
        capture_output=True, text=True, timeout=180, check=False,
    )
    assert result.returncode == live_acceptance.EXIT_PASS, result.stderr


def test_a_scenario_cannot_read_the_signing_secret_or_a_host_path(candidate: Path):
    """`{workdir}`, `{repo}`, `{port}` and `{jwt_secret}` are not scenario placeholders."""
    for placeholder in ("{workdir}", "{repo}", "{jwt_secret}", "{port}"):
        scenario = _scenario()
        scenario["steps"][0]["json"]["password"] = placeholder
        write_scenario(candidate, "peeking", scenario)
        result = invoke(candidate, "peeking")
        assert result.returncode == live_acceptance.EXIT_NOT_RUN, placeholder
        assert "does not provide" in result.stderr


def test_a_checkout_with_no_virtualenv_does_not_pass(tmp_path: Path):
    repo = tmp_path / "bare"
    (repo / "scripts" / "live-acceptance").mkdir(parents=True)
    write_scenario(repo, "novenv", _scenario())
    result = invoke(repo, "novenv")
    assert result.returncode == live_acceptance.EXIT_NOT_RUN
    assert "no server can be started from this checkout" in result.stderr


def test_a_module_resolving_outside_the_candidate_does_not_pass(tmp_path: Path):
    """A borrowed virtualenv imports another checkout's code.

    That is how a "disposable" run reaches the operator's real database:
    `api_gateway.config` loads `apps/api-gateway/.env` relative to the module
    file, so importing the original checkout's gateway reads the original
    checkout's settings. Refused before the server starts.
    """
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "fixture_app.py").write_text("VALUE = 1\n", encoding="utf-8")

    repo = tmp_path / "borrowed"
    (repo / ".venv" / "bin").mkdir(parents=True)
    (repo / "scripts" / "live-acceptance").mkdir(parents=True)
    # An interpreter that resolves the application from outside this checkout,
    # exactly as a symlinked virtualenv with editable installs would.
    shim = repo / ".venv" / "bin" / "python"
    shim.write_text(
        f'#!/bin/sh\nPYTHONPATH="{elsewhere}" exec "{sys.executable}" "$@"\n',
        encoding="utf-8")
    shim.chmod(0o755)
    write_scenario(repo, "borrowed", _scenario())

    result = invoke(repo, "borrowed")
    assert result.returncode == live_acceptance.EXIT_NOT_RUN
    assert "does not run this checkout's code" in result.stderr
    assert "outside the candidate" in result.stderr


def test_a_forked_server_that_outlives_its_launcher_is_still_reaped(candidate: Path):
    """Teardown signals the process group, not only a leader that is still alive."""
    (candidate / "fixture_app.py").write_text(
        "import os, sys, subprocess\n"
        "here = os.path.dirname(os.path.abspath(__file__))\n"
        "subprocess.Popen([sys.executable, os.path.join(here, 'real_app.py'), *sys.argv[1:]])\n"
        "raise SystemExit(0)\n",
        encoding="utf-8")
    (candidate / "real_app.py").write_text(FIXTURE_APP, encoding="utf-8")
    write_scenario(candidate, "forked", _scenario())

    before = _python_children()
    result = invoke(candidate, "forked")
    time.sleep(1.5)
    leaked = _python_children() - before
    assert not any("real_app" in line for line in leaked), leaked
    assert result.returncode != live_acceptance.EXIT_PASS


# ----------------------------------------- an unrelated server satisfies nothing
def test_a_healthy_unrelated_server_does_not_satisfy_the_check(candidate: Path):
    """The failure `repo:smoke` has: something answers, so something passed."""
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            raw = b'{"status":"ok"}'
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    server = HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            with socket.socket() as check:
                if check.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.05)
        # No scenario: a healthy server on a port changes nothing.
        assert invoke(candidate, "absent").returncode == live_acceptance.EXIT_NOT_RUN
    finally:
        server.shutdown()
        server.server_close()


# ---------------------------------------------------- registry and outcome wiring
def test_the_registry_separates_optional_smoke_from_required_live():
    registry = Registry()
    assert registry.get("repo:smoke").evidence_class == "optional_smoke"
    assert registry.get("repo:live-acceptance").evidence_class == "required_live"
    assert [c.id for c in registry.of_class("required_live")] == ["repo:live-acceptance"]


def test_the_live_check_maps_its_exit_codes_to_distinct_non_pass_outcomes():
    check = Registry().get("repo:live-acceptance")
    assert check.exit_outcomes == {20: "infra_unavailable", 21: "not_run", 22: "skip",
                                   2: "error"}
    assert not set(check.exit_outcomes.values()) & SUCCESS_OUTCOMES


def test_an_unparameterised_check_is_not_run_rather_than_executed_literally(
        store, tmp_path: Path, candidate: Path):
    """`{scenario}` with nothing bound must not become a literal argument."""
    runner = VerificationRunner(
        Registry(), store=store, run_id=store.create_run(
            brain="automatic", config_snapshot={}, publication_mode="none",
            deadline_epoch=None, plan_only=True),
        base_commit="0" * 40, spec_digest="d", artifacts_dir=tmp_path / "ev",
    )
    record = runner.run_check("repo:live-acceptance", checkout=candidate,
                              candidate_fingerprint="f")
    assert record["outcome"] == "not_run"
    assert "scenario" in record["detail"]


def test_a_bound_scenario_that_does_not_exist_records_not_run(
        store, tmp_path: Path, candidate: Path):
    run_id = store.create_run(brain="automatic", config_snapshot={},
                              publication_mode="none", deadline_epoch=None, plan_only=True)
    runner = VerificationRunner(
        Registry(), store=store, run_id=run_id, base_commit="0" * 40, spec_digest="d",
        artifacts_dir=tmp_path / "ev", parameters={"scenario": "phase-18-time-travel"},
    )
    record = runner.run_check("repo:live-acceptance", checkout=candidate,
                              candidate_fingerprint="f")
    assert record["outcome"] == "not_run"
    assert record["outcome"] not in SUCCESS_OUTCOMES


def test_the_registered_check_will_not_accept_a_checkout_that_is_not_pipewright(
        store, tmp_path: Path, candidate: Path):
    """A scenario existing is not enough; the gateway has to be importable here.

    The fixture candidate has a scenario and a working fixture application, and
    the registered check still records `not_run` -- because the launcher it is
    fixed to is the Pipewright gateway, and this checkout cannot import it. That
    is the property that stops a scenario choosing an easier program.
    """
    write_scenario(candidate, "phase-99-fixture", _scenario())
    run_id = store.create_run(brain="automatic", config_snapshot={},
                              publication_mode="none", deadline_epoch=None, plan_only=True)
    runner = VerificationRunner(
        Registry(), store=store, run_id=run_id, base_commit="0" * 40, spec_digest="d",
        artifacts_dir=tmp_path / "ev", parameters={"scenario": "phase-99-fixture"},
    )
    record = runner.run_check("repo:live-acceptance", checkout=candidate,
                              candidate_fingerprint="f")
    assert record["outcome"] == "not_run"
    assert "api_gateway" in record["detail"]


def test_the_scenario_parameter_comes_from_the_specification_not_a_worker(tmp_path: Path):
    from pw_dev.controller.run import Controller

    controller = Controller.__new__(Controller)
    controller.spec = {"phase_id": "18-time-travel"}
    assert controller.check_parameters() == {"scenario": "18-time-travel"}
    controller.spec = {"phase_id": "Phase 18/../etc"}
    assert controller.check_parameters()["scenario"] == "phase-18-etc"


def test_teardown_removes_only_what_this_invocation_created(
        candidate: Path, tmp_path: Path):
    marker = tmp_path / "not-mine.txt"
    marker.write_text("keep me", encoding="utf-8")
    write_scenario(candidate, "cleanup", _scenario())
    assert invoke(candidate, "cleanup").returncode == live_acceptance.EXIT_PASS
    assert marker.read_text(encoding="utf-8") == "keep me"
    assert not list(Path(tempfile.gettempdir()).glob("pw-dev-live-cleanup-*")), (
        "the temporary work directory is removed"
    )


def test_the_runner_leaves_no_child_process_behind(candidate: Path):
    write_scenario(candidate, "tidy", _scenario())
    before = _python_children()
    assert invoke(candidate, "tidy").returncode == live_acceptance.EXIT_PASS
    time.sleep(1.0)
    leaked = _python_children() - before
    assert not any("fixture_app" in line for line in leaked), leaked


def _python_children() -> set[str]:
    listing = subprocess.run(  # noqa: S603 - fixed argv
        ["/bin/ps", "-o", "command="], capture_output=True, text=True, check=False,
    )
    return {line for line in listing.stdout.splitlines() if "fixture_app" in line}


def test_the_runner_is_inside_the_never_writable_verification_package():
    from pw_dev.workspace.guard import PathGuard, PathViolation

    relative = "tools/dev-orchestrator/src/pw_dev/verify/live_acceptance.py"
    with pytest.raises(PathViolation, match="forbidden"):
        PathGuard(["**"]).check(relative)
    assert os.path.basename(str(RUNNER)) == "live_acceptance.py"


# ============ a required live gate may not be waived as "pre-existing" ========
def test_a_plan_cannot_scope_out_the_required_live_gate(config):
    """The waiver that defeated the whole mechanism.

    A scenario that has not been written is `not_run` at baseline, so the
    general "this check was already failing" allowance would waive the one gate
    whose entire purpose is that a missing scenario cannot pass.
    """
    from pw_dev.controller.validate_plan import validate_plan
    from pw_dev.testing import make_spec

    spec = make_spec(
        required_verifications=["repo:live-acceptance"],
        accepted_preexisting_failures=[
            {"verification_id": "repo:live-acceptance",
             "reason": "the scenario does not exist yet"},
        ],
    )
    spec["tasks"][0]["verification_ids"] = ["repo:live-acceptance"]
    report = validate_plan(spec, config=config, registry=Registry(),
                           base_commit=spec["base_commit"], repo_root=config.repo_root)
    assert not report.ok
    error = next(e for e in report.errors if "accepted_preexisting_failures" in e)
    assert "waives the gate" in error
    assert "Write the scenario, or stop requiring the check" in error


def test_an_ordinary_check_may_still_be_scoped_out(config):
    from pw_dev.controller.validate_plan import validate_plan
    from pw_dev.testing import make_spec

    spec = make_spec(
        required_verifications=["connectors:servers"],
        accepted_preexisting_failures=[
            {"verification_id": "connectors:servers",
             "reason": "no database servers on this machine; CI runs them"},
        ],
    )
    assert validate_plan(spec, config=config, registry=Registry(),
                         base_commit=spec["base_commit"],
                         repo_root=config.repo_root).ok


def test_the_run_loop_refuses_the_waiver_even_for_an_imported_specification():
    """Defence in depth: a specification can arrive by import, past validation."""
    from pw_dev.controller.run import Controller
    from pw_dev.testing import make_spec
    from pw_dev.verify.registry import registry_for

    controller = Controller.__new__(Controller)
    controller.registry = registry_for("pipewright")
    controller.notes = []
    controller.spec = make_spec(
        required_verifications=["repo:live-acceptance", "connectors:servers"],
        accepted_preexisting_failures=[
            {"verification_id": "repo:live-acceptance", "reason": "not written yet"},
            {"verification_id": "connectors:servers", "reason": "no servers here"},
        ],
    )
    controller.baseline = {"repo:live-acceptance": "not_run",
                           "connectors:servers": "infra_unavailable"}
    controller.final_records = {"repo:live-acceptance": {"outcome": "not_run"},
                                "connectors:servers": {"outcome": "infra_unavailable"}}

    outstanding = controller.outstanding_gate_failures()
    assert any("repo:live-acceptance" in entry for entry in outstanding), (
        "a missing live scenario must still block"
    )
    assert not any("connectors:servers" in entry for entry in outstanding), (
        "an ordinary stated pre-existing failure is still scoped out"
    )
    assert any("was not waived" in note for note in controller.notes)
