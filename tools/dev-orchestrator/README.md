# `pw-dev` — Pipewright's development orchestrator

An OpenAI planner and independent reviewer, Claude implementation workers, and a
deterministic controller that owns run state, scheduling, verification and Git
publication.

This is **development tooling**. It is not part of the Pipewright product
runtime, nothing in `apps/` or `services/` imports it, and
`service-intelligence` remains what it says it is: deterministic analysis with
no model calls.

---

## Why it is split this way

One session that interprets the roadmap, designs the work, implements it,
invents extra improvements, tests it, reviews itself and decides when it is done
produces a large workload for one context and leaves the completion decision
self-reported. The same requirements — autonomy, complete delivery, root-cause
fixes, real tests, personal Git identity, verified publication — survive better
when the responsibilities are separated:

| Role | Does | Produces |
|---|---|---|
| OpenAI planner | selects and scopes the phase, contracts, task DAG, acceptance criteria | a versioned specification |
| Claude workers | implement assigned slices and tests | patch bundles and evidence requests |
| OpenAI reviewer | inspects the actual diff and independently recorded evidence, in a fresh session | findings, or approval of one snapshot |
| Controller | state, scheduling, limits, integration, checks, Git | verified transitions and receipts |
| Owner | product intent, exceptional decisions | the adopted scope and publication policy |

This is a division of responsibility, not a claim that one vendor reasons or
codes better than the other. Both can do both jobs. The gain is explicit
requirements, cross-model scrutiny, and checks that the controller runs itself.

---

## Install

```bash
# From the repository root, into the repository's own virtualenv.
.venv/bin/pip install -e tools/dev-orchestrator
.venv/bin/pw-dev --help
```

`scripts/setup.sh` and `scripts/ci-bootstrap-python-venv.sh` already install it,
so a fresh `npm run setup` gets the command. Python 3.11+ is required, matching
every other package here.

Both provider CLIs must be installed and logged in:

```bash
codex login     # ChatGPT/OAuth or an API key
claude          # /login once, interactively
```

Start with:

```bash
.venv/bin/pw-dev doctor --probe
```

`doctor` separates what it can see offline from what it proved with a real call.
An installed CLI does not establish authentication; an authenticated CLI does not
establish access to a particular model. Only `--probe` answers the second
question, and it costs one tiny call per provider.

---

## Commands

```bash
pw-dev doctor [--probe]                     # what this machine can actually do
pw-dev plan --next                          # produce a phase specification and stop
pw-dev plan --phase 18 --show
pw-dev run --next --publish feature-branch  # the full loop
pw-dev run --spec <path> --brain interactive --publish feature-branch
pw-dev status [<run-id>]                    # state, tasks, evidence, usage
pw-dev logs <run-id>                        # the append-only event log
pw-dev review-export <run-id> [--out f]     # evidence packet for an external reviewer
pw-dev review-import <run-id> <review.json> # a verdict, bound to this candidate
pw-dev plan-export <run-id>                 # planning packet for an interactive run
pw-dev plan-import <run-id> <spec.json>
pw-dev resume <run-id> [--dry-run]          # reconcile, then continue
pw-dev cancel <run-id>                      # stop, preserving work
pw-dev checks                               # the verification registry
pw-dev schemas                              # the artifact schemas
```

### Two brains, one state machine

**Automatic** — the controller invokes Codex for planning, runs Claude workers,
invokes a fresh Codex session for review, and finishes the bounded loop.

**Interactive** — a Codex application is the brain. The controller exports a
schema-validated planning packet, pauses at `WAITING_FOR_PLAN`, runs the workers
once a specification is imported, then exports a review packet and pauses at
`WAITING_FOR_REVIEW`. The application's chat history is never shared with either
CLI: everything crosses as a versioned artifact, which is why a new session can
pick a run up without the original conversation.

An imported approval is accepted only through `pw-dev review-import`, and only
when it names this run, this base commit, this candidate fingerprint and this
specification digest. An approval of a different tree is refused there.

---

## States

```
DISCOVER → PLAN → VALIDATE_PLAN → IMPLEMENT → INTEGRATE → VERIFY → REVIEW → COMMIT → PUSH → COMPLETE
```

with `WAITING_FOR_PLAN`, `WAITING_FOR_REVIEW`, `NEEDS_FIX`, `BLOCKED`, `PAUSED`,
`CANCELLED`, `FAILED`, and `VERIFIED_LOCAL` when publication was not requested.

Three of these are worth stating plainly:

- **`PAUSED`** is where a run goes when a budget is exhausted. It is resumable
  and it is not a completed phase.
