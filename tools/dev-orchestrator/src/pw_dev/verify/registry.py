"""The verification registry.

An agent may ask for `web:typecheck`. It may not ask the controller to run a
command. The mapping from an ID to an argument array lives here, in controller
code that no task is allowed to write (see `workspace.guard.ALWAYS_FORBIDDEN`),
because an agent that can edit the command behind a check can make every check
pass.

Checks are grouped so a worker iterating on one service pays for one service,
while the integrated candidate pays for the whole gate.
"""

from __future__ import annotations

import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..errors import PolicyViolation

_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_.:-]{1,63}$")


@dataclass(frozen=True)
class Check:
    """One vetted command.

    `argv` is a fixed list. Nothing interpolates model output into it; the only
    substitution is `{repo}`, replaced with the checkout the check runs against.
    """

    id: str
    description: str
    argv: tuple[str, ...]
    cwd: str = "{repo}"
    timeout_seconds: int = 1800
    requires: tuple[str, ...] = ()
    infra: tuple[str, ...] = ()
    # Treated as evidence of a *gate*, not of one file. Required checks are what
    # the integrated candidate must pass.
    gate: bool = False
    env: dict[str, str] = field(default_factory=dict)
    # A check whose absence of infrastructure is reported rather than skipped
    # silently. `npm run verify` locally is not the same coverage as CI, which
    # brings up PostgreSQL, MySQL and MariaDB.
    infra_note: str | None = None
    # What a result from this check is worth. `gate` closes a completion gate;
    # `optional_smoke` is a diagnostic that cannot stand in for one; `required_live`
    # is an end-to-end acceptance path that only counts when a plan requires it.
    # Stated here so `pw-dev checks` and plan validation can say which is which
    # instead of leaving a reader to infer it from a name.
    evidence_class: str = "standard"
    # Exit statuses this check gives a specific meaning. Everything unmapped is
    # the usual pass/fail. A runner that collapsed "no scenario" and "a step
    # failed" into one word would hide which of them happened.
    exit_outcomes: dict[int, str] = field(default_factory=dict)
    # A pattern the output must contain before exit zero counts as a pass.
    #
    # Exit zero on its own says a process ended without complaining, which is
    # also what `os._exit(0)` says. Verification runs code the phase is
    # writing -- that is what verification *is* -- so the defence is not to stop
    # it running but to stop silence counting as a result: a pytest run that
    # passed says so, and one that vanished cannot.
    success_pattern: str | None = None

    def render(self, repo: Path,
               parameters: dict[str, str] | None = None) -> tuple[list[str], Path]:
        """Bind `{repo}` and any controller-supplied parameters.

        Parameters come from the controller -- the run's specification, not a
        model's message -- and each value is put through `normalise` before it
        reaches an argument. A token left unbound stays in the argv verbatim so
        the caller can refuse to run rather than execute a literal `{scenario}`.
        """
        from ..workspace.guard import normalise

        bindings = {"repo": str(repo)}
        for name, value in (parameters or {}).items():
            bindings[name] = normalise(str(value))

        def bind(text: str) -> str:
            for name, value in bindings.items():
                text = text.replace("{" + name + "}", value)
            return text

        return [bind(token) for token in self.argv], Path(bind(self.cwd))

    def unbound_tokens(self, argv: list[str]) -> list[str]:
        """Placeholders still present after rendering."""
        seen: list[str] = []
        for token in argv:
            for match in re.finditer(r"\{([a-z_][a-z0-9_]*)\}", token):
                if match.group(1) not in seen:
                    seen.append(match.group(1))
        return seen


def _runner() -> str:
    """Where this installation keeps the live-acceptance runner."""
    return str((Path(__file__).parent / "live_acceptance.py").resolve())


def _venv(repo_token: str = "{repo}") -> str:
    return f"{repo_token}/.venv/bin/python"


