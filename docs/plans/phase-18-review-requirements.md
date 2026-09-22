# Phase 18 (time travel) — accepted requirements

**Status:** accepted requirements for a future implementation. Nothing here is
a record that any of it has been built. The distinction between a *proposal*,
*accepted requirements*, an *implementation*, and *verified completion* is
load-bearing: this document is the second of those four.

**History.** These requirements were distilled from an independent review of a
generated Phase 18 specification (2026-09-17, against commit `6586b008`), which
found the gaps below. That specification, its eight review rounds and the full
planning record are preserved locally in
`backups/orchestrator-removal-2026-09-22/planning/` (see that directory's
`RECOVERY.md`); the tooling that produced and executed such specifications was
removed on 2026-09-22, and this document stands alone. An unfinished,
unreviewed implementation attempt (28 commits) is preserved as branch
`pw-dev/run-20260918-d770792f/candidate` — treat it as reference material, not
as a starting point whose claims can be adopted without evidence.

Every claim here was checked against the repository at the 2026-09-17 base
commit, and the evidence is named inline. Re-verify line numbers against the
current tree before relying on them.

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
   deterministic analysis.
5. **Alembic performs schema changes only.** Converting stored artifacts is a
   separate, separately executable backfill. A migration does not rewrite
   files.
6. **Rollback appends a new version.** It never mutates, deletes or renumbers
   history, and it never re-runs the producing pipeline.
7. **Changed-row and per-cell classification require trustworthy identity.**
   Without recorded or caller-supplied identity columns that are unique in both
   snapshots, return duplicate-aware added/removed multisets and state that
   changed/cell classification is unavailable. Do not guess.
8. **Stored-dataset temporal SQL does not intercept SQL sent to external
   sources.** `AS OF` applies to materialised Pipewright datasets. The
   workbench continues to send customer SQL to customer databases untouched
   (`services/service-workbench/src/service_workbench/service.py`).

Phase 18 remains the next phase unless repository evidence disproves it.
`docs/HANDOFF.md` §8 marks 18 `not started`, depending on 08, and recommends it
next; the roadmap's opening "proposed, not started" line is stale and the
ledger wins.

---

## 1. Inventory every producer and consumer

The requirements promise *universal* dataset versioning and input pins, and the
repository has more producers than the obvious three.

**Established by reading the code at the base commit:** four services call
`finalize_dataset_materialization_success`
(`services/service-datasets/src/service_datasets/service.py`):

| Caller | Site |
|---|---|
| ingestion (uploads) | `services/service-ingestion/src/service_ingestion/service.py` (via `finalize_dataset_ingestion_success`) |
| transformations | `services/service-transformations/src/service_transformations/run.py` |
| quality quarantine | `services/service-quality/src/service_quality/service.py` |
| extraction | `services/service-extraction/src/service_extraction/extract.py` |

Changing one shared finalisation helper does not by itself give any of these
four correct version publication, pin recording or run semantics — each has its
own transaction boundary, its own notion of what the logical dataset is, and
its own failure path.

Twelve services reference `Dataset.file_path` or read artifact bytes:
`service-comparisons`, `service-connectors`, `service-datasets`,
`service-destinations`, `service-enterprise`, `service-extraction`,
`service-ingestion`, `service-intelligence`, `service-quality`,
`service-reporting`, `service-schedules`, `service-transformations`.

For **each** producer and consumer below, the implementation must state: the
logical dataset identity; whether it publishes a version or reads one; its pin
and provenance behaviour; and its compatibility strategy during rollout — with
tests:

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

## 2. Immutable snapshots versus enterprise erasure

`services/service-enterprise/src/service_enterprise/service.py` implements
`request_erasure`. When `payload.apply` is set it calls `_write_back`, which
does:

```python
payload = frame.to_csv(index=False).encode()
storage.write_bytes(dataset.file_path, payload)
```

That **overwrites the stored file in place**, and it round-trips through CSV,
losing canonical types. Against immutable content-addressed snapshots it
corrupts a snapshot other versions may share.

The implementation must define an explicit lifecycle that:

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

Whichever design is chosen needs acceptance tests covering each of these
outcomes.

---

## 3. Replay determinism beyond frozen data and steps

Freezing inputs and steps is not enough. The IR evaluates clock-dependent
functions at execution time:
`services/service-transformations/src/service_transformations/ir/pandas_functions.py`
implements `age_years` as

```python
(pd.Timestamp(v), pd.Timestamp(datetime.now(timezone.utc).date()))
```

so a replay six months later returns a different number from the same pinned
inputs and the same recipe. `now` and `today` have the same property.

