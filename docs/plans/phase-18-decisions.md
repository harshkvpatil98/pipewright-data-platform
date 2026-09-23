# Phase 18 (time travel) — implementation decisions

Companion to `phase-18-review-requirements.md`. That document is the accepted
requirements; this one records the decisions taken as the increments are built,
so a later reader can tell what was chosen from what is still open. Re-verify
against the tree before relying on line-level claims.

## Increment status

- **Increment 1 — version storage & publication:** done (2026-09-23). See the
  handoff session log and `docs/plans/production-readiness-workflow.md` P7.
- **Increment 2 — temporal reads + this per-producer write-up:** done
  (2026-09-23).
- **Diff and rollback:** done (2026-09-23; commits `43dd11b`, `b1128d2`).
- **Erasure reconciliation (§2):** done (2026-09-23; commit `5ca73a3`) — see below.
- **Concurrent GC protocol (§4) + a `dataset_versions` retention policy:** done
  (2026-09-23) — see below.
- **Execution context + frozen clock (§3):** done (2026-09-23) — see below.
- **Deterministic replay (§3):** done (2026-09-23) — see below.
- **`AS OF` SQL query (decision #8):** done (2026-09-23) — see below.
- The scripted live end-to-end acceptance (§8) and the handoff close-out follow.

## §1 — Producer and consumer inventory

Every successful materialisation appends one `dataset_versions` row through the
publication seam in
`services/service-datasets/src/service_datasets/service.py`
(`apply_dataset_materialization_success` / `finalize_…`). Because all four
producers reach that seam, recording is uniform. What differs is the **logical
dataset identity** each producer assigns — and that determines whether history
accumulates on one dataset or spreads across many.

| Producer | Site | Logical dataset today | Versions it produces |
|---|---|---|---|
| Uploads / ingestion | `service-ingestion/service.py:124` | a fresh `Dataset` placeholder per upload | version 1 |
| Extraction | `service-extraction/extract.py:236` | a fresh `Dataset` per run (incremental data is read from the job's `target_dataset_id` and merged into the frame, but the **output is always a new dataset**) | version 1 |
| Transformations | `service-transformations/run.py:176` | a fresh derived `Dataset` per run | version 1 |
| Quality quarantine | `service-quality/service.py` | a fresh quarantine `Dataset` | version 1 |

**Consequence, stated plainly:** today **no producer re-materialises an
existing dataset**, so in the current product every dataset has exactly one
recorded version. `version_number > 1` on a single logical dataset arrives only
when a later increment writes back to an existing dataset — chiefly **rollback**
(settled decision #6: rollback appends a new version), and any future
"re-run into the same dataset" path. The version table, the monotonic numbering,
the unique constraint and the temporal read are all in place for that; they are
not yet exercised by a multi-run history in normal use. The Version history
panel therefore shows a single row for most datasets today, and says so when a
dataset has no recorded history at all.

### Extraction — the explicit answer §1 asks for

Extraction **keeps creating a dataset per run** (it does not append versions to
one logical extraction dataset). Rationale: the incremental **watermark lives on
the `ExtractionJob`, not on the dataset**, so watermark/head consistency does not
depend on dataset identity — full-refresh and incremental modes both advance the
job watermark after a successful write, independently of how many datasets exist.
Collapsing repeated extraction onto one logical dataset (so each run appends a
version) is a deliberate later refinement, not a bug; it is called out here so
the universal-versioning requirement is **not** marked complete for extraction.

### Consumers / readers

Readers continue to use `Dataset.file_path` (the head) unchanged; the temporal
read (`get_dataset_version_preview`) is the only version-aware read so far, and
it serves the preview snapshot captured at publication. The twelve services that
read `Dataset.file_path` are unaffected by increments 1–2 — `file_path` remains
authoritative for the head. Redefining `file_path`'s authority against a chunk
manifest (§5) is deferred with the content-addressed-storage increment.

## Role matrix (§6) — decided, pinned in `service_access/tests/test_permissions.py`

| Request | Role | How |
|---|---|---|
| `GET …/versions`, `GET …/versions/{n}`, `GET …/versions/{n}/preview` | viewer | read method |
| `POST …/versions/diff` | viewer | `diff` ∈ `READ_ONLY_SEGMENTS` |
| `POST …/versions/query` (temporal SQL) | viewer | `query` added to `READ_ONLY_SEGMENTS` — no route uses it for a write |
| `POST …/versions/{n}/rollback` | editor | `rollback` ∈ `EDITOR_SEGMENTS` |
| `POST …/runs/{id}/replay` | editor | `replay` ∈ `EDITOR_SEGMENTS`, which is checked **before** `OPERATOR_SEGMENTS` so the `runs` segment cannot demote it to operator |

`EDITOR_SEGMENTS` is new: actions that publish or re-execute by hand change what
the current data *is*, which is more than "run the nightly job" and less than an
access change. It is decided centrally in `permissions.py`; no route carries
role logic.

## Execution context and replay (§3) — decided

`service_transformations/ir/clock.py` is the one clock. `now()`, `today()` and
`age_years()` read `evaluation_instant()`; a run freezes one instant at its
start (`ExecutionContext.evaluated_at`, always UTC) and evaluates the whole
recipe against it; a replay installs the recorded instant instead. `age_years`
also accepts an explicit as-of second argument. `today()` is therefore the UTC
date of the instant, no longer the host's local date — stated here because it
is a (deliberate) semantic change.

Every transformation run records in `summary_json.execution_context`: schema,
`semantic_version` (`execution_context.SEMANTIC_VERSION`, bumped when a step's
or function's meaning changes so old results become irreproducible), the
instant and timezone, the clock-function list, the exact `steps` that ran with
a `steps_digest`, `inputs` (the head version of the base dataset and of every
dataset a join/union read — `{dataset_id, version_number, content_hash, role}`),
and `outputs` (the version it published). Failed runs record the context too.

`POST …/runs/{id}/replay` (editor) pins every input durably (§4) before a byte
is read, runs the **recorded** steps against the **pinned** versions at the
**recorded** instant (`ReplayPlan` in `run.py`), publishes the result as a new
dataset (`run_type = dataset_transformation_replay`, context `replay_of` set),
releases the pins, and compares with the original output pin. **Result
equivalence** is: identical content digest, or else the same ordered column
list, the same canonical type per column, and the same row multiset with
values compared as text and null equal to null; row order is not part of it.
Outcomes are `equivalent`, `divergent` (differences listed), `incompatible`
(semantic version moved / a recorded step no longer exists — never claimed
equivalent), `unavailable` (an input was pruned, deleted, or its bytes
rewritten by a destructive erasure — a different input), `failed`,
`unverifiable` (the original output is gone). The run audit surface shows the
output pins for **every** producer's runs (from the version table's run link),
the context, and the Replay action; a run that cannot be replayed says why.

Test that advances the clock: `test_replay.py::test_a_replay_reproduces_the_recorded_result_not_todays`
edits the pipeline and moves the clock ten years, then replays — the recorded
ages come back.

## `AS OF` SQL over stored datasets (decision #8) — decided

`POST …/datasets/{id}/versions/query` (viewer; `query` is a read-only segment)
lives in `service_workbench/temporal.py` because the workbench owns SQL
execution. It never touches SQL sent to customer databases. The request names
a `version_number` **or** an `as_of` instant (neither → the head); the
resolved version's artifact is loaded into a private in-memory SQLite database
as a table named `dataset`, and one SELECT runs there under the workbench's
read-only policy (15 s timeout, `row_limit` ≤ 1000, `truncated` reported).
Only a `read` statement is accepted — a write is refused with a sentence that
does not offer a write mode, because there is none.

§8 answers: **ordering** — "as of T" is the greatest `created_at ≤ T`, ties on
the higher version number; an instant before version 1 is a 404 naming when
version 1 was published, never the head. **Representation** — the workbench's
own JSON rendering: decimals as text, timestamps ISO 8601, nulls as null,
nested values as JSON text. **Pruned** — 409 with the reason. UI: a Query
action per readable version and a "Query as of" control on the history panel.

## Security posture of temporal reads (§6)

`apply_policies` (row/column security, `service-enterprise/security.py`) has **no
read-path caller** in the tree — it powers the policy **simulation** feature, not
an enforced gate on data reads. The base dataset preview serves stored
`preview_json` unfiltered; the temporal version preview mirrors that exactly.
So temporal reads open **no new bypass**: they are neither more nor less
filtered than the head preview. If an enforced row/column gate is added later, it
must live at the shared read layer so the head preview and every version preview
are filtered together — not bolted onto one and forgotten on the other.

## Erasure interplay (§2) — decided

`service-enterprise/service.py` (`_erase_by_correction`, `_erase_destructively`):

- A **correction** appends a corrected version through the same publication seam
  as every producer. The head advances to clean bytes; history — including the
  version that still holds the subject — stays readable, and the new version's
  hash tells the truth. This is the forward-moving path.
- An authorised **destructive** erasure rewrites the live artifact *and every
  historical version artifact* in place (the one sanctioned exception to version
  immutability), re-records each `content_hash` to match the new bytes, rebuilds
  the previews that carried the subject as raw rows, and reports a version whose
  artifact cannot be read as **blocked by name** — never silently skipped. A
  version already **pruned** by retention has no bytes and no preview left, so it
  is treated as already clean, not as an unreadable blocker.
- The API reports `completed` only when nothing was blocked; otherwise `partial`
  with the blocked list. There is no "erased" that leaves readable old bytes.

## Concurrent GC protocol (§4) — decided

`service_datasets/version_lifecycle.py` is the whole protocol; nothing else
decides when bytes go.

- **Pins are durable before any bytes are read.** `pin_version` writes a
  `dataset_version_pins` row under a row lock on the version (`SELECT … FOR
  UPDATE` on PostgreSQL; SQLite serialises writers itself), the caller
  **commits**, and only then reads. Rollback pins its target for the copy and
  releases it in the same commit that publishes the restored head. An
  uncommitted pin is never relied on.
- **Deletion is two durable steps with re-validation between them.** A
  `dataset_versions` retention policy (report-only by default, like every
  policy) first **marks** eligible versions `pending_delete` with a lease
  (`delete_after = now + 30 min`). Eligible means: published before the cutoff,
  `active`, **never the head**, **never pinned**. A later pass — the schedule
  ticker runs one every loop, and the governance page's sweep button runs one on
  demand — takes each due version's row lock, re-checks it is still pending,
  still not the head and still unpinned, and only then tombstones it
  (`pruned`, `pruned_at` set, `preview_json` cleared; digest, counts and schema
  kept). Bytes are deleted **after** that commit; `artifact_removed_at` records
  it. One pass can never mark and remove the same version (schedule runs before
  prune inside a pass), so the earliest a version can go is the next pass after
  its lease.
- **Between eligibility and deletion:** the version is readable (the lease
  exists so in-flight reads finish); a new pin **rescues** it back to `active`;
  a pin attempted after the tombstone is refused with the reason (409).
- **Crash and resume:** a crash between tombstone and blob deletion leaves
  `artifact_removed_at` null; the next pass retries the delete (a missing file
  counts as removed). Bytes shared with a live head or another unpruned version
  are never deleted; the version is marked removed with nothing to do.
- **No cross-project dedup.** Storage keys, reference counts and existence
  probes stay out of every API; a tombstone exposes `retention_state`,
  `pruned_at`, `delete_after` and `active_pins` only.
- Reads of a pruned version (preview, diff, rollback, and the temporal query
  when it lands) answer with the reason rather than an empty table.

Tests: `service-datasets/tests/test_version_lifecycle.py` (pin before mark,
pin after mark within the lease, pin after prune, two-session visibility, crash
between tombstone and delete + resumed sweep, shared bytes, tombstone reads,
rollback pin/release/rescue) and `service-enterprise/tests/test_version_retention.py`
(policy report-only → schedule → prune; ticker sweep; erasure over a tombstone).
