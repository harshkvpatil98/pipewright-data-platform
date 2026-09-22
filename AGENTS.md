# Working in this repository

Read [`docs/HANDOFF.md`](docs/HANDOFF.md) first. It is the cold-start document:
what this is, how to run it, what is done, and what comes next.

Development here is one Claude Code session working directly in the repository:
read the context, plan briefly, implement, verify, review the diff, update the
handoff. There are no delegated agent roles, no required subagents, and no
external model review. This file is the canonical set of development rules;
`docs/HANDOFF.md` is the project status and architecture detail. Keep it that
way — one source of truth each, linked rather than restated.

## Which sources win

Resolve conflicts in this order, highest first:

1. the user's explicit request;
2. accepted requirements for the work at hand (for Phase 18 that is
   [`docs/plans/phase-18-review-requirements.md`](docs/plans/phase-18-review-requirements.md));
3. established architecture decisions and executable behaviour — the code and
   the tests that pass;
4. `docs/HANDOFF.md` — the progress ledger;
5. `docs/roadmap-v2.md` — roadmap prose.

`docs/roadmap-v2.md` opens with "Status: proposed, not started" while later
sections mark phases complete. That opening line is stale; the ledger in
`docs/HANDOFF.md` is the current record. When two sources disagree, record the
contradiction with file evidence and resolve it deliberately — do not pick one
silently, and do not repair unrelated architecture you happen to dislike.

## Honesty

- Never claim a test ran or passed without evidence. Do not describe
  unexecuted work as done.
- Passed, failed, skipped, and could-not-run are four different results. A
  check that could not run because its prerequisite is missing has not been
  satisfied by that absence.
- Never weaken, skip, delete or narrow a failing product test to get a green
  result. A test that is genuinely wrong may be corrected — with the reason
  stated, so a reviewer can judge it.
- "No improvements remain" is not a completion condition. Completion is: the
  accepted requirements are met and `npm run verify` passes.
- If something is blocked or unverified, say exactly what and why. Do not
  substitute a plausible guess for a dependency you could not resolve.

## Scope and preservation

- Keep changes within the requested scope. Finish the whole request; report
  explicitly anything left out and why.
- Preserve existing user work. Do not overwrite uncommitted changes you did
  not make — inspect and preserve their intent, or report them.
- Update `docs/HANDOFF.md` (ledger and session log) whenever project state
  changes.

## The verification gate

```bash
npm run verify     # ruff + pytest + ESLint + tsc + production build
```

Everything must be green before declaring completion. `scripts/test.sh` lists
its pytest paths explicitly, so a new test directory has to be added there
deliberately or it will never run.

A green local run is not the same coverage as CI: CI starts real PostgreSQL,
MySQL and MariaDB and fails if they are unreachable, and the container-backed
connector tests skip without them. State skipped or unavailable infrastructure
coverage separately — a local pass is not proof it ran.

## Pipewright invariants

These are enforced by existing code and tests. Breaking one is a bug, not a
style disagreement. The detailed rationale for each lives in
`docs/HANDOFF.md` §5–§8.

- Access and tenancy checks are centralised (`service_access/permissions.py`,
  `service_projects.contracts.project_role`); do not re-implement them per
  route. Unrecognised write paths require `editor` — failing closed is the
  design.
- Cross-service extension happens through the established registered-hook
  patterns (`register_role_resolver`, `register_snapshotter`,
  `register_reference_resolver`), never by importing another service's
  internals.
- Use `sqlalchemy.Uuid`, not a dialect-specific UUID column type.
- IR join sides are **positional** — first operand is the left input, second
  the right. Reversing them silently produces a cartesian product.
- Lineage is derived, never stored. `service_lineage/columns.py` is the
  current deriver; `from_ir.py` derives from the IR and is proven equal to it.
  Both executors run today, and cutting over to IR-only is a deliberate,
  separate decision that has not been made — do not make it in passing.
- Connector capabilities are reported honestly: a connector that cannot do
  something here declares that it cannot.
- Inference methods are explicit, and `service-intelligence` remains
  deterministic analysis with **no model calls**.
- Three-valued logic is real: comparisons return nullable boolean with NA, and
  only `Filter` and `Case` collapse NA to false.
- `SUM` of an all-null group is NULL, not 0.
- A dialect that cannot express something raises `Unsupported`. Never
  approximate.
- The frontend has no icon library and no chart library — every icon and chart
  is hand-written SVG. Never write a raw colour literal; use the semantic theme
  tokens (`no-raw-colours.test.ts` enforces this).

## Git

Commits in this repository are the owner's:
`harshkvpatil98 <harshkvpatil@gmail.com>`, as both author and committer. Commit
metadata, branches, tags and notes carry no assistant, model or bot
attribution. Provider names inside source code and documentation are technical
facts and stay.
