# Rules every orchestrated role follows

These are the execution rules for this repository's development system. They do
not live in any one model's conversational memory: every role is handed this
file as part of its context packet, in a fresh session, every time.

## What is authoritative

Resolve conflicts in this order, highest first:

1. the operator's explicit request and the run's adopted policy;
2. the approved phase specification for this run;
3. established architecture decisions and executable behaviour — the code and
   the tests that pass;
4. the current handoff and progress ledger (`docs/HANDOFF.md`);
5. roadmap prose (`docs/roadmap-v2.md`).

Implementation can contain bugs, and a passing test is not proof that a
requirement is satisfied. When two sources disagree, record the contradiction
with file evidence and resolve it deliberately. Do not repair unrelated
architecture you happen to dislike.

## Honesty rules

- A claim that a test passes is a claim. The controller runs the tests and
  records evidence separately. Do not describe unexecuted work as done.
- A specification that passes validation is a validated document, not an
  approved, verified or implemented phase. Validation checks structure, scope,
  budgets and policy; it does not read the design.
- Only `pass` closes a gate. `skip`, `not_run`, `infra_unavailable`, `timeout`
  and `error` each say something different, and none of them says "passed". A
  check that could not run because its prerequisite is missing has not been
  satisfied by that absence.
- A task whose role is `verification` is a checkpoint. The controller runs the
  checks the specification gave it, against the integrated candidate, and holds
  its dependents until every one passes. Leaving them out of your
  `verification_requests` does not remove them.
- Never weaken, skip, delete or narrow a failing test to make a check pass. A
  test that is genuinely wrong may be corrected — with the reason stated, so a
  reviewer can judge it.
- "No improvements remain" and "there are no bugs" are not completion
  conditions. Completion is: the accepted requirements are met and the required
  checks pass.
- If something is blocked, say exactly what is blocking it. Do not substitute a
  plausible guess for a dependency you could not resolve.

## Boundaries

- Stay inside the paths your assignment declares. Anything outside is refused
  at integration, so writing there wastes a round.
- A declared path is a glob **only** if it contains `*` or `?`. `[` and `]` are
  literal, so `apps/web/src/app/projects/[projectId]/page.tsx` names that exact
  file. `*` and `?` stay inside one path segment; `**` spans zero or more. A
  pattern with no wildcard is a literal path that also owns its subtree.
- Do not run `git commit`, `git push`, `git merge`, `git rebase`, `git stash`,
  `git reset --hard`, or change Git configuration. The controller owns Git.
- Do not touch uncommitted work that was already in the repository. Report it.
- Do not install packages, change lockfiles, or allocate an Alembic revision
  unless your assignment says you own that resource.
- Never write credentials, production data, or paths outside the repository.

## Pipewright invariants

These are enforced by existing code and tests. Breaking one is a blocking
review finding, not a style disagreement.

- Access and tenancy checks are centralised; do not re-implement them per route.
- Cross-service extension happens through the established registered-hook
  patterns, not by importing another service's internals.
- Use `sqlalchemy.Uuid`, not a bespoke UUID column type.
- IR join sides are **positional**. Reversing them silently produces a cartesian
  product.
- Lineage is derived from the IR, not hand-maintained alongside it.
- Connector capabilities are reported honestly: a connector that cannot do
  something declares that it cannot.
- Inference methods are explicit. `service-intelligence` states
  "deterministic analysis; no model calls" and that must remain true — this
  development system lives in `tools/dev-orchestrator/` and is not part of the
  product runtime.
- The frontend has no icon library and no chart library. Every icon and chart is
  hand-written SVG. Keep it that way.
- Three-valued logic is real: comparisons return nullable boolean with NA, and
  only `Filter` and `Case` collapse NA to false.
- `SUM` of an all-null group is NULL, not 0.
- A dialect that cannot express something raises `Unsupported`. Never
  approximate.
