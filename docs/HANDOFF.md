# HANDOFF — read this first

**Purpose:** this file lets a brand-new session (with zero context) pick up exactly where the
last one stopped. Keep it current. If you change project state, update the **Progress ledger**
and **Session log** at the bottom before you finish.

**Last updated:** 2026-08-21
**Updated by:** session `5754fbb2` (Phases 08, 09, 12, 13, 14 complete; roadmap v2 phases 10-11, 15-23 remain)

---

## 1. What this is

**Pipewright** — an ETL platform. Monorepo:

```
apps/api-gateway      FastAPI gateway; mounts every service's router. Alembic lives here.
apps/web              Next.js 16 App Router, React 19, TS 5.9, Tailwind v4, Vitest
packages/shared-python  storage, errors, common utilities
packages/shared-types   TS contracts mirroring Python schemas
packages/shared-ui      shared React components
services/service-*      22 Python service packages (the actual domain logic)
scripts/                setup, dev, test, verify, backup
docs/                   case study, disaster recovery, roadmaps
```

**Stack:** FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pandas · pyarrow · fastavro ·
httpx · boto3 · openpyxl · PyJWT · Postgres. Frontend has **no icon library and no chart
library** — every icon and chart is hand-written SVG. Keep it that way.

---

## 2. Getting running (cold start)

```bash
cd "/Users/harsh/Downloads/Projects/Intelligent ETL"

# 1. Postgres must be up first — dev.sh refuses to start without it
docker compose up -d postgres

# 2. One-time setup (creates ./.venv, installs Python + npm workspaces, runs migrations)
npm run setup

# 3. Run both servers (backend :8000, frontend :3000 by default)
npm run dev
#    override with BACKEND_PORT / FRONTEND_PORT env vars
```

**Login:** `platform-admin` / `change-me-now`

**Requires Homebrew `python@3.12`.** The system Python will not work. If `npm run setup` fails
on the venv, that is usually why.

### The verification gate — run this after every change

```bash
npm run verify     # ruff + pytest + ESLint + tsc + production build
```

Everything must be green before moving on. Current baseline: **1,256 Python tests,
111 web tests, all passing.**

Other commands: `npm test` (tests only) · `npm run smoke` (end-to-end smoke) ·
`npm run lint` · `npm run typecheck` · `scripts/backup.sh --verify` (real restore drill).

### Running one service's tests

```bash
.venv/bin/python -m pytest services/service-transformations -q
```

---

## 3. Repo state

- **Everything is pushed.** The remote is `harshkvpatil98/pipewright-data-platform` on
  branch `main`, and it holds the whole platform: the ~15 setup fixes to the original
  repo, roadmap v1 phases 01–07, and roadmap v2 phases 08, 09, 12, 13, 14, 15 and 16.
- A cloud agent *can* now continue this work — cloning the repo gets the real thing.

**Not in the repo, by design:** `.env` files, `apps/api-gateway/data/` (uploaded and
derived files), `*.tsbuildinfo`, `__pycache__/`, `.venv/`, `node_modules/`, `.next/`,
`backups/`, and editor leftovers. See `.gitignore`; every exclusion there has a comment
saying why.

**Still ask before pushing.** The first push was explicitly authorised; that authorisation
was for that push, not a standing one.

---

## 4. Where the project stands

### Phases 01–07: complete

| # | Phase | Service(s) added | Notes |
|---|---|---|---|
| 01 | Orchestration | `service-workflows` | DAG, queue/worker, canvas, cron, backfills, macros |
| 02 | Trust | `service-lineage`, `service-observability` | Column lineage (derived, never stored), anomalies, incidents |
| 03 | Team | `service-access`, `service-governance` | Roles, versions, approvals, audit log |
| 04 | Reach | `service-connectors` | Connector SDK + conformance suite, 19 connectors |
| 05 | Consumption | `service-reporting` | Charts, dashboards, pivots, Excel export, catalog |
| 06 | Intelligence | `service-intelligence` | PII, join keys, entity resolution — **no model calls** |
| 07 | Enterprise | `service-enterprise` | Tenancy, row/column security, retention, SSO, `/metrics` |

