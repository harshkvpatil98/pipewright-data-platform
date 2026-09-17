"""Driving the planner, workers and reviewer.

Each function assembles a context packet, calls one provider, records usage, and
returns a structured result. They do not decide anything: the run loop reads the
result and the state machine decides what happens next.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..providers.base import ProviderResult
from ..util.hashing import digest_json
from .context import ContextBuilder


def plan_prompt(*, discovery: dict, registry_ids: list[tuple[str, str]], base_commit: str,
                config_summary: dict, requested_phase: str | None,
                context_text: str) -> str:
    """The planner's packet.

    The contradictions discovery found are handed over explicitly. A planner
    that has to rediscover them spends its budget on archaeology, and a planner
    that never sees them writes a plan against a stale sentence.
    """
    candidates = "\n".join(
        f"- phase {p['number']} {p['name']}: ledger says {p['ledger_status']!r}"
        + (f", roadmap marker {p['roadmap_marker']!r}" if p.get("roadmap_marker") else "")
        + (f", depends on {p['depends_on']}" if p.get("depends_on") else "")
        + (f" — {p['notes']}" if p.get("notes") else "")
        for p in discovery["phases"]
    )
    contradictions = "\n".join(f"- {c}" for c in discovery["contradictions"]) or "- (none found)"
    deferred = "\n".join(f"- {d}" for d in discovery["deferred_decisions"]) or "- (none recorded)"
    checks = "\n".join(f"- `{cid}`: {description}" for cid, description in registry_ids)

    target = (
        f"Plan **phase {requested_phase}**." if requested_phase else
        "Select the phase yourself from the evidence below, and justify the choice in "
        "`summary` and `open_questions`."
    )

    return f"""{target}

## Repository state

- base commit: `{base_commit}`
- branch: `{discovery['branch']}`
- uncommitted files present at capture: {len(discovery['dirty_paths'])} modified, \
{len(discovery['untracked_paths'])} untracked. These are someone else's work. Do not plan \
changes that depend on them, and do not plan to remove them.

## Progress ledger (docs/HANDOFF.md)

{candidates}

The handoff's own recommendation: {discovery.get('recommendation_text') or '(none found)'}

## Contradictions discovery found

These are real disagreements between documents in this repository. Resolve each one
deliberately in `open_questions`, with the evidence, and say which source you followed.

{contradictions}

## Deliberately deferred decisions

Do not fold these into this phase because they are adjacent. Name them as dependencies
or non-goals.

{deferred}

## Verification registry

Your `verification_ids` and `required_verifications` must come from this list. You cannot
supply a command.

{checks}

## Adopted run policy

```json
{json.dumps(config_summary, indent=2, sort_keys=True)}
```

Your `resource_limits` may not exceed these, and your `publication_policy` must match the
adopted one exactly.

## Repository context

{context_text}

---

Return one JSON document conforming to the phase_spec/v1 schema. `base_commit` must be
exactly `{base_commit}`.
"""


def review_prompt(*, spec: dict, diff: str, evidence: list[dict], worker_reports: list[dict],
                  candidate_fingerprint: str, base_commit: str, spec_digest: str,
                  baseline_context: str, run_id: str,
                  previous_findings: list[dict] | None = None) -> str:
    """The reviewer's packet: requirements, the actual diff, and independent evidence."""
    evidence_lines = "\n".join(
        f"- `{e['verification_id']}` → **{e['outcome']}** "
        f"(exit {e['exit_status']}, {e['duration_seconds']}s) — {e.get('detail') or ''}"
        for e in evidence
    ) or "- (no verification evidence was recorded)"

    claims = []
    for report in worker_reports:
        for claim in report.get("tests_claimed", []):
            claims.append(
                f"- {report['task_id']} claims `{claim['name']}` → {claim['claimed_outcome']}"
            )
    claims_text = "\n".join(claims) or "- (no test claims were made)"

    prior = ""
    if previous_findings:
        prior = (
            "\n## Findings from the previous round\n\n"
            "These were raised before. Check whether each is genuinely resolved in this "
            "tree, not merely described as resolved.\n\n"
            + "\n".join(
                f"- [{f['severity']}] {f['id']}: {f['failure_scenario']}"
                for f in previous_findings
            )
            + "\n"
        )

    return f"""Review this candidate against its specification.

- run: `{run_id}`
- base commit: `{base_commit}`
- candidate fingerprint: `{candidate_fingerprint}`
- specification digest: `{spec_digest}`

Your verdict must repeat these four values exactly. An approval is bound to this tree;
it does not carry to a different one.

## Specification

```json
{json.dumps(spec, indent=2, sort_keys=True)}
```
{prior}
## Verification evidence recorded by the controller

The controller ran these itself. `skip`, `not_run`, `infra_unavailable` and `timeout`
are not passes.

{evidence_lines}

## What the workers claimed

Compare these against the evidence above. A claim with no matching evidence is a finding.

{claims_text}

## The candidate diff

```diff
{diff}
```

## Relevant baseline code

{baseline_context}

---

Return one JSON document conforming to the review_findings/v1 schema.
"""