The implementation must:

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

## 4. Transaction and concurrent garbage-collection protocol

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

Include adversarial concurrent tests and rollback/restart scenarios:
publication interleaved with a sweep, replay pinning during deletion, a crash
between metadata change and blob deletion, and a resumed sweep.

**Prefer project-scoped deduplication.** Cross-project content sharing needs a
justified benefit plus a fully specified reference and isolation lifecycle; if
it is proposed, specify both, and keep storage keys, hash-existence probes and
cross-project reference counts out of every API.

---

## 5. Contracts before the pieces diverge

Define, before anything depends on it:

- **publication transaction ownership** — which layer opens and commits it;
- **which helpers flush and which boundary commits**;
- **version-aware read interfaces**;
- **input and output pin contracts**;
- **retention integration hooks**;
- **typed API payloads and error semantics**.

`finalize_dataset_materialization_success`
(`services/service-datasets/src/service_datasets/service.py`) calls
`db.commit()` internally, and four producers call it. Refactor it **first**,
before any work that needs a larger atomic transaction spanning version
publication and dataset head advance — retrofitting transaction ownership after
integrations exist is how partial-publication bugs get shipped.

**Define the compatibility meaning of `Dataset.file_path` and
`Dataset.file_type`** (`services/service-datasets/src/service_datasets/models.py`)
once the authoritative data is a chunk manifest: what they point at, who may
still read them, and when they stop being authoritative. Avoid implicit CSV
round trips that lose canonical types — the erasure path in §2 is an existing
example of exactly that loss.

Keep Alembic migrations serialised (this repository holds exactly one head —
check with `.venv/bin/alembic -c apps/api-gateway/alembic.ini heads`), and land
shared schema/type changes before their consumers.

---

## 6. Centralised authorisation for every new endpoint

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
read/query, diff, rollback and replay**, change it centrally in
`permissions.py` with tests, and do not duplicate ownership or role logic
inside the new routes — the module docstring says why.

Also define how historical row and cell responses respect row-level and
column-level security policies: a version from before a policy existed must not
become a way to read what the policy now hides.

---

## 7. Implementation shape

- **Work in small, verifiable increments** — storage; publication and
  backfill; temporal reads and rollback; diffing — rather than one monolithic
  change, and run the full gate between increments.
- The run audit surface is
  `apps/web/src/features/audit/components/run-audit-page.tsx`, reached from
  `apps/web/src/app/projects/[projectId]/runs/[runId]/audit/page.tsx` — the
  component, not just the route, needs updating for output pins.
- Migration and backfill must be separately executable and idempotent under
  interruption (settled decision #5).

---

## 8. Measurable acceptance

Define, concretely enough to test:

- supported input types and canonical types;
- the **exact** API representation of decimals, timestamps, nulls and nested
  values;
- timestamp and publication ordering, including tie semantics;
- maximum query results and diff page sizes;
- memory and resource limits, with named stress-test fixtures;
- schema evolution during version comparison (added, dropped, retyped
  columns);
- null and duplicate identity-key behaviour;
- cursor stability across concurrent publication;
- behaviour for a pruned, erased or otherwise unavailable version;
- migration and backfill interruption and idempotence;
- historical navigation and replay compatibility.

Every accepted requirement must map to an executable check. Distinguish
mandatory tests from optional diagnostics.

**Live end-to-end evidence.** A smoke pass is not end-to-end evidence:
`scripts/smoke-test.sh` exits 0 when `SMOKE_SKIP_NETWORK=1`, and when it does
probe it is satisfied by any process answering `/api/v1/health/live` — including
a server started from another checkout. The phase's acceptance needs an
executable end-to-end script (the `scratchpad/e2e_*.sh` pattern in
`docs/HANDOFF.md` §9) run against a gateway started **from the checkout under
test**, exercising the authenticated workflow: publish versions, temporal
query, diff, rollback, replay. Record what actually ran; a skipped step is not
a pass.

---

## 9. Honest completion claims

- Do **not** mark Phase 18 complete in `docs/HANDOFF.md` or
  `docs/roadmap-v2.md` on the strength of a design or a partial
  implementation. Completion is: the accepted requirements are met, the tests
  above exist and pass, and `npm run verify` is green.
- Keep unresolved questions visibly unresolved. A question with a proposed
  answer and an adopted decision are different things and must be
  distinguishable.
- The tool count discrepancy (`docs/HANDOFF.md` says both 173 and 167;
  `docs/roadmap-v2.md` says 167) is a documentation contradiction to record,
  not a licence to claim Phase 16 is complete.