**Migrations:** `apps/api-gateway/alembic/versions/`, 27 files, head is `0027_writeback_change_sets`.

### Roadmap v2: in progress

See [`roadmap-v2.md`](./roadmap-v2.md) — 16 phases across 4 tracks, ≈58 sessions.
Phases **08, 09, 12, 13, 14, 15** are done; the progress ledger in §8 tracks the rest.

---

## 5. Architecture rules — violating these breaks things

1. **Permission is decided in exactly one place.** A FastAPI dependency on the whole API router
   reads HTTP method + path (`service_access/permissions.py`). Do **not** add per-route
   ownership checks. Unrecognised write paths require `editor` — it fails closed by design.
2. **Tenancy is enforced in the same place project access is** —
   `service_projects.contracts.project_role`, via a registered resolver. Never as a filter each
   service remembers to apply.
3. **Cross-service dependencies use registered hooks, never imports.** The pattern is
   `register_role_resolver`, `register_snapshotter`, `register_reference_resolver`. A service
   importing another service that imports it back is a cycle — the hooks exist to avoid this.
4. **Use `sqlalchemy.Uuid`, never `sqlalchemy.dialects.postgresql.UUID`.** SQLite gives the
   latter NUMERIC affinity and an all-digit UUID silently becomes a float. This was fixed across
   16 model files; do not reintroduce it.
5. **The workflow worker must `import api_gateway.metadata`** or SQLAlchemy mappers fail to
   resolve. Internal endpoints mount at the **root**, not under `/api/v1`.
6. **Lineage is derived, never stored.** `service_lineage/columns.py` symbolically executes
   steps. Adding a transformation step means updating it, and a test enforces
   `KNOWN_STEP_TYPES == ALL_STEP_TYPES`.
6a. **In an IR `Join`, sides in the condition are POSITIONAL** — first operand is the left
   input, second is the right. Resolving by name lookup makes `eq(region, region)` compile to
   `t1.region = t1.region`, which is always true, so the join silently becomes a cartesian
   product. Both backends follow the convention; `test_ir_differential.py` enforces it.
7. **Connector capabilities describe what works *here*.** A connector without its driver
   declares only `test` and `available=False`. The conformance suite enforces that a declared
   capability has a backing method.
8. **Every inference reports its `method`.** `service-intelligence` responses carry a field
   saying what produced them. No result appears that cannot explain itself.

---

## 6. Gotchas that have already cost time

- **pytest uses `--import-mode=importlib` with no `__init__.py` files.** Two `conftest.py`
  files with the same basename collide and one silently supplies the other's fixtures. Fixtures
  are inlined per module. Do not add a shared `conftest.py` without checking for collisions.
- **`curl -F "file=@x.csv"` sends `application/octet-stream`** and the upload endpoint rejects
  it. Use `-F "file=@x.csv;type=text/csv"`.
- **`created_at` defaults to `now()`, which in Postgres is the *transaction* time.** Every row
  written in one request ties. Order by an explicit `sequence` column instead.
- **`HTTPServer.server_bind` calls `socket.getfqdn()`** which blocks ~35s per fixture on macOS.
  The REST connector tests subclass it. Reuse that pattern for any new loopback server.
- **Falsy-zero bugs.** `if tile.position` treated position 0 as unset. Prefer `is not None`.
- **`npm run dev` refuses to start if Postgres is unreachable** — that error is accurate, start
  Docker.

---

## 7. Known gaps — stated, not hidden

These are deliberate and documented, not oversights. Do not quietly "fix" them by relaxing the
honesty; if you verify one, update its status here.

