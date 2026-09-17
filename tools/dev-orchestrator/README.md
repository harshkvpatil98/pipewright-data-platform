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
pw-dev plan --phase 18 --context-file docs/plans/notes.md   # corrections, in full
pw-dev validate-spec <spec.json>            # check a specification, run nothing
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

### Planning to running, and the publication policy

A specification records the publication policy it was planned under, and `run`
refuses one that disagrees with its own — authority comes from the adopted
policy, never from a document a model wrote. So **plan under the policy you
intend to execute under**, and pass the same `--publish` value to both:

```bash
pw-dev plan --phase 18 --publish none                 # or: --publish feature-branch
pw-dev validate-spec .pw-dev/runs/<run-id>/phase-spec.json
pw-dev run --spec .pw-dev/runs/<run-id>/phase-spec.json --publish none
```

Adopting a different policy later is a fresh planning and validation cycle, not
an edit: change `[publication] mode` in `pw-dev.toml` (or pass `--publish`),
plan again against the current HEAD, validate, and run. The equality check is
not relaxed, a recorded run's frozen policy is not rewritten, and a
specification's `base_commit` is not swapped for a newer one — both would make a
published commit unattributable to anything that was actually reviewed.

### Handing the planner corrections

`--context-file PATH` reads a repository file, bounds and redacts it, records
its SHA-256 in the run's event log and the planning packet, and puts the
**contents** into the planner's prompt under a heading that outranks roadmap
prose. Repeatable. Naming a file in a free-text instruction is not delivery: a
planner that never opens it plans without it, and nothing afterwards shows that
it did.

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
                        ↘ PLAN_READY  (plan-only: nothing implemented)
