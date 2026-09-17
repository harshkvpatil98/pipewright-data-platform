"""Shared helpers for this package's own tests.

They live inside the installed package rather than beside the tests because
`scripts/test.sh` runs the whole repository's pytest bundle from the repository
root with `--import-mode=importlib`. Under that mode the tests directory is not
on `sys.path`, so `from conftest import ...` and `from test_x import ...` both
fail at collection -- and a collection error interrupts the *entire* bundle, not
just these files. Importing from `pw_dev.testing` works from any rootdir.

Nothing in here is imported by the controller at runtime.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

from .config import Config, IsolationConfig, Limits, ProviderConfig, PublicationPolicy
from .util.hashing import digest_json

OWNER = "harshkvpatil98"
EMAIL = "harshkvpatil@gmail.com"

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "tests" / "fixtures"


# --------------------------------------------------------------------- git
def run_git(repo: Path, *args: str, env: dict | None = None) -> str:
    """Run git in a fixture repository with a deterministic identity."""
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
        **(env or {}),
    }
    result = subprocess.run(  # noqa: S603 - test helper, fixed argv
        ["git", *args], cwd=repo, env=environment, capture_output=True, text=True, check=True,
    )
    return result.stdout.strip()


# ------------------------------------------------------------- stub binaries
def install_stub(path: Path, body: str) -> Path:
    """Write an executable stand-in for a provider CLI.

    The shebang is `/bin/sh` rather than the interpreter directly: this
    repository's checkout path contains a space, and the kernel splits a shebang
    on whitespace, so `#!<python>` would try to exec the first path segment and
    fail with ENOENT on the script itself.
    """
    source = path.with_suffix(".py")
    source.write_text(body, encoding="utf-8")
    path.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{source}" "$@"\n', encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return path


def fake_codex(bin_dir: Path, script: dict) -> Path:
    """A `codex` that answers planning and review from a scripted plan.

    `script` maps `role` or `role:index` to a JSON document, and the stub logs
    every call so a test can assert how often each role was invoked.
    """
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "codex-calls.json"
    body = f'''
import json, sys, pathlib
argv = sys.argv[1:]
log = pathlib.Path({str(log)!r})
calls = json.loads(log.read_text()) if log.exists() else []
prompt = argv[-1]
role = "reviewer" if "Review this candidate" in prompt else "planner"
index = sum(1 for c in calls if c["role"] == role)
calls.append({{"role": role, "argv": argv, "prompt_tail": prompt[-500:]}})
log.write_text(json.dumps(calls))

# Embedded as a JSON *string* and parsed: pasting json.dumps output straight
# into Python source breaks the moment the document contains true/false/null.
script = json.loads({json.dumps(json.dumps(script))})
key = f"{{role}}:{{index}}"
answer = script.get(key) or script.get(role) or {{}}

if role == "reviewer":
    # A real reviewer repeats the binding fields it was handed, and the
    # controller then checks them. The stand-in does the same wherever the
    # scripted answer says "PLACEHOLDER", which is what lets it answer a second
    # round whose candidate is a different tree. A field with a literal value is
    # left alone, so a test can pin a deliberately wrong one.
    import re
    answer = dict(answer)
    for field, pattern in (
        ("run_id", r"- run: `([^`]+)`"),
        ("base_commit", r"base commit: `([^`]+)`"),
        ("candidate_fingerprint", r"candidate fingerprint: `([^`]+)`"),
        ("spec_digest", r"specification digest: `([^`]+)`"),
    ):
        found = re.search(pattern, prompt)
        if found and answer.get(field) == "PLACEHOLDER":
            answer[field] = found.group(1)

print(json.dumps({{"type": "thread.started", "thread_id": "t-1"}}))
print(json.dumps({{"type": "turn.started"}}))
text = json.dumps(answer)
print(json.dumps({{"type": "item.completed",
                  "item": {{"id": "i0", "type": "agent_message", "text": text}}}}))
print(json.dumps({{"type": "turn.completed",
                  "usage": {{"input_tokens": 1000, "output_tokens": 100}}}}))
if "-o" in argv:
    open(argv[argv.index("-o") + 1], "w").write(text)
'''
    return install_stub(bin_dir / "codex", body)


def fake_claude(bin_dir: Path, *, edits: dict, report: dict | None = None,
                fail_first: bool = False) -> Path:
    """A `claude` that edits files in its cwd and returns a worker report."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    log = bin_dir / "claude-calls.json"
    body = f'''
import json, sys, os, pathlib
argv = sys.argv[1:]
log = pathlib.Path({str(log)!r})
calls = json.loads(log.read_text()) if log.exists() else []
index = len(calls)
calls.append({{"cwd": os.getcwd(), "argv": argv}})
log.write_text(json.dumps(calls))

edits = json.loads({json.dumps(json.dumps(edits))})
fail_first = {fail_first!r}
here = pathlib.Path(os.getcwd())
stage = "broken" if (fail_first and index == 0) else "fixed"
for name, variants in edits.items():
    content = variants.get(stage, variants.get("fixed"))
    if content is None:
        continue
    target = here / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)

report = json.loads({json.dumps(json.dumps(report or {}))})
report = dict(report)
report.setdefault("schema_version", "worker_report/v1")
report.setdefault("task_id", "T-01")
report.setdefault("status", "completed")
report.setdefault("summary", "done")
report.setdefault("changed_paths", sorted(edits))
report.setdefault("requirement_ids_addressed", ["R-01"])
report.setdefault("tests_claimed", [])
report.setdefault("verification_requests", [])
report.setdefault("assumptions", [])
report.setdefault("blockers", [])
report.setdefault("proposed_improvements", [])
text = json.dumps(report) if "--json-schema" in argv else "ok"
print(json.dumps({{
    "type": "result", "subtype": "success", "is_error": False, "duration_ms": 10,
    "num_turns": 1, "result": text, "session_id": "s-1", "total_cost_usd": 0.01,
    "usage": {{"input_tokens": 500, "output_tokens": 50, "cache_read_input_tokens": 0}},
    "modelUsage": {{"claude-sonnet-5": {{"outputTokens": 50}}}},
    "permission_denials": [], "terminal_reason": "completed",
}}))
'''
    return install_stub(bin_dir / "claude", body)