| Gap | Why |
|---|---|
| 5 SaaS connectors never run live | Stripe/HubSpot/Shopify/Salesforce/Sheets — no credentials on this machine |
| OIDC network legs never run | Token exchange + JWKS written to spec; no IdP available |
| SAML absent | Needs `xmlsec`; a SAML that skips signature checking is an auth bypass |
| 5 warehouse connectors driver-gated | Snowflake/BigQuery/Redshift/SQL Server/Oracle declare `test` only |
| PDF export absent | No layout engine; HTML export prints correctly from a browser |
| Write-back run only against SQLite | PostgreSQL and MySQL paths are written and dialect-aware; no server on this machine to run them |
| Write-back does not cover files or SaaS | A file-backed dataset is a replayable recipe in the Studio, which is a better answer than a destructive rewrite. Write-back exists for live tables the platform does not own |
| No three-way conflict resolution UI | A stale row stops the commit and names the statement; choosing "theirs" or "yours" per row is its own screen |
| Tool library is 167, not the roadmap's 420 | Window, statistical/ML, geospatial, fuzzy-matching, enrichment and recipe-management families are absent by name in `roadmap-v2.md`. Each needs something the IR does not have yet (a window node, a geometry type, a network policy) rather than more declarations |

---

## 8. Progress ledger — roadmap v2

**Update this table when you finish a phase.** Status: `not started` / `in progress` / `done`.

| # | Phase | Status | Sessions | Notes |
|---|---|---|---|---|
| 08 | Type system & IR | **done** | 4/4 | Types, IR, 2 backends, 20 steps, IR-derived lineage. Cutover deliberately deferred — see below |
| 09 | Design system & themes | **done** | 2/2 | Graphite/teal/copper; light+dark+system; density |
| 10 | Connector factory (→250) | not started | 0/6 | Needs 08 |
| 11 | Ingestion intelligence | not started | 0/3 | Needs 08 |
| 12 | Pushdown & dialects | **done** | 4/4 | Surfaces, planner, plan executor, plan panel. Not yet wired into runs |
| 13 | Data grid | **done** | 4/4 | Canvas grid, selection, clipboard, profiling, header interactions, step deltas. Editing wired by 15 |
| 14 | Formula engine | **done** | 3/3 | Lexer, parser to IR, 87-function catalogue, formulas push down |
| 15 | Write-back | **done** | 3/3 | Change sets, identity, dry run, blast radius, batching, Table editor page |
| 16 | Tool library (→420) | **partial** | 3/6 | 167 tools + the registry, harness, API, docs and UI. Window/statistical/geo/enrichment families deliberately absent |
| 17 | SQL IDE & notebook | not started | 0/3 | Needs 12, 13 |
| 18 | Time travel | not started | 0/3 | Needs 08 |
| 19 | Semantic layer & contracts | not started | 0/3 | Needs 08, 18 |
| 20 | Streaming & CDC | not started | 0/4 | Needs 08, 10 |
| 21 | Collaboration | not started | 0/3 | Needs 13 |
| 22 | Optimizer | not started | 0/4 | Needs 12, 18 |
| 23 | Extensibility | not started | 0/3 | Needs most |

### Recommended next action

**Phase 11 (ingestion intelligence)** or **Phase 17 (SQL IDE)**, or more tool
categories on the Phase 16 registry.

The thesis track is finished: 08 (types + IR) → 09 (design) → 13 (grid) → 14 (formulas) →
12 (pushdown) → 15 (write-back) are all done, and 16 has shipped its machinery plus
167 tools. Together they are the whole argument — an analyst edits a live table in a
grid, reaches any of 167 tools from a right-click or Ctrl+K, and every edit is a
reviewed statement with lineage. What is left is breadth (10, 11, more tool
categories), depth (17–23), and two cutovers noted below: making the IR the only
executor, and wiring pushdown into extraction runs.

### Phase 08: what is done, and the one thing deliberately not done

The IR is built, proven, and wired in — but it does **not** yet replace the existing
executor. Both run, and `test_ir_from_steps.py` proves they agree on every step.
Likewise `service_lineage/from_ir.py` derives columns from the IR and
`test_matches_ir.py` proves it equals `columns.py`, which in turn is proven against a
real pandas run.

**Cutting over to IR-only is a deliberate separate decision**, not an oversight. The
roadmap itself called for running both until identical; they now are. Whoever makes the
cutover should delete `columns.py`'s per-step table and route `apply_transformation_steps`
through `ir.pandas_backend.execute`.

Conventions worth knowing before touching the IR:

- **Join sides are positional** — see rule 6a above. This one silently produced a
  cartesian product.