#: pytest's own summary line. A run that produced no summary did not finish,
#: whatever it exited with.
_PYTEST_RAN = r"\d+ (?:passed|failed|error|skipped|deselected|xfailed|xpassed)"


#: Pipewright's checks, read from `scripts/test.sh`, `scripts/verify-release.sh`
#: and `.github/workflows/ci.yml` on 2026-09-17 rather than invented.
PIPEWRIGHT_CHECKS: tuple[Check, ...] = (
    Check(
        id="python:ruff",
        description="Ruff over the gateway, services and shared-python (same paths as verify-release.sh)",
        argv=(f"{_venv()}", "-m", "ruff", "check",
              "apps/api-gateway/src", "services", "packages/shared-python/src"),
        timeout_seconds=600,
        requires=("venv",),
    ),
    Check(
        id="python:tests",
        description="The repository's pytest bundle (scripts/test.sh, Python half)",
        argv=(f"{_venv()}", "-m", "pytest", "--import-mode=importlib", "-q",
              "apps/api-gateway/tests",
              "packages/shared-python/tests",
              "services/service-auth/tests",
              "services/service-access/tests",
              "services/service-enterprise/tests",
              "services/service-governance/tests",
              "services/service-projects/tests",
              "services/service-sources/tests",
              "services/service-datasets/tests",
              "services/service-pipeline-runs/tests",
              "services/service-comparisons/tests",
              "services/service-destinations/tests",
              "services/service-ingestion/tests",
              "services/service-transformations/tests",
              "services/service-quality/tests",
              "services/service-extraction/tests",
              "services/service-writeback/tests",
              "services/service-workbench/tests",
              "services/service-connectors/tests",
              "services/service-reporting/tests",
              "services/service-workflows/tests",
              "services/service-lineage/tests",
              "services/service-intelligence/tests",
              "services/service-observability/tests",
              "services/service-schedules/tests",
              "services/service-notifications/tests"),
        timeout_seconds=3600,
        requires=("venv",),
        success_pattern=_PYTEST_RAN,
    ),
    Check(
        id="python:service",
        description="One service's tests. The service is chosen by the caller, not by an agent.",
        argv=(f"{_venv()}", "-m", "pytest", "-q", "--import-mode=importlib", "{service_path}"),
        timeout_seconds=1200,
        requires=("venv",),
        success_pattern=_PYTEST_RAN,
    ),
    Check(
        id="orchestrator:ruff",
        description="Ruff over the development orchestrator itself",
        argv=(f"{_venv()}", "-m", "ruff", "check", "tools/dev-orchestrator/src", "tools/dev-orchestrator/tests"),
        timeout_seconds=300,
        requires=("venv",),
        gate=True,
    ),
    Check(
        id="orchestrator:tests",
        description="The orchestrator's own test suite",
        argv=(f"{_venv()}", "-m", "pytest", "-q", "--import-mode=importlib",
              "tools/dev-orchestrator/tests"),
        timeout_seconds=1800,
        requires=("venv",),
        gate=True,
        success_pattern=_PYTEST_RAN,
    ),
    Check(
        id="web:lint",
        description="ESLint for @platform/web",
        argv=("npm", "run", "lint", "--workspace", "@platform/web"),
        timeout_seconds=900,
        requires=("node_modules",),
    ),
    Check(
        id="web:typecheck",
        description="tsc --noEmit for @platform/web",
        argv=("npm", "run", "typecheck", "--workspace", "@platform/web"),
        timeout_seconds=900,
        requires=("node_modules",),
    ),
    Check(
        id="web:tests",
        description="Vitest for @platform/web",
        argv=("npm", "run", "test", "--workspace", "@platform/web"),
        timeout_seconds=1800,
        requires=("node_modules",),
    ),
    Check(
        id="web:build",
        description="The production Next.js build",
        argv=("npm", "run", "build", "--workspace", "@platform/web"),
        timeout_seconds=2400,
        requires=("node_modules",),
    ),
    Check(
        id="repo:verify",
        description="npm run verify -- the repository's full release gate (ruff, pytest, ESLint, tsc, build)",
        argv=("npm", "run", "verify"),
        timeout_seconds=5400,
        requires=("venv", "node_modules"),
        gate=True,
        success_pattern=_PYTEST_RAN,
    ),
    Check(
        id="repo:smoke",
        description=(
            "scripts/smoke-test.sh -- an OPTIONAL diagnostic: repository layout, then health "
            "probes against whatever answers SMOKE_API_ROOT. It exits 0 offline, and a "
            "gateway started from another checkout satisfies it, so it is not acceptance "
            "evidence for an authenticated workflow. Use repo:live-acceptance for that"
        ),
        argv=("bash", "./scripts/smoke-test.sh"),
        timeout_seconds=1200,
        requires=("venv",),
        evidence_class="optional_smoke",
    ),
    Check(
        id="repo:live-acceptance",
        description=(
            "REQUIRED live acceptance: proves this checkout's own code is what runs, "
            "starts the gateway from it on an ephemeral port with a disposable database, "
            "storage, signing secret and test credentials, runs every step of "
            "scripts/live-acceptance/<scenario>.json, and fails closed. A missing scenario "
            "records not_run, unreachable infrastructure records infra_unavailable, a "
            "skipped step records skip -- none of which is a pass"
        ),
        # The launcher is a literal here, in controller-owned code. It is not a
        # parameter and not a scenario field: a worker who could choose what to
        # start could satisfy this gate with `python -m http.server`.
        # The runner is *this* installation's copy, not the candidate's. It is
        # controller-owned verification code, and a candidate is built from a
        # base commit that may predate it -- so running the candidate's copy
        # meant running whatever version of the gate that base happened to
        # carry. A defect the controller had already fixed was still being
        # reported, and the repair worker, shown a problem that no longer
        # existed, changed the product to satisfy it.
        #
        # The candidate is the *subject*: it is passed as an argument, its
        # interpreter starts the server, and its scenario is what runs.
        argv=(sys.executable, _runner(),
              "{repo}", "{scenario}", "pipewright-gateway",
              "{repo}/.pw-dev-scratch/live-acceptance-evidence.json"),
        timeout_seconds=1800,
        requires=("venv",),
        evidence_class="required_live",
        exit_outcomes={20: "infra_unavailable", 21: "not_run", 22: "skip", 2: "error"},
    ),
    Check(
        id="connectors:servers",
        description=(
            "CI-equivalent connector coverage: PostgreSQL, MySQL and MariaDB must be "
            "reachable, as CI requires before it runs verification"
        ),
        argv=(f"{_venv()}", "./scripts/check-connector-servers.py"),
        timeout_seconds=300,
        requires=("venv",),
        infra=("postgres", "mysql", "mariadb"),
        infra_note=(
            "CI starts these three servers and fails if they are unreachable. A local run "
            "without them is not equivalent coverage: the container-backed connector tests "
            "skip, and a skip is not a pass."
        ),
    ),
    Check(
        id="alembic:heads",
        description=(
            "Exactly one Alembic head, asserted against the revision graph -- catches two "
            "workers allocating parallel revisions. `alembic heads` alone does not: it exits "
            "0 with two heads and with none"
        ),
        argv=(f"{_venv()}", "{repo}/tools/dev-orchestrator/src/pw_dev/verify/alembic_heads.py",
              "{repo}/apps/api-gateway"),
        timeout_seconds=300,
        requires=("venv",),
        gate=True,
    ),
)