- **`VERIFIED_LOCAL`** means verified and approved, and *nothing was published*.
- **`COMPLETE`** requires the remote ref to have been read back and matched.

Every status carries the precise outstanding condition, not just a word.

---

## What counts as verification

Agents request check **IDs**. The controller maps an ID to a vetted argument
array and runs it. An agent cannot supply a command, and
`tools/dev-orchestrator/src/pw_dev/verify/` is never writable by a task.

Outcomes are kept apart because they mean different things:

| Outcome | Meaning |
|---|---|
| `pass` | ran, succeeded. **The only outcome that closes a gate.** |
| `fail` | ran, failed |
| `skip` | ran, and skipped cases inside it. Not full coverage |
| `not_run` | never executed — a prerequisite was missing |
| `infra_unavailable` | a required service was not reachable |
| `timeout` | killed; whether it would have passed is unknown |
| `error` | the runner could not execute it |

`npm run verify` locally with no database is **not** CI coverage: CI starts
PostgreSQL, MySQL and MariaDB and fails if they are unreachable. The
`connectors:servers` check records `infra_unavailable` rather than letting a
green local run look equivalent.

Every evidence record is bound to the candidate tree fingerprint, base SHA,
specification digest and an environment digest. The fingerprint walks the
filesystem rather than asking Git, so a new untracked file invalidates evidence
that a `git diff` check would have missed.

A worker's claim that a test passed is recorded as a **claim** and compared
against runner evidence. A claim with no matching evidence is surfaced to the
reviewer.

Running the checks is not a change to the tree being checked. `compileall`
writes `__pycache__`, `next build` writes `.next/`, and the controller writes
`.pw-dev/` — none of that is the worker's work, so none of it is staged, and
none of it blocks publication for something the controller itself did. Worker
leftovers are treated differently: a `.orig`, `.rej`, `.DS_Store` or `.env` in
the candidate refuses the commit rather than being quietly dropped.

---

## Isolation

Each writing worker gets its own git worktree, created from **its own
prerequisite commit** — not from the run's base, so a dependent task sees the
contracts it depends on.

A worktree is not a security boundary. Worktrees share `.git` and stop file
collisions, nothing more. The actual write boundary is enforced by the operating
system: on macOS, `sandbox-exec` with a profile that allows reads and confines
writes to the roots a task owns. `pw-dev doctor` probes it at startup and reports
`enforced` or `supervised`.

Where no mechanism can be enforced, unattended runs are **refused**. Supervised
runs are supported, with the limitation stated. A post-run digest comparison
detects tampering; it does not prevent it, and this tool does not describe it as
if it did.

### One documented hole, rather than a hidden one

A Claude worker runs with the operator's **real** `~/.claude` configuration
directory, granted writable in the sandbox profile. This is not a convenience:
Claude Code's subscription login resolves through that directory, a fresh
`CLAUDE_CONFIG_DIR` reports "Not logged in" even when the operator is signed in,
and copying the account record across does not help. All three were tested.

So the directory is granted, and the files that could change what happens in the
operator's *next* interactive session are carved back out with deny rules that
override the grant:

```
~/.claude/settings.json          ~/.claude/plugins    ~/.claude/hooks
~/.claude/settings.local.json    ~/.claude/agents     ~/.claude/skills
~/.claude.json                   ~/.claude/commands
```

`pw-dev doctor` proves the carve-outs work at startup, alongside the boundary
itself — an early version of this profile silently failed to apply them, because
`/var` and `/private/var` are the same directory under different names and the
deny paths were not resolved. The probe caught it; reading the profile would not
have.

What remains writable inside `~/.claude`: session state, caches, file history and
shell snapshots. A worker can write those. That is the residual exposure, and it
is stated here rather than left for someone to discover.

Workers additionally run with:

- `--setting-sources ""` — no user, project or local settings, so no inherited
  hooks, plugins or permission grants;
- `--strict-mcp-config` with an empty config — no MCP;
- delegation tools removed — a nested agent would spawn outside the controller's
  concurrency and budget accounting;
- `--permission-mode acceptEdits`, never `--dangerously-skip-permissions`;
- an allowlist environment with `ANTHROPIC_*`, `OPENAI_*`, `GIT_AUTHOR_*`,
  `GIT_COMMITTER_*` and the parent session's `CLAUDE_CODE_*` stripped.

Uncommitted work already in the repository is **recorded and left alone**.
Nothing is stashed, reset or cleaned, and runs work from the clean committed
base.

---

## Scheduling

