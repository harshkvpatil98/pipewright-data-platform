# Working in this repository

Read [`docs/HANDOFF.md`](docs/HANDOFF.md) first. It is the cold-start document:
what this is, how to run it, what is done, and what comes next.

This file is a pointer, not a second copy of the rules. Where something is
written down already, it is linked rather than restated, so the two cannot drift
apart.

## The rules

The execution rules every orchestrated role follows live in one place:
[`tools/dev-orchestrator/src/pw_dev/prompts/shared_rules.md`](tools/dev-orchestrator/src/pw_dev/prompts/shared_rules.md).
They cover which sources are authoritative when documents disagree, the honesty
rules, the path and Git boundaries, and the Pipewright invariants that existing
code and tests enforce. Read them whether or not you are running under the
orchestrator.

## The verification gate

```bash
npm run verify     # ruff + pytest + ESLint + tsc + production build
```

Everything must be green before moving on. `scripts/test.sh` lists its pytest
paths explicitly, so a new test directory has to be added there deliberately or
it will never run.

A green local run is not the same coverage as CI: CI starts real PostgreSQL,
MySQL and MariaDB and fails if they are unreachable, and the container-backed
connector tests skip without them.

## Which sources win

1. the operator's explicit request and the adopted run policy
2. the approved phase specification
3. established architecture decisions and executable behaviour — the code and
   the tests that pass
4. `docs/HANDOFF.md` — the progress ledger
5. `docs/roadmap-v2.md` — roadmap prose

`docs/roadmap-v2.md` opens with "Status: proposed, not started" while later
sections mark phases complete. That opening line is stale; the ledger in
`docs/HANDOFF.md` is the current record. Record contradictions with file
evidence rather than picking one silently.

## The development orchestrator

`tools/dev-orchestrator/` holds `pw-dev`: an OpenAI planner and reviewer, Claude
implementation workers, and a deterministic controller that owns state,
verification and Git publication. See
[`tools/dev-orchestrator/README.md`](tools/dev-orchestrator/README.md).

It is development tooling. It is not part of the product runtime, nothing in
`apps/` or `services/` imports it, and `service-intelligence` remains
deterministic analysis with no model calls.

## Git

Commits in this repository are the owner's:
`harshkvpatil98 <harshkvpatil@gmail.com>`, as both author and committer. Commit
metadata, branches, tags and notes carry no assistant, model or bot attribution.
Provider names inside source code and documentation are technical facts and
stay.