class Registry:
    """Resolves IDs to commands. Unknown IDs are refused, never guessed."""

    def __init__(self, checks: tuple[Check, ...] = PIPEWRIGHT_CHECKS) -> None:
        self._checks: dict[str, Check] = {}
        for check in checks:
            if not _ID_PATTERN.match(check.id):
                raise ValueError(f"invalid verification id {check.id!r}")
            if check.id in self._checks:
                raise ValueError(f"duplicate verification id {check.id!r}")
            self._checks[check.id] = check

    def __contains__(self, check_id: object) -> bool:
        return check_id in self._checks

    def get(self, check_id: str) -> Check:
        try:
            return self._checks[check_id]
        except KeyError:
            raise PolicyViolation(
                f"{check_id!r} is not a registered verification. Registered ids: "
                f"{', '.join(sorted(self._checks))}. Agents request ids; they do not "
                f"supply commands."
            ) from None

    def resolve_many(self, ids: list[str]) -> list[Check]:
        return [self.get(check_id) for check_id in ids]

    def validate_ids(self, ids: list[str]) -> list[str]:
        """Return the unknown ids without raising. Used when validating a plan."""
        return [check_id for check_id in ids if check_id not in self._checks]

    def gates(self) -> list[Check]:
        return [c for c in self._checks.values() if c.gate]

    def all(self) -> list[Check]:
        """Every registered check, in id order."""
        return [self._checks[check_id] for check_id in sorted(self._checks)]

    def of_class(self, evidence_class: str) -> list[Check]:
        """Registered checks of one evidence class, e.g. every required live path."""
        return [c for c in self._checks.values() if c.evidence_class == evidence_class]

    def ids(self) -> list[str]:
        return sorted(self._checks)

    def describe(self) -> list[tuple[str, str]]:
        return [(c.id, c.description) for c in sorted(self._checks.values(), key=lambda c: c.id)]

    def with_parameter(self, check_id: str, token: str, value: str) -> Check:
        """Bind a controller-supplied parameter such as a service path.

        The value comes from the plan's validated path list, and it is checked
        here again: an agent that could put arbitrary text into a command
        argument has been handed the command.
        """
        from ..workspace.guard import normalise

        check = self.get(check_id)
        safe = normalise(value)
        argv = tuple(arg.replace(token, safe) for arg in check.argv)
        return Check(
            id=f"{check.id}[{safe}]", description=f"{check.description} ({safe})",
            argv=argv, cwd=check.cwd, timeout_seconds=check.timeout_seconds,
            requires=check.requires, infra=check.infra, gate=check.gate,
            env=dict(check.env), infra_note=check.infra_note,
            evidence_class=check.evidence_class, exit_outcomes=dict(check.exit_outcomes),
            success_pattern=check.success_pattern,
        )