- **Three-valued logic is real.** Comparisons return nullable `boolean` with NA where an
  operand is null; only `Filter` and `Case` collapse NA to false. `fillna(False)` before a
  `NOT` makes `NOT NULL` true, and pandas returned three rows where SQL returned one.
- **`SUM` of an all-null group is NULL, not 0.** pandas needs `min_count=1`.
- **A dialect that cannot express something raises `Unsupported`.** Never approximate;
  the planner keeps that node local instead.
- **`Extension` config is frozen** (lists become tuples) so the node stays hashable. Use
  `node.config_dict()` to read it back — `dict(node.config)` hands a step a tuple where it
  wants a list.
- **The IR must read the same config keys the engine reads.** `cast_column_types` uses
  `mappings`, not `casts`; aggregate names come from
  `steps.aggregate.SUPPORTED_AGGREGATIONS`. Guards in `test_ir_step_coverage.py` compare
  the two allowlists, which is how three missing aggregates were found.

### Phase 16 notes: the tool library

`services/service-transformations/tools/` is a **registry**, not a folder of
modules. Read `spec.py` first; everything else follows from the shape it
defines. Adding a tool means one declaration in a category module and a run of
`scripts/generate-tool-reference.py` -- nothing else.

- **One `tool` step type covers all 167.** Editing the step vocabulary, the
  validator, the lineage table and the UI catalogue for each new tool is how a
  library of hundreds stops being consistent. `compile_step` handles `tool`
  directly and asks the spec to build its own node.
- **A tool *is* IR.** `build(node, params) -> Node`. That is what gives every
  tool type inference, lineage and pushdown at no extra cost -- and why
  `columns.py` has no per-tool table: `_handle_tool` builds the node and reads
  its schema. Do not add a second description of what a tool does.
- **The tests are structural, not per-tool.** `test_tool_library.py` iterates
  the registry: empty, all-null and single-row for everything, plus the
  documented example executed, plus lineage-versus-engine. A tool that skips a
  case fails without anybody writing a test for it. If you add a tool and a test
  you have never seen before goes red, it is telling you something true.
- **The documented example is the documentation.**
  `docs/transformation-tools.md` is generated, and a test fails if the
  checked-in copy drifts. Do not edit it by hand.
- **Null in, null out -- and it is enforced, not intended.** Everything in
  `pandas_functions.py` goes through `_map`, which never calls the
  implementation for a missing value. Where an expression has a *total* answer --
  a `Case` with a default, a `coalesce` with a constant, an `if_error` fallback --
  wrap it in `null_safe`, or a row that had no input gets the default and "we do
  not know" quietly becomes "we know, and it is zero".
- **A setting has to be constant across rows**, and `_literal` checks it. The IR
  will happily let somebody pass a column where a pattern belongs; reading row
  zero and applying it everywhere looks entirely plausible in the output.
- **Local-only is the honest default.** 109 of the 186 IR functions declare no
  Postgres lowering. That is the Phase 08 rule, not neglect: SQL that means
  something *close to* the local implementation is worse than none, because the
  difference only shows as numbers that disagree depending on where it ran.

### Phase 15 notes: write-back

`services/service-writeback` is the only code in the platform that writes to a database the
platform does not own, so the whole module is built around making the destructive case
unreachable by accident. Read `identity.py` first — everything else depends on it.

- **Editing is refused when rows cannot be addressed.** Preference order is primary key →
  NOT-NULL unique constraint → a key the user designates (verified against live data before
  it is accepted) → a physical identifier (`ctid`/`rowid`, offered with its caveat, never a
  default) → refusal. There is no "match on all columns" fallback; it silently updates every
  duplicate.
- **A rehearsal must leave nothing behind, and once it did not.** SQLite has transactional
  DDL but pysqlite only opens an implicit transaction for DML, so an `ALTER TABLE` in a dry
  run committed itself, survived the rollback, and made the real commit fail with "duplicate
  column name". SQLite is now in `NON_TRANSACTIONAL_DDL` beside MySQL. If you add a dialect,
  check this before trusting the rollback.
- **Validation is change-set-wide, not per edit.** `validate_all` checks structure changes
  against the table as it accumulates and row edits against the table as it will be. Without
  it, "add a column then type into it" — the commonest gesture in the Studio — is impossible.
