"""Executes registry checks and records evidence.

The distinctions this module refuses to collapse:

* **pass** -- the command ran and reported success;
* **fail** -- it ran and reported failure;
* **skip** -- it ran, and cases inside it were skipped. Not a pass;
* **not_run** -- it never executed, because a prerequisite was absent;
* **infra_unavailable** -- an external service the check needs was not there.
  This is the one that would otherwise masquerade as a green local run when CI
  is testing against real PostgreSQL, MySQL and MariaDB;
* **timeout** -- it was killed. Whether it would have passed is unknown;
* **error** -- the runner itself could not execute it.

Every record carries the candidate fingerprint, base commit, specification
digest and an environment digest, so a check run against yesterday's tree cannot
be counted toward today's gate.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..schemas.validate import validate_artifact
from ..util import proc
from ..util.hashing import digest_json, digest_text
from ..util.jsonio import utc_now
from ..util.redact import redact
from .registry import Check, Registry


class Outcome:
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"
    NOT_RUN = "not_run"
    INFRA_UNAVAILABLE = "infra_unavailable"
    TIMEOUT = "timeout"
    ERROR = "error"


#: Outcomes that let a gate close. Exactly one of them.
SUCCESS_OUTCOMES = frozenset({Outcome.PASS})

_PYTEST_SUMMARY = re.compile(
    r"(?m)^=+ .*?(?P<body>\d+ (?:passed|failed|error|skipped).*?) =+\s*$"
)
_SKIP_COUNT = re.compile(r"(?<!\w)(\d+)\s+skipped")
_FAIL_COUNT = re.compile(r"(?<!\w)(\d+)\s+(?:failed|error(?:s|ed)?)")


@dataclass
class EnvironmentFacts:
    """What produced a result, recorded so two results can be compared."""

    python: str | None
    python_executable: str | None
    node: str | None
    platform: str
    resolved_modules: list[dict]

    def digest(self) -> str:
        return digest_json({
            "python": self.python, "python_executable": self.python_executable,
            "node": self.node, "platform": self.platform,
            "resolved_modules": self.resolved_modules,
        })

    def to_dict(self) -> dict:
        return {
            "python": self.python, "python_executable": self.python_executable,
            "node": self.node, "platform": self.platform,
            "resolved_modules": self.resolved_modules,
        }


class VerificationRunner:
    """Runs vetted checks against a specific checkout and records the result."""

    def __init__(
        self, registry: Registry, *, store, run_id: str, base_commit: str,
        spec_digest: str, artifacts_dir: Path,
    ) -> None:
        self.registry = registry
        self.store = store
        self.run_id = run_id
        self.base_commit = base_commit
        self.spec_digest = spec_digest
        self.artifacts_dir = Path(artifacts_dir)
        self.artifacts_dir.mkdir(parents=True, exist_ok=True)
        self._env_cache: dict[str, EnvironmentFacts] = {}

    # ------------------------------------------------------------- execution
    def run_check(
        self, check: Check | str, *, checkout: Path, candidate_fingerprint: str,
        task_id: str | None = None, cancel_check: Callable[[], bool] | None = None,
        modules_to_resolve: tuple[str, ...] = ("shared_python", "api_gateway"),
    ) -> dict:
        if isinstance(check, str):
            check = self.registry.get(check)
        checkout = Path(checkout).resolve()
        argv, cwd = check.render(checkout)
        facts = self._environment(checkout, modules_to_resolve)
        started = utc_now()

        document = {
            "schema_version": "verification_evidence/v1",
            "evidence_id": f"ev-{uuid.uuid4().hex[:16]}",
            "run_id": self.run_id,
            "task_id": task_id,
            "verification_id": check.id,
            "outcome": Outcome.NOT_RUN,
            "command": argv,
            "cwd": str(cwd),
            "exit_status": None,
            "started_at": started,
            "finished_at": None,
            "duration_seconds": None,
            "output_digest": None,
            "output_bytes": 0,
            "truncated": False,
            "candidate_fingerprint": candidate_fingerprint,
            "base_commit": self.base_commit,
            "spec_digest": self.spec_digest,
            "environment_digest": facts.digest(),
            "environment": facts.to_dict(),
            "detail": None,
        }

        missing = self._missing_prerequisites(check, checkout)
        if missing:
            document["outcome"] = Outcome.NOT_RUN
            document["finished_at"] = utc_now()
            document["detail"] = (
                f"prerequisites absent: {', '.join(missing)}. The check did not execute, "
                f"which is not the same as passing."
            )
            return self._record(document)

        unavailable = self._unavailable_infra(check, checkout)
        if unavailable:
            document["outcome"] = Outcome.INFRA_UNAVAILABLE
            document["finished_at"] = utc_now()
            document["detail"] = (
                f"required services unreachable: {', '.join(unavailable)}."
                + (f" {check.infra_note}" if check.infra_note else "")
            )
            return self._record(document)

        env = proc.build_env(overrides={
            # Each checkout gets its own caches and temp space, so two
            # concurrent runs do not share a Next.js build cache or a pytest
            # cache directory and report each other's results.
            "TMPDIR": str(self._scratch(checkout, "tmp")),
            "PYTEST_ADDOPTS": "-p no:cacheprovider",
            # Running the tests to verify a tree is not a change to that tree.
            # Without this, every check drops __pycache__ into the candidate.
            "PYTHONDONTWRITEBYTECODE": "1",
            "NEXT_TELEMETRY_DISABLED": "1",
            "CI": "1",
            "npm_config_cache": str(self._scratch(checkout, "npm-cache")),
            # A per-checkout namespace for anything that wants one, so parallel
            # runs do not write the same database or storage directory.
            "PW_DEV_RUN_NAMESPACE": f"{self.run_id}-{task_id or 'candidate'}",
            **check.env,
        })

        try:
            result = proc.run(
                argv, cwd=cwd, env=env, timeout=check.timeout_seconds,
                max_output_bytes=16 * 1024 * 1024, cancel_check=cancel_check,
            )
        except (FileNotFoundError, OSError) as exc:
            document["outcome"] = Outcome.ERROR
            document["finished_at"] = utc_now()
            document["detail"] = f"the runner could not execute the command: {exc}"
            return self._record(document)

        body = redact(f"$ {' '.join(argv)}\n(cwd: {cwd})\n\n--- stdout ---\n{result.stdout}"
                      f"\n--- stderr ---\n{result.stderr}\n")
        output_path = self.artifacts_dir / f"{document['evidence_id']}.log"
        output_path.write_text(body, encoding="utf-8")

        document.update({
            "exit_status": result.returncode,
            "finished_at": utc_now(),
            "duration_seconds": result.duration_seconds,
            "output_digest": digest_text(body),
            "output_bytes": len(body.encode("utf-8")),
            "truncated": result.truncated,
        })

        if result.cancelled:
            document["outcome"] = Outcome.NOT_RUN
            document["detail"] = "cancelled before the check finished"
        elif result.timed_out:
            document["outcome"] = Outcome.TIMEOUT
            document["detail"] = (
                f"killed after {check.timeout_seconds}s. Whether it would have passed is "
                f"unknown; the process group was terminated."
            )
        elif result.returncode != 0:
            document["outcome"] = Outcome.FAIL
            document["detail"] = _failure_detail(result)
        else:
            skipped = _skip_count(result.stdout + result.stderr)
            if skipped:
                document["outcome"] = Outcome.SKIP
                document["detail"] = (
                    f"the command succeeded with {skipped} skipped case(s). Recorded as "
                    f"'skip' so it cannot be read as full coverage."
                    + (f" {check.infra_note}" if check.infra_note else "")
                )
            else:
                document["outcome"] = Outcome.PASS
                document["detail"] = _success_detail(result)

        return self._record(document)

    def run_many(
        self, check_ids: list[str], *, checkout: Path, candidate_fingerprint: str,
        task_id: str | None = None, stop_on_fail: bool = False,
        cancel_check: Callable[[], bool] | None = None,
        on_start: Callable[[str], None] | None = None,
    ) -> list[dict]:
        records: list[dict] = []
        for check_id in check_ids:
            if on_start is not None:
                on_start(check_id)
            record = self.run_check(
                check_id, checkout=checkout, candidate_fingerprint=candidate_fingerprint,
                task_id=task_id, cancel_check=cancel_check,
            )
            records.append(record)
            if stop_on_fail and record["outcome"] not in SUCCESS_OUTCOMES:
                break
        return records

    # ------------------------------------------------------------- baselines
    def capture_baseline(
        self, check_ids: list[str], *, checkout: Path, candidate_fingerprint: str,
        on_start: Callable[[str], None] | None = None,
    ) -> dict[str, str]:
        """Record how required checks behave *before* any change.

        A check that was already failing stays visible. It does not become a
        success because the phase happened to touch a different file, and it is
        not silently attributed to this run's work either.
        """
        baseline: dict[str, str] = {}
        for record in self.run_many(
            check_ids, checkout=checkout, candidate_fingerprint=candidate_fingerprint,
            task_id=None, on_start=on_start,
        ):
            baseline[record["verification_id"]] = record["outcome"]
        return baseline

    # --------------------------------------------------------------- helpers
    def _record(self, document: dict) -> dict:
        validate_artifact(document, "verification_evidence/v1")
        self.store.record_evidence(document)
        return document

    def _scratch(self, checkout: Path, name: str) -> Path:
        path = checkout / ".pw-dev-scratch" / name
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _missing_prerequisites(self, check: Check, checkout: Path) -> list[str]:
        missing: list[str] = []
        for requirement in check.requires:
            if requirement == "venv" and not (checkout / ".venv" / "bin" / "python").exists():
                missing.append(f"{checkout}/.venv")
            elif requirement == "node_modules" and not (checkout / "node_modules").is_dir():
                missing.append(f"{checkout}/node_modules")
            elif requirement == "npm" and shutil.which("npm") is None:
                missing.append("npm on PATH")
        return missing

    def _unavailable_infra(self, check: Check, checkout: Path) -> list[str]:
        """Probe the services a check needs, by connecting to them."""
        if not check.infra:
            return []
        import socket

        targets = {
            "postgres": ("CONNECTORS_TEST_POSTGRES_URL", 5432),
            "mysql": ("CONNECTORS_TEST_MYSQL_URL", 3306),
            "mariadb": ("CONNECTORS_TEST_MARIADB_URL", 3307),
        }
        unavailable: list[str] = []
        for service in check.infra:
            env_name, default_port = targets.get(service, (None, None))
            if default_port is None:
                continue
            port = default_port
            url = os.environ.get(env_name or "", "")
            if url:
                match = re.search(r":(\d+)/", url)
                if match:
                    port = int(match.group(1))
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(2.0)
                if sock.connect_ex(("127.0.0.1", port)) != 0:
                    unavailable.append(f"{service} (127.0.0.1:{port})")
        return unavailable

    def _environment(self, checkout: Path, modules: tuple[str, ...]) -> EnvironmentFacts:
        key = str(checkout)
        cached = self._env_cache.get(key)
        if cached is not None:
            return cached

        python_exe = checkout / ".venv" / "bin" / "python"
        python_version: str | None = None
        resolved: list[dict] = []
        if python_exe.exists():
            probe = (
                "import json,sys,importlib.util as u;"
                "print(json.dumps({'v':sys.version.split()[0],'exe':sys.executable,"
                "'m':{m:(u.find_spec(m).origin if u.find_spec(m) else None) for m in "
                f"{list(modules)!r}" "}}))"
            )
            try:
                result = proc.run(
                    [str(python_exe), "-c", probe], cwd=checkout,
                    env=proc.build_env(), timeout=120, max_output_bytes=1 << 20,
                )
                if result.ok:
                    import json as _json

                    payload = _json.loads(result.stdout.strip().splitlines()[-1])
                    python_version = payload["v"]
                    resolved = [
                        {"module": name, "origin": origin}
                        for name, origin in sorted(payload["m"].items())
                    ]
            except (OSError, ValueError, KeyError, IndexError):
                pass

        node_version: str | None = None
        if shutil.which("node"):
            try:
                result = proc.run(["node", "--version"], cwd=checkout,
                                  env=proc.build_env(), timeout=60, max_output_bytes=1 << 16)
                node_version = result.stdout.strip() or None
            except (OSError, ValueError):
                pass

        facts = EnvironmentFacts(
            python=python_version,
            python_executable=str(python_exe) if python_exe.exists() else sys.executable,
            node=node_version,
            platform=f"{platform.system()} {platform.release()} {platform.machine()}",
            resolved_modules=resolved,
        )
        self._env_cache[key] = facts
        return facts

    def check_module_isolation(self, checkout: Path, modules: tuple[str, ...]) -> list[str]:
        """Complaints about modules importing from outside this checkout.

        Pipewright installs its service packages with `pip install -e`. A venv
        created in one worktree resolves those packages to *that* worktree's
        source, so running a second worktree's tests against it verifies the
        wrong code and reports a pass. This is what catches it.
        """
        checkout = Path(checkout).resolve()
        facts = self._environment(checkout, modules)
        problems: list[str] = []
        if not facts.resolved_modules:
            # Reporting "no problems" here would be the exact false clean this
            # check exists to prevent: an unanswerable question is not a pass.
            return [
                f"module origins could not be determined for {checkout}: no usable "
                f"{checkout}/.venv/bin/python. Checks run here would record 'not_run', and "
                f"whether they would test this checkout's code is unknown."
            ]
        for entry in facts.resolved_modules:
            origin = entry["origin"]
            if not origin:
                problems.append(f"{entry['module']} is not importable in {checkout}/.venv")
                continue
            try:
                Path(origin).resolve().relative_to(checkout)
            except ValueError:
                problems.append(
                    f"{entry['module']} resolves to {origin}, outside {checkout}. "
                    f"This environment is testing another checkout's code."
                )
        return problems


def _skip_count(output: str) -> int:
    match = _PYTEST_SUMMARY.search(output)
    body = match.group("body") if match else output[-4000:]
    skips = _SKIP_COUNT.search(body)
    if not skips:
        return 0
    if _FAIL_COUNT.search(body):
        return 0  # a failure is reported as a failure, not as a skip
    return int(skips.group(1))


def _failure_detail(result: proc.ProcResult) -> str:
    match = _PYTEST_SUMMARY.search(result.stdout)
    if match:
        return redact(match.group("body"))[:400]
    tail = (result.stderr or result.stdout).strip().splitlines()[-6:]
    return redact(" | ".join(tail))[:400] or f"exit {result.returncode}"


def _success_detail(result: proc.ProcResult) -> str:
    match = _PYTEST_SUMMARY.search(result.stdout)
    if match:
        return redact(match.group("body"))[:400]
    return f"exit 0 in {result.duration_seconds:.1f}s"