#: A tiny profile for the orchestrator's own disposable fixture repository.
#:
#: It exists because the Pipewright gates cannot run against a three-file test
#: repo -- there is no `.venv`, no `node_modules` and no `npm run verify` -- and
#: a gate that records `not_run` every time teaches nothing. The commands here
#: are real and really execute; they are just small.
#:
#: Selecting a profile is controller configuration, not something an agent can
#: reach: `pw-dev.toml` is in `ALWAYS_FORBIDDEN`, and `pw-dev doctor` prints the
#: active profile so a weakened gate cannot hide.
FIXTURE_CHECKS: tuple[Check, ...] = (
    Check(
        id="fixture:tests",
        description="the fixture repository's unittest suite",
        argv=("python3", "-m", "unittest", "discover", "-s", "tests", "-t", "."),
        timeout_seconds=120,
        gate=True,
    ),
    Check(
        id="fixture:compile",
        description="every Python file in the fixture repository parses",
        argv=("python3", "-m", "compileall", "-q", "src"),
        timeout_seconds=120,
        gate=True,
    ),
)

PROFILES: dict[str, tuple[Check, ...]] = {
    "pipewright": PIPEWRIGHT_CHECKS,
    "fixture": FIXTURE_CHECKS,
}


def registry_for(profile: str) -> Registry:
    """Build the registry for a named profile, refusing an unknown one."""
    try:
        return Registry(PROFILES[profile])
    except KeyError:
        raise PolicyViolation(
            f"unknown verification profile {profile!r}; known: {sorted(PROFILES)}"
        ) from None