def worker_prompt(*, assignment: dict, context_text: str, repair_findings: list[dict] | None = None) -> str:
    """One worker's packet."""
    requirements = "\n".join(
        f"- **{r['id']}**: {r['statement']}" for r in assignment["requirements"]
    ) or "- (no requirement ids were attached to this task)"
    criteria = "\n".join(f"- {c}" for c in assignment["acceptance_criteria"]) or "- (none stated)"
    allowed = "\n".join(f"- `{p}`" for p in assignment["allowed_paths"])
    forbidden = "\n".join(f"- `{p}`" for p in assignment["forbidden_paths"]) or "- (none beyond the standing rules)"
    checks = ", ".join(f"`{v}`" for v in assignment["verification_ids"]) or "(none)"
    rules = "\n".join(f"- {r}" for r in assignment["rules"])

    findings_block = ""
    if repair_findings:
        findings_block = (
            "\n## Findings to fix\n\n"
            + "\n".join(
                f"### {f['id']} [{f['severity']}] {f.get('path') or ''} {f.get('location') or ''}\n"
                f"- rule/requirement: {f['requirement_or_rule']}\n"
                f"- failure: {f['failure_scenario']}\n"
                f"- evidence: {f['evidence']}\n"
                f"- requested correction: {f['requested_correction']}\n"
                for f in repair_findings
            )
            + "\n"
        )

    return f"""# {assignment['title']}

{assignment['objective']}
{findings_block}
## Requirements

{requirements}

## Acceptance criteria

{criteria}

## Paths you may write

{allowed}

## Paths you may not write

{forbidden}

## Checks the controller will run for you

{checks}

## Rules

{rules}

## Task context

{context_text}

---

You are working in this checkout. Make the changes, then return one JSON document
conforming to the worker_report/v1 schema with `task_id` set to `{assignment['task_id']}`.
"""


def gather_context(builder: ContextBuilder, paths: list[str], reason: str) -> tuple[str, list[str]]:
    files, problems = builder.read([(p, reason) for p in paths])
    return builder.render(files), problems


def record_usage(store, run_id: str, result: ProviderResult, *, task_id: str | None = None) -> None:
    store.record_usage(
        run_id, role=result.role, provider=result.provider,
        model=result.usage.model or result.resolved_model,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cost_usd=result.usage.cost_usd, task_id=task_id,
    )


def digest_spec(spec: dict) -> str:
    return digest_json(spec)


def default_planner_context(repo_root: Path) -> list[str]:
    """Files a planner almost always needs, filtered to what exists."""
    candidates = [
        "docs/HANDOFF.md", "docs/roadmap-v2.md", "docs/architecture.md",
        "docs/agent-context.md", "package.json", "scripts/test.sh",
        "scripts/verify-release.sh", ".github/workflows/ci.yml",
    ]
    return [p for p in candidates if (Path(repo_root) / p).exists()]
