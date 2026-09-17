# Phase 18 — planning requirements from an independent review

**Status:** operator-supplied planning input. This is not a specification, and
it is not a record that any of it has been built.

A Phase 18 specification was generated on 2026-09-17 against commit
`6586b008a20ac71d4f44d9053b24a9bae386fd4c` and preserved at
`.pw-dev/runs/run-20260917-5d5c59dc/phase-spec.json`. It passed structural
validation. An independent review then found the gaps below. That specification
stays exactly as it is, as a historical artifact; this document states what a
replanning must do differently.

Every claim here was checked against the repository at the base commit, and the
evidence is named inline. Where a claim could not be established it says so.

---

## 0. Decisions that are already settled

These are adopted. Do not reopen them, and do not fold any of them into this
phase because it would be convenient.

1. **Phase 16 remains partial.** Its window, statistical/ML, geospatial,
   fuzzy-matching, enrichment and recipe-management families are absent by
   design (`docs/HANDOFF.md` §8 and the known-gaps table).
2. **The IR-only executor cutover remains deferred.** Both executors stay.
3. **Wiring Phase 12 pushdown into extraction runs remains deferred.**
4. **No model calls enter the product runtime.** `service-intelligence` is
   deterministic analysis. The development orchestrator in
   `tools/dev-orchestrator/` is not part of the product.
5. **Alembic performs schema changes only.** Converting stored artifacts is a
   separate, separately executable backfill. A migration does not rewrite files.
6. **Rollback appends a new version.** It never mutates, deletes or renumbers
   history, and it never re-runs the producing pipeline.
7. **Changed-row and per-cell classification require trustworthy identity.**
   Without recorded or caller-supplied identity columns that are unique in both
   snapshots, return duplicate-aware added/removed multisets and state that
   changed/cell classification is unavailable. Do not guess.
8. **Stored-dataset temporal SQL does not intercept SQL sent to external
   sources.** `AS OF` applies to materialised Pipewright datasets. The workbench
   continues to send customer SQL to customer databases untouched
   (`services/service-workbench/src/service_workbench/service.py`).

Phase 18 remains the next phase unless repository evidence at the new base
disproves it. `docs/HANDOFF.md` §8 marks 18 `not started`, depending on 08,
and recommends it next; the roadmap's opening "proposed, not started" line is
stale and the ledger wins.

---

## 1. Inventory every producer and consumer (B1)

The previous plan's integration task covered ingestion, transformations and
pipeline runs. The requirements promise *universal* dataset versioning and
input pins, and the repository has more producers than that.

**Established by reading the code at the base commit:** four services call
`finalize_dataset_materialization_success`
(`services/service-datasets/src/service_datasets/service.py:193`):

| Caller | Site |
|---|---|
| ingestion (uploads) | `services/service-ingestion/src/service_ingestion/service.py:207` (via `finalize_dataset_ingestion_success`) |
| transformations | `services/service-transformations/src/service_transformations/run.py:206` |
| quality quarantine | `services/service-quality/src/service_quality/service.py:220` |
| extraction | `services/service-extraction/src/service_extraction/extract.py:258` |

`service-quality` and `service-extraction` appear in **no** task's
`allowed_paths` in the previous plan. Changing one shared finalisation helper
does not by itself give any of these four correct version publication, pin
recording or run semantics — each has its own transaction boundary, its own
notion of what the logical dataset is, and its own failure path.

Twelve services reference `Dataset.file_path` or read artifact bytes:
`service-comparisons`, `service-connectors`, `service-datasets`,
`service-destinations`, `service-enterprise`, `service-extraction`,
`service-ingestion`, `service-intelligence`, `service-quality`,
`service-reporting`, `service-schedules`, `service-transformations`.

For **each** producer and consumer below, the plan must state: the logical
dataset identity; whether it publishes a version or reads one; its pin and
provenance behaviour; its compatibility strategy during rollout; and the owning
task, paths and tests.

- uploads and the ingestion paths;
- full-refresh and incremental extraction;
- transformation outputs;
- quality quarantine datasets;
- reports, charts, exports and publish operations;
- comparisons, previews, audits and any other direct artifact reader;
- existing enterprise operations that mutate stored data (see §2).