A task may start when its dependencies are integrated, no running task claims
overlapping paths, and no exclusive resource it needs is held. Overlapping write
ownership between two concurrently eligible tasks is refused at plan validation,
not discovered later as a merge conflict.

Alembic revision allocation, lockfile and dependency changes, and shared contract
edits take a named lock — implicitly, from the paths a task claims, so a plan
cannot forget to declare one.

Default: at most three simultaneous workers. The controller integrates; workers
never commit, push, merge, rebase or touch Git configuration.

---

## Git and publication

Publication authority is captured once, in `pw-dev.toml`, not asked for per run.
Modes are `none`, `local_commit` and `feature_branch`. **Pushing is not merging
and neither is deploying.**

Before a commit exists, the publisher checks that the candidate still matches the
reviewed tree, that no temporary or build artefacts are staged, that nothing
credential-shaped is in the diff, and that every changed path is inside the
specification's declared scope.

Then one commit is created for exactly the approved tree, with author *and*
committer set explicitly to `harshkvpatil98 <harshkvpatil@gmail.com>`. The
message is composed by the publisher; no model writes this repository's history.
Every commit reachable from the publication ref is re-read from Git and checked
for identity and for assistant attribution in its subject, body, trailers and
notes.

Provider names in source code and documentation are technical facts, not
authorship claims — `codex_cli.py` and `claude_cli.py` keep their names. The
attribution scan is applied to commit metadata and ref names only, never to a
diff.

Before pushing: the target must not be a protected branch, and if the branch
already exists remotely it must be an ancestor of what is being published. A
target that moved incompatibly **blocks** with the local work preserved. There is
no force-push path in this codebase, and a test greps for one.

After pushing, the remote ref is read back and compared to the intended SHA. A
push exiting zero is not the evidence.

**CI is reported as `not_triggered`** for a feature branch, because this
repository's workflow runs on pushes to `main`/`master` and on pull requests. A
pushed branch with no PR has not been tested by CI.

---

## Budgets and cost

Configured in `pw-dev.toml`: parallel workers, per-task seconds, total run
seconds, provider retries, repair rounds, output size. Reaching one produces a
resumable `PAUSED`, never a completed phase. Three identical repair rounds
escalate rather than continuing against a wall.

Reported usage is stored as reported. `claude -p` supplies a dollar figure;
`codex exec` supplies tokens and no cost. A missing cost shows as **unknown**,
not zero — and a subscription is not "free". Wall-clock and round limits are
enforced regardless.

---

## Artifacts

Under `.pw-dev/` (gitignored):

```
.pw-dev/state.sqlite3              run and task state, events, evidence, usage
.pw-dev/runs/<run-id>/
  phase-spec.json                  the accepted specification
  plan-request.json                interactive planning packet
  review-request.json              interactive review packet
  publication-receipt.json         what was committed and published
  evidence/                        one log per executed check
  worktrees/                       per-task checkouts
  candidate/                       the integration checkout
  artifacts/                       patches, reports, reviews, by content hash
```

Committed to Git: schemas, role prompts, the policy template, tests and this
documentation. Not committed: the database, logs, worktrees, patches, and any
prompt carrying repository excerpts.

---

## A future MCP wrapper

Not required for v1: a Codex application can invoke this CLI directly. If native
tool cards become useful later, a thin MCP wrapper should call **the same
controller commands** rather than become a second scheduler. Do not build against
`codex mcp-server`: the current Codex SDK documentation directs custom clients to
the app server and says that interface was removed. Verify the current interface
before adding an adapter.

---

## Verified against

Read from the installed builds on 2026-09-17, not from documentation alone:

| | |
|---|---|
| codex-cli | 0.149.1, `auth_mode: chatgpt`, default model `gpt-5.6-sol` |
| Claude Code | 2.1.231, subscription OAuth via the OS keychain |
| Python | 3.12.14 locally, 3.11 in CI; this package requires 3.11+ |
| Isolation | `/usr/bin/sandbox-exec`, probed and confirmed to confine writes |

Two behaviours that cost real debugging time and are encoded in the adapters:

1. `codex exec` reads a piped stdin, prints `Reading additional input from
   stdin...` and waits for EOF. Every invocation binds stdin.
2. `claude -p` can exit **1** while emitting a complete result object with
   `subtype: "success"` and `is_error: true` — that is how "Not logged in"
   arrives. `is_error` is authoritative; the exit status is corroboration.

And one model fact worth keeping: the operator's `~/.codex/config.toml` names
`gpt-6-astra`, which this CLI rejects with HTTP 400. Configuration is not
availability, which is why the resolved model is recorded per run.