- **Concurrency compares values per cell, not hashes per row.** A hash matching Python's is
  not portable across dialects, and getting it subtly wrong disables the check silently. A
  concurrent change to a different column of the same row is not a conflict, by design.
- **`previous` and "no previous" are different claims.** `Edit.previous` uses an
  `_UNRECORDED` sentinel so an explicit `None` still gets checked. Gating the check on
  `version` while comparing `previous` meant setting one without the other turned it off.
- **No-op edits are dropped at compile time.** Also a MySQL trap: it reports rows *changed*,
  not matched, so writing a value that is already there returns zero and reads as a conflict.
- **Updates batch by shape.** Rows setting the same columns and checking the same columns
  share one statement with many parameter sets. `export_as_migration` writes one statement
  per set — a bind marker left in a migration file is not a migration.
- **`GET .../rows` is not the extraction preview.** A preview is a sample with no defined
  order; an editing surface needs the row under the cursor to still be there on the next
  page, so these reads order by the identity key and use it to break ties on any sort.
- **In a governed project only `POST .../commit` is refused.** Staging is the proposal.

### Phase 14 notes: formulas

`formula/lexer.py` and `formula/parser.py` turn spreadsheet syntax into an **IR expression**,
not a private AST. That is the whole design: a formula then gets type inference, lineage and
pushdown for free — `=UPPER([name])` compiles to a `Project` and runs at the source.

- **Two languages, never guessed between.** `derive_column` accepts `expression` (the
  original Python-ish syntax, which every saved pipeline uses) or `formula` (spreadsheet
  syntax). Supplying both is refused: they are different languages and picking one would
  eventually compute something other than what was written.
- **Excel's precedence, not Python's.** `-3^2` is 9, `&` is concatenation and binds tighter
  than comparison, `=` means equality. Pinned in `test_formula_parser.py`.
- **`to_text` and `to_number` deliberately have no SQL lowering.** `CAST(1.0 AS TEXT)` is
  "1.0" in Postgres where the local path renders "1", and a failed cast raises in SQL where
  the local path yields null. Pushing them would make the answer depend on where it ran.
- **Arithmetic typing is not widening.** `widen` looks for a type holding both values
  exactly and correctly refuses decimal-and-float; multiplying them is well defined and
  yields a float. Conflating the two typed real formulas as `unknown`.
- **A bad row is counted, not fatal.** The count is reported against the rows that *had*
  values, not against every row — "the other 1 were fine" was wrong when that row's input
  was empty to begin with.

### Phase 12 notes: pushdown

`ir/surfaces.py` declares what each source can run, `ir/planner.py` splits a tree, and
`ir/run_plan.py` executes the split. `test_pushdown_planner.py` proves a planned execution
equals a local one for every tree in the corpus — that is the gate, because pushdown
rewrites the user's computation.

- **An unknown source is local-only.** Nothing is assumed to push down; a connector absent
  from `_SURFACES` gets `LOCAL_ONLY`, which is always safe.
- **Nothing above a local step can be pushed.** Its input no longer exists at the source.
- **Every local node records WHY.** The most useful thing an optimiser reports is what
  stopped it, and the Studio panel shows exactly that.
- **The plan is currently advisory.** The preview computes it from the IR and the panel says
  "*would* run in postgres" — it describes the RUN, not the preview, which always reads the
  materialised file. Wiring `execute_plan` into real extraction runs is the next step and is
  where the actual speed-up lands.
- **`_describe_plan` accepts steps as dicts *and* objects.** The request body delivers dicts;
  the unit-test mock was an object, so `step.step_type` passed in tests and raised in the
  browser.

### Phase 13 notes: the grid

`features/studio/grid/` — geometry, selection, clipboard and theme are **pure and tested**
(159 tests, no DOM); `data-grid.tsx` is the only part that renders. Keep it that way: the
maths is where the bugs are, and it is far cheaper to test without a canvas.