# ------------------------------------------------------------------ fixtures
#: A worker that changes behaviour and updates the test that asserts it.
UNITTEST_BODY = (
    "import unittest\n\nfrom src.app import VALUE\n\n\n"
    "class ValueTest(unittest.TestCase):\n"
    "    def test_value(self):\n"
    "        self.assertEqual(VALUE, 2)\n"
)

PASSING_EDIT = {
    "src/app.py": {"fixed": "VALUE = 2\n"},
    "tests/test_app.py": {"fixed": UNITTEST_BODY},
}


def make_run_config(repo: Path, tmp_path: Path, codex: Path, claude: Path, *,
                    state_dir: Path | None = None, **publication) -> Config:
    """A configuration pointed at stub providers and the fixture check profile."""
    return Config(
        repo_root=repo,
        state_dir=state_dir or (tmp_path / "state"),
        planner=ProviderConfig(executable=str(codex), model="planner-model"),
        implementer=ProviderConfig(executable=str(claude), model="implementer-model"),
        reviewer=ProviderConfig(executable=str(codex), model="reviewer-model"),
        limits=Limits(max_parallel_workers=2, per_task_seconds=60, total_run_seconds=600,
                      provider_retries=0, repair_rounds_per_task=2, plan_seconds=60,
                      review_seconds=60),
        # Supervised: the stand-ins are ordinary processes, and the enforced
        # boundary is exercised directly in the isolation tests.
        isolation=IsolationConfig(mode="supervised"),
        publication=PublicationPolicy(
            remote="origin", branch_prefix="pw-dev",
            author_name=OWNER, author_email=EMAIL, **publication,
        ),
        # The Pipewright gates cannot run against a three-file fixture repo.
        # This profile's checks are real commands that really execute.
        verification_profile="fixture",
    )