```

with `WAITING_FOR_PLAN`, `WAITING_FOR_REVIEW`, `NEEDS_FIX`, `BLOCKED`, `PAUSED`,
`CANCELLED` and `FAILED`.

The three stopping states that are not failures mean three different amounts,
and they are kept apart on purpose:

| State | What is true |
|---|---|
| `PLAN_READY` | a specification passed structural and policy validation. **Nothing was implemented, no check was executed, and no reviewer has seen it.** Validation establishes that the document is well-formed, in scope, inside the adopted budget and free of the conflicts the controller can decide — not that the design is right |
| `VERIFIED_LOCAL` | an implementation the controller verified and an independent reviewer approved. Nothing was published |
| `COMPLETE` | the above, published, with the remote ref read back and matched |

A plan-only run used to finish in `VERIFIED_LOCAL`, whose own description said
"verified and approved". It was neither, so `PLAN_READY` exists. Runs recorded
before it are *described* for what they were rather than relabelled: their rows
are historical evidence, and `pw-dev status` prints the honest sentence for a
stored plan-only run without rewriting the state it was saved under.

- **`PAUSED`** is where a run goes when a budget is exhausted. It is resumable
  and it is not a completed phase.

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

### What a result is worth

`pw-dev checks` labels every check, because "it passed" is not one thing:

| Class | Meaning |
|---|---|
| `gate` | runs before `COMMIT` whether or not a plan asks for it. A plan cannot drop one by omitting it |
| `optional_smoke` | a diagnostic. `repo:smoke` exits 0 offline and is satisfied by *any* server answering the configured root, including one started last week from a different checkout. It cannot stand in for acceptance evidence |
| `required_live` | an end-to-end acceptance path that fails closed. A plan that needs one must name it in `required_verifications` — a live scenario only one task asks for is not a gate on the phase, and validation refuses that shape |

**`alembic:heads`** asserts the count. The registered command used to be
`alembic heads`, which exits 0 with two heads and exits 0 with none — so the
exact failure it exists to catch, two workers each allocating a revision, passed
it. It now reads the revision graph through Alembic's `ScriptDirectory` and
requires exactly one head. It opens no database.

**`repo:live-acceptance`** starts the gateway *itself*, from the candidate's own
virtualenv, in the candidate's own directory, on an ephemeral port, against a
disposable database and storage directory with credentials, a signing secret and
an administrator it generated, and then runs every step of
`scripts/live-acceptance/<phase-id>.json`.

Three things are deliberately **not** the scenario's to decide:

- **what starts.** The launcher is a literal in the check registry. A scenario
  that could name the module would satisfy an acceptance gate with
  `python -m http.server` and a `GET /` returning 200;
- **what environment it starts with.** Database URL, upload root, signing
  secret, `HOME` and `TMPDIR` are generated per invocation inside a temporary
  directory. The operator's environment is not inherited beyond `PATH`, so an
  unset variable falls back to a Pipewright default rather than to whatever
  happens to be exported;
- **what is cleaned up.** Teardown signals the process group this runner
  created — whether or not its leader is still alive, because a launcher that
  forks and exits otherwise leaves the server holding the port — and removes the
  directory this runner made. Nothing else.

Before the port is opened, the candidate interpreter is asked where it resolves
`api_gateway` and the services from, and every origin must be inside the
candidate. Pipewright installs its packages with `pip install -e`, so a
virtualenv belonging to another checkout imports *that* checkout's source — and
`api_gateway.config` then loads the operator's real `apps/api-gateway/.env`,
pointing the "disposable" run at their actual database. Outcomes:

| Situation | Outcome |
|---|---|
| every declared step executed and passed | `pass` |
| a step failed an expectation | `fail` |
| the server never became ready | `infra_unavailable` |
| no scenario file, or a credential the runner did not create | `not_run` |
| a declared step did not execute | `skip` |
| the deadline passed | `timeout` |

Only `pass` closes a gate, so **a phase that has not written its scenario yet
cannot accidentally satisfy the check**: no file means `not_run`. The scenario
name is derived from the specification's own `phase_id` by the controller, not
chosen by a worker, and the runner lives under `pw_dev/verify/` where no task may
write it.

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

### One thing a checkout does not get

`node_modules` is symlinked in. **`.venv` is not**, and that is a real
limitation rather than an oversight. Pipewright installs its service packages
with `pip install -e`, so a virtualenv belonging to the original checkout
imports *that* checkout's source: every Python check would run, and would be
testing the wrong tree. A check that passes against code nobody is publishing is
worse than one that says it did not run.

So every check declaring `requires=("venv",)` — ten of the fourteen, including
the `repo:verify` and `alembic:heads` gates — records `not_run` in a checkout
without its own environment, and the completion gate does not close. The run
says so at the start rather than at `COMMIT`, and `check_module_isolation`
blocks a candidate whose modules resolve elsewhere instead of merely logging it.
Closing this properly means provisioning a candidate-local environment, which
this build does not do.

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

### Paths: one rule

**A pattern is a glob if and only if it contains `*` or `?`. Every other
character, `[` and `]` included, is literal.**

This is a Next.js App Router application, so
`apps/web/src/app/projects/[projectId]/datasets/[datasetId]/page.tsx` is an
ordinary file. The guard used to call `fnmatch`, which reads `[projectId]` as a
character class — and that was wrong in both directions at once: the real file
was **refused**, while `projects/p/datasets/d/page.tsx`, a different and
unauthorised file, was **allowed**, because `p` and `d` are in those classes.

Otherwise: `*` and `?` stay inside one path segment, `**` spans zero or more
segments, and a wildcard-free pattern is a literal path that also owns its
subtree. Forbidden patterns are evaluated first and win.

Two patterns overlap when some concrete path satisfies both — decided exactly,
not inferred from a shared prefix, because a wrong "no" would put two workers in
one file. A wildcard-free pattern owns its subtree, so it is compared as
`P` *and* `P/**`: `apps/web` and `**/package-lock.json` both accept
`apps/web/package-lock.json`, and they overlap.

Whether a claim *takes* a serialized lock is a narrower question: containment,
plus the concrete case. `apps/web/package-lock.json` names a lockfile and takes
the lock; `apps/web/**` could contain one and does not, because owning the web
application is not declaring a lockfile edit. A claim that can reach a
serialized resource without holding its lock is reported at plan validation.

Containment is **sound and deliberately incomplete**: it answers yes only when
one pattern is a literal prefix (optionally followed by `**`) of the other, and
`False` everywhere else means *not established*. Every caller treats that as "no
implicit lock" or "no finding", which is the safe direction — the guard still
refuses the write and the exact overlap check still refuses the concurrency. An
earlier version inferred containment from a single placeholder witness, which
made `src/*p*` appear to contain `src/*`.

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

## What plan validation does and does not prove

`pw-dev validate-spec <path>` runs everything `pw-dev run` checks before
dispatching anybody — the schema, the base commit this repository is actually
at, the adopted policy and budgets, the verification registry, and the path
rules the integration guard will apply — and creates no run, no worktree, no
provider call and no commit. Exit 0 accepted, 1 rejected, 2 malformed.

It establishes that the document is well-formed; that every identifier resolves;
that every concrete declared path survives the real guard; that no two
concurrently eligible tasks share write ownership; that every requirement has an
owning task; that a declared migration has a task that allocates it; that the
budget arithmetic closes; and that the publication policy is the one this run
holds.

It establishes **nothing** about whether the design is correct, whether the
tasks add up to the requirements, or whether the phase is the right one. Every
report ends with that sentence, so a green validation is not quoted as an
approval.

One thing it refuses outright: `accepted_preexisting_failures` may not name a
`required_live` check. Such a check is non-passing at baseline by construction —
its scenario does not exist until the phase writes it — so scoping it out waives
the gate rather than recording a pre-existing failure. The run loop refuses the
same waiver independently, because a specification can arrive by import.

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
