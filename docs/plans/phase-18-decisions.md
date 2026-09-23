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
- Later increments (diff, rollback, replay, erasure reconciliation, concurrent
  GC, full authz matrix, live e2e) are not started.

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

## Security posture of temporal reads (§6)

`apply_policies` (row/column security, `service-enterprise/security.py`) has **no
read-path caller** in the tree — it powers the policy **simulation** feature, not
an enforced gate on data reads. The base dataset preview serves stored
`preview_json` unfiltered; the temporal version preview mirrors that exactly.
So temporal reads open **no new bypass**: they are neither more nor less
filtered than the head preview. If an enforced row/column gate is added later, it
must live at the shared read layer so the head preview and every version preview
are filtered together — not bolted onto one and forgotten on the other.

## Erasure interplay (§2) — still open

P6 gave erasure its mode (correction vs destructive) and a no-silent-success
status, and destructive erasure already refuses to overwrite `is_derived`
datasets. But a destructive erasure of a non-derived dataset still overwrites the
head artifact **in place** (`service-enterprise/service.py` `_write_back`), which
against immutable version snapshots would leave a version row whose
`content_hash` no longer matches its bytes. Reconciling erasure with immutable
snapshots is the dedicated later increment; it is **not** resolved here, and the
version machinery does not yet claim to survive a destructive erasure intact.