def make_spec(**overrides) -> dict:
    """A minimal valid `phase_spec/v1` document."""
    spec = {
        "schema_version": "phase_spec/v1",
        "phase_id": "18",
        "phase_title": "Time travel",
        "summary": "Immutable snapshots addressable by time.",
        "base_commit": "0" * 40,
        "source_references": [{"path": "docs/roadmap-v2.md", "lines": None, "why": "the promise"}],
        "requirements": [
            {"id": "R-01", "statement": "snapshots are immutable", "rationale": "audit",
             "priority": "must"},
        ],
        "non_goals": ["a UI"],
        "invariants": [{"id": "I-01", "rule": "sqlalchemy.Uuid", "evidence": "existing models"}],
        "public_contracts": [],
        "migration_strategy": {"needed": False, "notes": "none", "alembic_revisions": []},
        "tasks": [
            {
                "id": "T-01", "title": "backend", "role": "backend",
                "objective": "implement snapshots", "depends_on": [],
                "requirement_ids": ["R-01"], "allowed_paths": ["src/app.py"],
                "forbidden_paths": [], "exclusive_resources": [],
                "acceptance_criteria": ["it works"], "verification_ids": [],
                "context_paths": [], "notes": None,
            },
        ],
        "acceptance_criteria": [
            {"id": "A-01", "criterion": "snapshots immutable", "requirement_ids": ["R-01"],
             "verification_ids": []},
        ],
        "required_verifications": [],
        "accepted_preexisting_failures": [],
        "risks": [{"id": "K-01", "risk": "concurrent writers", "severity": "high",
                   "mitigation": "atomic publish", "test_idea": "two writers"}],
        "resource_limits": {"max_parallel_workers": 2, "per_task_seconds": 30,
                            "total_run_seconds": 300, "repair_rounds_per_task": 2},
        "publication_policy": {"mode": "none", "branch_prefix": "pw-dev",
                               "allow_existing_branch": None},
        "open_questions": [],
    }
    spec.update(overrides)
    return spec


def spec_for(base: str, **overrides) -> dict:
    """A specification for the end-to-end fixture repository."""
    spec = make_spec(
        phase_id="18", phase_title="Time travel", base_commit=base,
        summary="Immutable dataset snapshots addressable by time.",
        resource_limits={"max_parallel_workers": 2, "per_task_seconds": 60,
                         "total_run_seconds": 600, "repair_rounds_per_task": 2},
        open_questions=[{"question": "is the roadmap opening stale?",
                         "evidence": "HANDOFF ledger says 08 is done",
                         "resolution": "followed the ledger"}],
    )
    spec["tasks"] = [{
        "id": "T-01", "title": "snapshot store", "role": "backend",
        "objective": "add a snapshot value", "depends_on": [],
        "requirement_ids": ["R-01"],
        "allowed_paths": ["src/app.py", "tests/**"],
        "forbidden_paths": [], "exclusive_resources": [],
        "acceptance_criteria": ["VALUE is 2"], "verification_ids": [],
        "context_paths": [], "notes": None,
    }]
    spec.update(overrides)
    return spec


def approval(spec: dict, run_id: str, fingerprint: str, verdict: str = "APPROVE",
             findings=None) -> dict:
    """A `review_findings/v1` verdict bound to a specific candidate."""
    return {
        "schema_version": "review_findings/v1", "run_id": run_id, "verdict": verdict,
        "base_commit": spec["base_commit"], "candidate_fingerprint": fingerprint,
        "spec_digest": digest_json(spec), "summary": "checked",
        "findings": findings or [], "requirements_checked": ["R-01"],
        "evidence_reviewed": [], "context_requests": [],
    }


def load_events(name: str) -> list[dict]:
    """Recorded provider event streams.

    Fixtures captured from real CLI invocations and then edited to cover failure
    shapes. Appropriate for offline tests of parsing and failure classification.
    They are never evidence that a live call happened.
    """
    path = FIXTURE_DIR / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]