- **Use a callback ref, not `useRef`, for the scroll container.** The grid renders an
  empty-state branch until the preview arrives, so the element does not exist on first
  paint. With `useRef` plus `[]`-dependency effects, the measurement and the palette read
  ran once against `null` and never again — the canvas kept its default 300×150 and drew
  nothing, while the status bar happily reported "3 rows".
- **The canvas reads design tokens via `getComputedStyle`**, because it cannot use CSS
  classes. If a token fails to resolve the grid refuses to draw rather than falling back to
  a hardcoded palette — a plausible light grid on a dark page looks like a choice, not a bug.
- **Numbers are not thousands-grouped.** An `order_id` of 1001 must not read as "1,001",
  and identifiers are the commonest integer column. Excel does not group by default either.
- **Profiling is capped at `PROFILE_SAMPLE` (1,000) rows.** Profiling every column over the
  whole dataset is O(rows x columns) *per render* — at a million rows and 20 columns that is
  twenty million reads. `ColumnProfile.complete` records whether the sample was everything,
  so the popover says "first 1,000 rows" rather than implying it saw them all.
- **A header sort is a STEP, not a view operation.** The grid holds a page, so sorting what is
  loaded would order a sample and present it as the order of the table. The Studio replaces
  the existing `sort_rows` step rather than stacking another, or the arrow and the pipeline
  tell different stories.
- **Never discard the last good preview on error.** A step is added *before* it is configured,
  so the first request after every "add step" fails. Throwing the preview away made the data
  vanish at exactly the moment somebody needed to see it to configure the step. The grid stays
  and is marked stale.
- **Editing is deliberately not wired.** `onEditCell` exists and `pasteWrites` is tested, but
  the Studio does not pass it: changing one cell needs row identity to say *which* row changed,
  and that is Phase 15's write-back. Wiring it to a step that rewrites every matching value
  would surprise people badly.
- **Join sides, three-valued logic and the other IR conventions** are in the Phase 08
  section above and still apply.

### Phase 09 notes for whoever touches the UI next

- **Never write a colour literal.** `apps/web/src/lib/theme/no-raw-colours.test.ts` scans
  `apps/web/src` **and** `packages/shared-ui/src` and fails on Tailwind palette utilities,
  white/black alpha, hex literals, and colours hidden inside arbitrary values
  (`shadow-[...rgba(...)]`). Use the semantic tokens: `text-ink/ink-2/ink-3/muted/faint`,
  `bg-canvas/surface/surface-2/sunken`, `border-line/line-strong`, `text-danger/success/warning/info`,
  `bg-*-soft`, `border-*-line`, and `text-*-ink` for text sitting **on** a filled background.
- **Three theme states, not two.** "system" *removes* `data-theme` — that is the mechanism, not
  an oversight. Setting `data-theme="system"` would match no rule.
- **`packages/shared-ui` is easy to forget.** The original migration missed it and the app
  rendered with near-black borders in light mode; only a screenshot caught it.
- **Density is real, not decorative.** `cell-pad` (a Tailwind `@utility`) consumes
  `--density-cell-*`, and 112 table cells use it. Tailwind padding utilities are classes, so a
  `:where(td, th)` rule would lose to them — that is why a utility was needed.
- **Chart series** come from `--series-1..8` (Okabe-Ito). Hue alone is trustworthy to **5 series
  in light, 6 in dark**; past that a chart needs a dash pattern or marker shape. `series.test.ts`
  enforces this with a real dichromat simulation.

---

## 9. How to work on this project

The user's standing instruction, given repeatedly:

> "Continue remaining all the phases. After each test is complete run all the tests, then check
> if anything is missing or any modifications to be done to improve it, and then proceed to the
> next phase. Do this till the whole project is completed end to end."

So, per phase:

1. Build it.
2. Run `npm run verify` — **all** of it, not just the touched package.
3. Write an end-to-end script against the **real running API** (see `scratchpad/e2e_*.sh` for
   the pattern) and actually run it. Every phase so far found bugs this way that unit tests
   missed — the tenancy leak, the empty column picker, the missing node type.
4. Fix what you find. Look for what is missing or could be improved, not just what is broken.
5. Update this file's ledger and session log.
6. Move to the next phase.

Report honestly. If something is unverified, say so and add it to §7.

---