**Extraction needs an explicit answer.** Today a run creates a *new dataset*
per run (`service_extraction/extract.py`). Under a logical-dataset model,
repeated extraction must either append versions to one logical dataset or keep
creating datasets — say which, and say how the watermark and head stay
consistent with that choice for both full-refresh and incremental modes.

Anything left out of scope must be named as a limitation. Do not mark the
corresponding universal requirement complete while a producer or consumer is
outside it.

---

## 2. Immutable snapshots versus enterprise erasure (B2)

`services/service-enterprise/src/service_enterprise/service.py:580` implements
`request_erasure`. When `payload.apply` is set it calls `_write_back` (line
646), which does:

```python
payload = frame.to_csv(index=False).encode()
storage.write_bytes(dataset.file_path, payload)
```

That **overwrites the stored file in place**, and it round-trips through CSV,
losing canonical types. Against immutable content-addressed snapshots it
corrupts a snapshot other versions may share.

The plan must define an explicit lifecycle that:

- prevents an erasure from corrupting an immutable snapshot;
- prevents historical reads or replay from silently undoing an erasure;
- distinguishes **ordinary forward-moving correction** (append a corrected
  version; history remains readable) from an **authorised destructive erasure**
  (the subject's data is removed from historical artifacts too);
- defines what happens to historical metadata, artifact access, shared
  content-addressed references and replay *after* an erasure;
- states, per outcome, what the API reports.

Appending a redacted head and reporting "erased" is the failure to avoid: the
old bytes are still there and still readable through history. If the requested
erasure cannot be completed — because a chunk is shared, or a pinned version
still references it — fail, or report it incomplete and say which datasets were
not erased. Do not report success.

Assign an owning task, paths, and acceptance tests for whichever design is
chosen.

---

## 3. Replay determinism beyond frozen data and steps (B3)

Freezing inputs and steps is not enough. The IR evaluates clock-dependent
functions at execution time:
`services/service-transformations/src/service_transformations/ir/pandas_functions.py:766`
implements `age_years` as

```python
(pd.Timestamp(v), pd.Timestamp(datetime.now(timezone.utc).date()))
```

so a replay six months later returns a different number from the same pinned
inputs and the same recipe. `now` and `today` have the same property.

The plan must:

- define an **execution context** recorded with every run: the frozen
  evaluation instant, the timezone, the semantic/runtime version, and every
  other supported nondeterministic input;
- make replay consume that recorded context rather than the current clock;
- return an **explicit incompatibility result** when a semantic change means
  the original result cannot be reproduced. An unsupported claim of equivalence
  is worse than a stated incompatibility;
- include a test that advances the clock between the original execution and the
  replay and asserts the recorded result, not today's;
- define exactly what **result equivalence** means — row multiset, column set,
  canonical types, ordering, null handling — and test that definition.

**Output pins as well as input pins.** A historical run link, a comparison and
an audit view must resolve the *output version that run produced*, not the
current head, after later runs advance the same logical dataset.

---

## 4. Transaction and concurrent garbage-collection protocol (B4)

A grace period plus a reference scan is not sufficient. Two races must be
closed, not merely made unlikely:

- a publication adds a reference *after* the scan and *before* the delete;
- a replay pins a version while retention is deleting it.

Specify an enforceable protocol — locks, leases, or an equivalent — covering:

- active reads and replay;
- durable input pins;
- publication;
- retention metadata changes;
- physical blob deletion;
- retry and crash recovery.

State explicitly what happens in the interval between eligibility calculation
and actual deletion, and what re-validates in that window.

**Resolve the pin visibility question.** Either a pin is durable *before* any
data is read, or it is protected equivalently inside the same transaction. Do
not rely on an uncommitted pin being visible to a concurrent GC in another
session — it is not.

Include adversarial concurrent tests and rollback/restart scenarios: publication
interleaved with a sweep, replay pinning during deletion, a crash between
metadata change and blob deletion, and a resumed sweep.

**Prefer project-scoped deduplication.** Cross-project content sharing needs a
justified benefit plus a fully specified reference and isolation lifecycle; if
it is proposed, specify both, and keep storage keys, hash-existence probes and
cross-project reference counts out of every API.

---

## 5. Contracts before workers diverge (B5)

The contract task must define, before anything depends on it:

- **publication transaction ownership** — which layer opens and commits it;
- **which helpers flush and which boundary commits**;
- **version-aware read interfaces**;
- **input and output pin contracts**;
- **retention integration hooks**;
- **typed API payloads and error semantics**.

`finalize_dataset_materialization_success`
(`services/service-datasets/src/service_datasets/service.py:193-224`) calls
`db.commit()` internally. Four producers call it. Plan its refactoring in a task
that **owns that file**, and schedule that task before any integration work that
needs a larger atomic transaction spanning version publication and dataset head
advance.

**Define the compatibility meaning of `Dataset.file_path` and
`Dataset.file_type`** (`services/service-datasets/src/service_datasets/models.py:59-61`)
once the authoritative data is a chunk manifest: what they point at, who may
still read them, and when they stop being authoritative. Avoid implicit CSV
round trips that lose canonical types — the erasure path in §2 is an existing
example of exactly that loss.

---

## 6. Centralised authorisation for every new endpoint (B6)

Permission is decided in one place, from method and path:
`services/service-access/src/service_access/permissions.py`. Checked against
that function at the base commit:

| Request | Required role today |
|---|---|
| `GET  .../datasets/{id}/versions` | `viewer` |
| `POST .../datasets/{id}/versions/diff` | `viewer` (`diff` ∈ `READ_ONLY_SEGMENTS`) |
| `POST .../datasets/{id}/versions/query` | **`editor`** — `query` is not in `READ_ONLY_SEGMENTS`, so a read-only temporal query falls through to the write default |
| `POST .../datasets/{id}/versions/rollback` | `editor` |
| `POST .../pipeline-runs/{id}/replay` | `editor` |

So a read-only `AS OF` query would need an editor while an equally read-only
diff needs a viewer. Define the intended role matrix for **history, temporal
read/query, diff, rollback and replay**, assign the central
`permissions.py` change and its tests to a named task, and do not duplicate
ownership or role logic inside the new routes — the module docstring says why.

Also define how historical row and cell responses respect row-level and
column-level security policies: a version from before a policy existed must not
become a way to read what the policy now hides.

---

## 7. Task ownership and dependencies (B7)

- **Assign every application file and test the work touches.** The run audit
  surface is `apps/web/src/features/audit/components/run-audit-page.tsx`,
  reached from `apps/web/src/app/projects/[projectId]/runs/[runId]/audit/page.tsx`.
  The previous plan claimed the route directory and not the component, so the
  task could not have edited the surface it was asked to update.
- **Split the previous monolithic backend task** into smaller verifiable tasks:
  storage; publication and backfill; temporal reads and rollback; diffing.
- **Keep migrations, shared schemas/types and dependency changes serialised** —
  declare `alembic`, `contract:*` and lockfile resources.
- **Check every revised scope against the actual scheduler and guard** before
  submitting: `pw-dev validate-spec <path>` does this without running anything.
- **Parallelise only genuinely independent tasks**, and make sure every worker
  sees its prerequisites in its own checkout — a task depending on the contract
  task starts from that task's integration checkpoint, not the run base.

Path syntax: a declared path is a glob only if it contains `*` or `?`. `[` and
`]` are literal, so
`apps/web/src/app/projects/[projectId]/datasets/[datasetId]/page.tsx` names that
exact file.

---

## 8. Measurable acceptance (B8)

Define, concretely enough to test:

- supported input types and canonical types;
- the **exact** API representation of decimals, timestamps, nulls and nested
  values;
- timestamp and publication ordering, including tie semantics;
- maximum query results and diff page sizes;
- memory and resource limits, with named stress-test fixtures;
- schema evolution during version comparison (added, dropped, retyped columns);
- null and duplicate identity-key behaviour;
- cursor stability across concurrent publication;
- behaviour for a pruned, erased or otherwise unavailable version;
- migration and backfill interruption and idempotence;
- historical navigation and replay compatibility.

Map every accepted requirement to an owning task **and** an executable
verification id. Distinguish mandatory tests from optional diagnostics.

**Verification ids that matter here.** `repo:smoke` is an *optional* diagnostic:
`scripts/smoke-test.sh` exits 0 when `SMOKE_SKIP_NETWORK=1`, and when it does
probe it is satisfied by any process answering `/api/v1/health/live` on the
configured root — including a gateway started from another checkout. It cannot
evidence an authenticated end-to-end workflow.

`repo:live-acceptance` is the required live path. It starts the gateway itself
from the candidate checkout on an ephemeral port with a disposable database,
disposable storage, a generated signing secret and generated test credentials,
and executes every step of `scripts/live-acceptance/<phase-id>.json`. A missing
scenario records `not_run`, unreachable infrastructure records
`infra_unavailable`, a skipped step records `skip` — none of which is a pass.

The scenario file contains **requests and expectations only**. It has no
`launcher`, no `env` and no `cleanup_paths`; declaring any of them is refused,
because a scenario that could choose the program could satisfy the gate with
`python -m http.server`. The placeholders available to a step are
`{test_username}`, `{test_password}` and `{capture:<name>}` — not `{workdir}`,
`{repo}`, `{port}` or the signing secret. The scenario name is derived by the
controller from `phase_id`, so plan the file at
`scripts/live-acceptance/<phase_id>.json` exactly.

If this phase promises a live authenticated scenario, list
`repo:live-acceptance` in `required_verifications` **and** give a task ownership
of `scripts/live-acceptance/**` so the scenario is actually written. It may
**not** appear in `accepted_preexisting_failures`: a scenario that does not
exist yet is non-passing at baseline by construction, so scoping it out waives
the gate, and both plan validation and the run loop refuse that.

`alembic:heads` now asserts exactly one head against the revision graph, and it
is a gate: a plan cannot drop it by omitting it.

A declared migration must be owned by a task whose `allowed_paths` reach
`apps/api-gateway/alembic/versions/**`. Declaring `exclusive_resources:
["alembic"]` without that ownership is refused — a task that cannot write the
revision file cannot allocate the revision, whatever lock it holds.

**One environment limitation to plan around.** A controller checkout does not
get a `.venv`: linking the original checkout's would make editable installs
resolve there, so the checks would run against a different tree. Every check
requiring a virtualenv therefore records `not_run` in a candidate today, which
is not a pass, so a run cannot reach `COMMIT` until the checkout has its own
environment. State this as a risk with a named mitigation rather than assuming
the gate will close.

---

## 9. Honest estimates and budgets (B9)

The adopted limits are 3 parallel workers, 1800 s per task, 14400 s per run and
3 repair rounds. **Do not raise them, and do not assert the whole phase fits
inside them without evidence.**

- Estimate the work per task, and include environment preparation, integrated
  checks and review time, not only the coding.
- Identify the critical path.
- Prefer smaller tasks with resumable checkpoints over few large ones.
- If the phase does not fit one budget, say so and say which tasks a single run
  can reach. Budget exhaustion produces `PAUSED` with work preserved — a
  resumable run, never a completed phase. Plan for that outcome instead of
  asserting it will not happen.

---

## 10. Honest completion claims (B10)

- Do **not** mark Phase 18 complete in `docs/HANDOFF.md` or `docs/roadmap-v2.md`
  as part of producing this specification.
- Do **not** describe the specification as an implemented or tested phase. A
  specification that passes validation is a validated document: validation
  checks structure, identifiers, path scope, budgets and policy, and reads
  nothing about whether the design is right.
- In `open_questions`, fill `resolution` only where an answer has actually been
  adopted, and leave it empty where none has. A question with a proposed
  resolution and an unresolved decision are different things and must be
  distinguishable.
- The tool count discrepancy (`docs/HANDOFF.md` says both 173 and 167;
  `docs/roadmap-v2.md` says 167) is a documentation contradiction to record,
  not a licence to claim Phase 16 is complete.

---

## 11. Run policy for this specification

- `publication_policy.mode` must be **`none`**, matching the adopted policy the
  planning run holds. The execution command uses `--publish none`.
- `base_commit` must be exactly the commit this planning run reports, and must
  not be edited afterwards.
- `resource_limits` must be within the adopted limits in §9.
- Adopting a different publication policy later is a fresh planning, validation
  and run cycle, not an edit to this document or to a recorded run.
