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
| a checkpoint's `verification_ids` | run when that task integrates, against the candidate, and block its dependents until they pass |
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

### Every checkout gets an environment that imports its own code

A git worktree has no `.venv`, so every check declaring `requires=("venv",)` —
ten of the fourteen, including the `repo:verify` and `alembic:heads` gates —
used to record `not_run`, and a run could never close its completion gate.

Symlinking the original `.venv` would have been the short fix and the wrong one.
Pipewright installs its twenty-six first-party packages with `pip install -e`,
so that virtualenv imports the *original* checkout's source: the checks would
run, and every one of them would be verifying a tree nobody is publishing.

`workspace/pyenv.py` builds each checkout its own virtualenv instead, and
composes `sys.path` so the two questions get different answers:

```
<checkout>/.venv/lib/pythonX.Y/site-packages/_pw_dev_sources.pth
    <checkout>/packages/*/src          first-party: this checkout
    <checkout>/services/*/src
    <checkout>/apps/api-gateway/src
    <checkout>/tools/dev-orchestrator/src
    <root>/.venv/.../site-packages     third-party: shared, and only packages
```

Adding the shared directory to `sys.path` does not make it a *site* directory,
so the `__editable__.*.pth` files inside it are never processed and the original
checkout's sources never appear. Nothing is installed, nothing is downloaded,
and preparation takes well under a second — which is why every worker checkout
and the candidate can each have one.

- **It is proved, not assumed.** Before a worker starts and before the candidate
  is verified, the checkout's interpreter is asked where it resolves
  `api_gateway`, `shared_python`, `service_datasets` and `pw_dev` from. Anything
  outside the checkout blocks the run.
- **It is checked before the provider is called.** A checkout that cannot verify
  its own code is knowable in a tenth of a second; finding out afterwards costs
  an implementation call to learn it.
- **Staleness is a decision.** The inputs are digested into a stamp, so a
  resumed run rebuilds an environment built for a different tree instead of
  inheriting it.
- **A new dependency is named.** A checkout that declares a third-party
  requirement the shared installation predates cannot be given it. The names are
  reported; the check then fails on the import, visibly.
- **Nothing is borrowed that would break isolation.** The shared directory is
  referenced by path, and a worker's sandbox grants writes under its own
  checkout only. No `.env`, credential store or database is copied.

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

### Verification checkpoints

A task's `verification_ids` used to be advisory: the controller ran what the
*worker asked for*, recorded the outcomes as events, integrated the patch and
released the dependents regardless. A plan promising "documentation is updated
only after the verification task passes" was describing an ordering nothing
enforced.

**A task with `role: "verification"` is a checkpoint.** Its declared
`verification_ids` are required, and three things make that mean something:

- **the controller chooses what runs**, from the accepted specification. A
  worker that omits them from `verification_requests`, or asks for something
  easier, changes nothing;
- **they run against the integrated candidate**, not the worker's checkout, so
  what is verified is the tree the phase is building;
- **only `pass` releases the dependents.** `fail`, `skip`, `not_run`,
  `infra_unavailable`, `timeout` and `error` each say something different and
  none of them says the work is done. `accepted_preexisting_failures` does not
  apply either: that is for a check the phase inherited broken, and a checkpoint
  is a statement about this phase's own work.

The passing candidate fingerprint is recorded. A resumed run re-reads the
durable evidence and inherits a verdict only when it still describes the current
candidate; otherwise it rechecks. Ordinary tasks are unchanged — a worker asking
for `python:service` while it iterates does not thereby make that check a
completion gate for the phase.

A checkpoint that declares **no** `allowed_paths` is executed by the controller
with no worker at all: "run these checks and tell me the answer" is controller
work, and dispatching somebody to ask for it would spend an implementation call
on a result they cannot influence. Every other role must own something — a
worker that owns nothing cannot produce a patch, and there would be no scope
against which to judge what it did.

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
seconds, provider retries, repair rounds, output size.

### Five different durations, kept apart

| | What it bounds | Limit |
|---|---|---|
| provider call | one `claude -p` or `codex exec` invocation answering | `per_task_seconds`, `plan_seconds`, `review_seconds` |
| environment preparation | giving one checkout an interpreter | `environment_seconds` |
| controller verification | one registry check running | each `Check.timeout_seconds` |
| integration and review | applying patches, fingerprinting, the reviewer's own call | inside the run budget |
| the run | everything above, end to end | `total_run_seconds` |

**`per_task_seconds` is a timeout, not an estimate.** A task that finishes in a
minute does not consume thirty, so no arithmetic over it predicts a duration.
What it bounds is the worst case, and plan validation reports the three things
that force provider calls apart in it:

| Bound | What forces it |
|---|---|
| longest dependency chain | no number of workers shortens it |
| `ceil(worker tasks / workers)` | W workers run at most W calls at once |
| largest resource-serialized set | one holder at a time, run-wide |

The largest of the three, times `per_task_seconds`, is the floor.

`ceil(tasks / workers) x per_task_seconds` is **not a ceiling** — five tasks in a
dependency chain with three workers still run one after another, so as an upper
bound it understates, which is the dangerous direction. It is a perfectly good
*lower* bound, which is why it is one of the three rather than discarded.

Only tasks that dispatch a worker are counted: a controller-executed checkpoint
consumes check time, not a provider timeout. Environment preparation, controller
verification, integration and review are excluded from all three, and the
message says so rather than folding them in as though they were free.

### Which conditions produce which state

| Condition | State |
|---|---|
| `total_run_seconds` spent | `PAUSED`, resumable, work preserved |
| a provider did not answer within its timeout | `PAUSED` |
| `repair_rounds_per_task` exhausted | `PAUSED` |
| a provider refused: rate limit, auth, unknown model | `BLOCKED`, resumable, with the provider's own reason |
| a checkpoint did not pass | `BLOCKED`, naming the checks and the dependents held back |
| a worker wrote outside its scope, or a plan broke policy | `BLOCKED` |

`PAUSED` is for the budgets this tool set; `BLOCKED` is for a condition it may
not decide alone. Both preserve the work and both resume. Neither is a completed
phase, and the distinction is kept because "we ran out of time" and "the
provider refused" call for different actions.

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