## 10. Session log

| Date | Session | What happened |
|---|---|---|
| 2026-08-20 | `5754fbb2` | Fixed ~15 setup bugs in the cloned repo; added extraction, quality, drift services; expanded transformations 10→20 steps |
| 2026-08-21 | `5754fbb2` | Phases 01–07 built and verified end to end. 254→1,256 Python tests, 111 web tests, 22 services, migrations 0014–0025. Roadmap v2 written (`roadmap-v2.md`, `HANDOFF.md`) |
| 2026-08-21 | `5754fbb2` | **Phase 09 done.** Three-state theming, graphite/teal/copper palette, ~2,860 colour usages migrated to tokens, density wired to table cells, per-user preferences (migration 0026). 1,270 Python / 287 web tests |

| 2026-08-22 | `5754fbb2` | Phase 09 bug sweep: theme toggle was in a dead component (moved to top bar), avatar ink on brand gradient, `--faint` misused as a text colour in 67 places, `--accent-muted` failed AA in light, and a missing stored file returned 400 instead of 404 |

| 2026-08-22 | `5754fbb2` | **Phase 08 part 1**: canonical type lattice (`shared_python/types/`), coercion with lossy-cast reporting, mappings for postgres/mysql/sqlite/pandas, value-based inference bridged to the legacy vocabulary. 1,270 -> 1,482 Python tests |

| 2026-08-22 | `5754fbb2` | **Phase 08 part 2**: relational IR (expressions, 11-node algebra), pandas and SQL backends, 22-case differential test. Caught 3 real bugs incl. a join condition compiling to a cartesian product. 1,482 -> 1,504 Python tests |

| 2026-08-22 | `5754fbb2` | **Phase 08 complete.** 20 steps compile to IR, lineage derives from IR, 90% coverage on the new code. Found 8 real bugs incl. three-valued logic, SUM-of-nulls, a cartesian-product join, and three aggregates missing from the IR. 1,504 -> 1,794 Python tests |

| 2026-08-22 | `5754fbb2` | **Phase 13 part 1**: canvas data grid replacing the DOM table — two-axis virtualisation, Excel keybindings, Excel-compatible clipboard, in-cell editing, column resize. 288 -> 447 web tests |

| 2026-08-22 | `5754fbb2` | **Phase 13 complete.** Column profiling with quality bars, header sort/autofit/freeze/reorder, per-step row deltas from the existing pass. Found 4 bugs incl. profiling reading a million rows per render and the grid vanishing whenever a step was incomplete. 447 -> 507 web tests |

| 2026-08-22 | `5754fbb2` | **Phase 12 complete.** Execution surfaces, pushdown planner, plan executor, Studio plan panel. Also fixed a React pooled-event bug that unmounted the grid mid-scroll on wide tables. 1,800 -> 1,827 Python tests |

| 2026-08-23 | `5754fbb2` | **Phase 16 partial (machinery complete).** Tool registry, 167 tools across 10 categories, IR catalogue 87 -> 186 functions, universal test harness, catalogue + preview API, generated reference, tool browser with live preview, type-aware column context menu, palette synonyms. Fixed `abs`/`round` raising on all-null columns, `to_date` failing a run on one bad value, mixed date formats silently losing rows, and `starts_with`/`contains` having no lowering at all. 2,113 -> 4,392 Python, 544 -> 573 web tests |
| 2026-08-22 | `5754fbb2` | **Phase 15 complete.** `service-writeback` (identity, change sets, compiler, dry run, blast radius, batching), 11 routes, migration 0027, Table editor page. Fixed a dry run that left DDL behind on SQLite, per-edit validation that blocked add-then-fill, and a blast-radius share rule that fired on a 3-row table. 1,993 -> 2,113 Python, 510 -> 544 web tests |
| 2026-08-22 | `5754fbb2` | **Phase 14 complete.** Formula lexer/parser producing IR, catalogue 40 -> 87 functions, formulas push down. Fixed a planner crash on a bare local scan and arithmetic typing that returned `unknown` for decimal x float. 1,827 -> 1,993 Python tests |

<!-- Add a row above when you finish a session. Keep it to one line. -->
