# HANDOFF — read this first

**Purpose:** this file lets a brand-new session (with zero context) pick up exactly where the
last one stopped. Keep it current. If you change project state, update the **Progress ledger**
and **Session log** at the bottom before you finish.

**Last updated:** 2026-10-15 (roadmap Phase 20 complete as D1, live data)
**Updated by:** session `75332b59` (adoption-readiness A0–A9, then C1 contracts, C2 working together and D1 live data)

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

### How development works

Directly in the repository: read the context, plan briefly, implement, run the
verification gate, review the diff, update this handoff. The development rules
and invariants live in [`CONTRIBUTING.md`](../CONTRIBUTING.md). There is no
development orchestrator — the `pw-dev` orchestrator that briefly ran phases
through planner/worker/reviewer roles was removed on 2026-09-22 (see the
session log).

### The verification gate — run this after every change

```bash
npm run verify     # ruff + pytest + ESLint + tsc + production build
```

Everything must be green before moving on. Current baseline (2026-10-15, after D1): **6,684 Python tests
passed (667 skipped), 854 web tests, all passing, zero warnings.** The
skips include the real-server delivery and copy tests; see §6 for running
them.

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
| 04 | Reach | `service-connectors` | Connector SDK + conformance suite, 19 connectors (**211** after Phase 10) |
| 05 | Consumption | `service-reporting` | Charts, dashboards, pivots, Excel export, catalog |
| 06 | Intelligence | `service-intelligence` | PII, join keys, entity resolution — **no model calls** |
| 07 | Enterprise | `service-enterprise` | Tenancy, row/column security, retention, SSO, `/metrics` |

**Migrations:** `apps/api-gateway/alembic/versions/`, 62 files, head is `0062_live_data`.

### Roadmap v2: in progress

See [`roadmap-v2.md`](./roadmap-v2.md) — 16 phases across 4 tracks, ≈58 sessions.
Phases **08, 09, 10, 11, 12, 13, 14, 15, 17, 18** and, since 2026-10-15,
**19 and 21** (as C1 and C2 in `docs/plans/contracts-and-collaboration.md`)
and **20** (as D1 in `docs/plans/live-data-and-performance.md`) are done,
**16** shipped its machinery plus 173 tools, **22** shipped a first slice as
production-readiness P9; **23** has not started. The progress ledger in §8
tracks the rest.

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

- **Never `Base.metadata.create_all` against PostgreSQL in a test process.** On a dialect with
  ALTER it marks the foreign keys in reference cycles (datasets, runs, recipes) to be added
  afterwards, on the shared metadata, and every SQLite test after it loses those constraints and
  their ON DELETE CASCADE. CI failed on "deleting a project leaves its datasets" for exactly this
  (C1). Create PostgreSQL tables from a private copy: `table.to_metadata(MetaData())` for each
  table, then `create_all` on the copy (`test_data_contracts._create_tables`).
- **pytest uses `--import-mode=importlib` with no `__init__.py` files.** Two `conftest.py`
  files with the same basename collide and one silently supplies the other's fixtures. Fixtures
  are inlined per module. Do not add a shared `conftest.py` without checking for collisions.
- **Live feeds' round trips need their servers** (D1): `docker compose -f docker-compose.live.yml up -d`,
  `scripts/check-live-servers.py --wait 180`, then run with `LIVE_TEST_SERVERS=1` (and
  `OUTBOUND_ALLOW_LOOPBACK=true` for the queue tests). Without it they skip; the `live` CI job
  sets it. `services/service-extraction/tests/conftest.py` puts the tests folder on the path so
  `live_servers.py` imports under `--import-mode=importlib`. SQL Server runs under Rosetta on Apple
  silicon; its capture job copies changes every few seconds, so its test waits.
- **`curl -F "file=@x.csv"` sends `application/octet-stream`** and the upload endpoint rejects
  it. Use `-F "file=@x.csv;type=text/csv"`.
- **`created_at` defaults to `now()`, which in Postgres is the *transaction* time.** Every row
  written in one request ties. Order by an explicit `sequence` column instead.
- **`HTTPServer.server_bind` calls `socket.getfqdn()`** which blocks ~35s per fixture on macOS.
  The REST connector tests subclass it. Reuse that pattern for any new loopback server.
- **Falsy-zero bugs.** `if tile.position` treated position 0 as unset. Prefer `is not None`.
- **`npm run dev` refuses to start if Postgres is unreachable** — that error is accurate, start
  Docker.
- **The real-server connector tests skip quietly without their servers.** Start
  `docker compose -f docker-compose.connectors.yml up -d` and export
  `CONNECTORS_TEST_POSTGRES_URL`, `CONNECTORS_TEST_MYSQL_URL` and, for S3,
  `DELIVERY_TEST_S3_ENDPOINT` / `_BUCKET` / `_KEY` / `_SECRET` (the compose
  file's header lists the values) to run delivery, copy and S3 tests for real.
- **A connector that fetches URLs refuses 127.0.0.1 by default.** Set
  `OUTBOUND_ALLOW_LOOPBACK=true` for a local API in development; the connector
  tests' `conftest.py` sets it for their loopback servers.
- **Sourcing `.env` in a shell breaks `BACKEND_CORS_ORIGINS`**: the quotes
  inside its JSON list are stripped, and pydantic then fails to parse it.
  Export it again as JSON after sourcing (the CLI scripts read `.env` through
  pydantic directly and are fine).
- **In zsh, `path` is `PATH`.** A loop variable called `path` empties the
  shell's search path for the rest of the command.
- **A test that overrides `get_db` also moves the audit log** (A6): the audit
  middleware writes through the same override, so tests no longer write
  their requests into the configured database.
- **The API answers 422 for a malformed id in a path**; the web app's
  `parseApiResponse` turns that into 404, so pages show "not found".
- **SQLite's clock has one-second resolution; PostgreSQL's has
  microseconds.** A comparison of two timestamps written in the same second
  passes on SQLite and fails on PostgreSQL (A7: picking a run up was refused
  for every run live while its test passed). Compare something other than
  `updated_at`, or test against PostgreSQL.
- **The dev stack does not reload.** After a migration run `alembic upgrade
  head` from `apps/api-gateway` (with `.env` sourced and
  `BACKEND_CORS_ORIGINS` re-exported); after a code change restart the
  gateway and `scripts/worker.sh`, and check with `pgrep -f workflow_worker`
  that the old worker processes are gone (stopping the shell can leave them
  running old code).
- **A page in a background browser tab never finishes streaming**: React
  reveals streamed content on the next animation frame, which a hidden tab
  never gets, so a crawler there sees fallbacks and extra headings. Walk
  pages with Playwright (headless counts as visible).
- **CI installs the newest versions the ranges allow** (SQLAlchemy 2.1.4
  there, 2.0 here). A library that supports a narrower range than ours can
  silently do nothing in CI and production; read CI's captured logs.
- **Docker Hub refuses anonymous pulls of `minio/minio`** in CI; the job uses
  `cgr.dev/chainguard/minio` with `server /data`.
- **`next build` type-checks with `tsconfig.typecheck.json`**, not
  `tsconfig.json`; `npx tsc --noEmit -p tsconfig.typecheck.json` is the same
  check.

---

## 7. Known gaps — stated, not hidden

These are deliberate and documented, not oversights. Do not quietly "fix" them by relaxing the
honesty; if you verify one, update its status here.

| Gap | Why |
|---|---|
| 161 of 211 connectors are tier 4 ("Not yet tested") | Written from vendor documentation and never executed here. Since A6 they sit under "Available on request" in the catalogue; each still says so on its card, in the config form, in the connection test and in the run's warnings — the design, not a gap to close by relaxing the claim |
| Tier 3 ("Recorded") is empty | It means replaying a *captured real session*, and there are no credentials on this machine for any of these vendors. Fabricating a recording would be the exact failure the tier system prevents |
| 5 SaaS connectors never run live | Stripe/HubSpot/Shopify/Salesforce/Sheets — no credentials on this machine |
| OIDC not run against Okta or Entra ID | No tenant here. The flow runs against a live Keycloak 26 in CI on every change (A8: `scripts/sso-test-provider.py`, `e2e/sso.spec.ts`); `scripts/check-oidc.py` checks a deployment's own provider |
| SAML absent | Needs `xmlsec`; a SAML that skips signature checking is an auth bypass |
| 5 warehouse connectors driver-gated | Snowflake/BigQuery/Redshift/SQL Server/Oracle declare `test` only |
| Email and Slack delivery unverified against a real server | Report delivery, emailed invitations and reset codes are implemented and tested with captured senders; this machine has no SMTP server or reachable webhook, so live runs record the stated failure per channel — set `EXTERNAL_NOTIFICATION_SMTP_*` and a real webhook to exercise them |
| Write-back run only against SQLite | PostgreSQL and MySQL paths are written and dialect-aware; no server on this machine to run them |
| Write-back does not cover files or SaaS | A file-backed dataset is a replayable recipe in the Studio, which is a better answer than a destructive rewrite. Write-back exists for live tables the platform does not own |
| No three-way conflict resolution UI | A stale row stops the commit and names the statement; choosing "theirs" or "yours" per row is its own screen |
| Python notebook cells are disabled on macOS | The sandbox probe finds `setrlimit(RLIMIT_AS)` rejected, so a cell could allocate until the host runs out of memory. Disabling with a stated reason is the designed behaviour; on Linux the probe passes and cells run |
| Python notebook cells: fixed on Linux (A7) | The cell process imports pandas and the gateway's packages before limiting itself, which on Linux is already past 512MB of address space; the absolute `RLIMIT_AS` left nothing, so the result channel's thread could not start and every cell timed out (32 CI failures). The limit is now the interpreter's address space plus 512MB, the channel opens before limits apply, and numpy's maths libraries are held to one thread. `test_sandbox.py` passes in a `python:3.11-slim` container |
| Notebooks run in the request, not on the worker | Bounded instead: 15s per Python cell, a SQL statement timeout, 120s for the whole notebook. A queue would add a job table, a worker node type and client polling for the same result |
| PDF table extraction absent | Needs camelot or pdfplumber, neither installed. The format detector refuses `.pdf` by name with that sentence rather than failing inside a parser |
| SPSS `.sav`, `.ods` and 7-Zip unreadable | Need `pyreadstat`, `odfpy` and `py7zr`. Each is declared and refused with the package to install. SAS and Stata, which pandas reads natively, work |
| Duplicate-row detection is skipped when streaming | It needs every row held at once. The streaming profile reports `null` rather than `0`, which would be a claim |
| Live feeds are micro-batch | D1: every feed is read every few seconds (1 at least) by `platform-live-runner`, never held open. The roadmap's "continuous execution only where the latency requirement justifies it" was not built: no requirement here asked for less than a second |
| Some live feeds save an event at least once | MQTT gives no message an id, and RabbitMQ messages and webhook posts carry one only if the sender adds it, so a redelivery after a crash between saving and acknowledging can be saved twice. Each such kind says so where it is chosen and on its page (`guarantee: at_least_once`) |
| Cloud queues are tested against the vendors' test servers | Kinesis against a Kinesis test server (kinesis-mock), Pub/Sub against Google's emulator, Event Hubs against Microsoft's emulator, every change in the `live` CI job: tier 2, which says "a real server or a test server that answers the way the vendor documents". No AWS, Google or Azure account is used |
| Live feeds stay out of bundles | A bundle carries no credentials; a live feed holds the credentials of what it reads, as a connection does, so feeds and their live recipes are not moved with a project's work |
| A live recipe's output keeps 30 days of windows | `live_recipes.KEEP_WINDOWS`: older final windows leave the output dataset at its next save and stay in its earlier versions, so a save never grows with every window there ever was |
| SQL Server change capture is switched on by the database's owner | Pipewright never changes a database's settings; `sqlserver_cdc`'s test names the `sys.sp_cdc_enable_db` / `sp_cdc_enable_table` statements to run. MySQL's binlog settings and PostgreSQL's `wal_level` are reported the same way |
| gRPC absent | Needs `grpcio` and a reflection-based dynamic client |
| Lineage is still derived from `columns.py`, not the IR | P9 made the IR the only *executor*; `service_lineage/from_ir.py` derives schemas, not edges, so cutting lineage over means writing edge derivation first. `test_matches_ir.py` still proves the two agree |
| Contracts are per dataset, here | C1: a contract is about one dataset in this deployment. Nothing publishes it to another deployment or holds it at the source, and a downstream recipe is listed as relying on a dataset rather than notified itself (its owner can follow). Erasing a person's data is never stopped by a contract, by design; a promise it breaks is recorded |
| Optimizer has rewrites, not statistics | `ir/rewrites.py` applies five provable identities before the planner splits a tree. No row/distinct counts are collected, so no join reordering, no cost model, no caching or federation (Phase 22) |
| 9 engines are declared but undriveable | Cassandra, ScyllaDB, Couchbase, Redis, ArangoDB, HBase, Aerospike, Timestream, HDFS. Each declares only `test`, reports `available: false`, and names the interface this platform *can* read instead |
| Old duplicate datasets are not merged | Since A4 an import's runs and a recipe's runs add versions to one dataset (`reusable_dataset`, `TransformationPipeline.output_dataset_id`). Datasets created one-per-run before that stay separate records; merging them would rewrite version history, so the Datasets list still folds same-named records into one row ("12 loads") |
| The v1 source registry is hidden, not removed | `service-sources` (`/api/v1/projects/{id}/sources`, the "Register source" records) is no longer shown anywhere in the web app since A1; its API and tables stay for compatibility. A4 did not retire it: nothing reads it, and deleting the tables needs a decision about existing rows |
| Column names appear in lineage and recipe definitions | Policies (A6) hold on every path that hands rows or values to a person; lineage and recipes describe the data's shape, so a denied column's name still appears there |
| No warehouse destinations | Datasets deliver to PostgreSQL, MySQL, S3 (or a compatible store) and a server folder. Snowflake, BigQuery and Redshift are not destinations until a customer names one |
| Checks and charts compute in the request | Bounded: charts, the Assistant's analyses and policy previews refuse a dataset over 500,000 rows before reading it; checks read any size. All read a columnar copy rather than the file (A8: checks on 4M rows 22s to 1s). A check in a workflow runs on the worker. Only uploads over 25MB, deliveries over 50,000 rows and database copies are handed to the worker |
| Embedding sites are listed per deployment, not per embed | `EMBED_ALLOWED_ORIGINS` is the web's one list; an embed cannot narrow it to one partner's site. Signed links, expiry, per-link filters and turning an embed off are per embed |
| Activity goes back 2,000 items | `api_gateway/activity.py` pages by position up to `MAX_OFFSET`; the audit log and runs pages hold everything |
| Page bodies are written in English in the code | Y7 moved the shell and navigation (266 strings) into `messages/en.json` and every date and number into `lib/format.ts`; the rest of each page's words are inline, so a second language needs them moved first. English is the one language shipped |
| Okta and Entra ID untested | No tenant; Keycloak is tested in CI on every change |
| Cold-user sessions not run | A9 asks for five people outside the team; `docs/cold-user-sessions.md` is the protocol and its files are in `docs/cold-user-files/`. Only the owner can arrange the people |
| 1.0.0 not tagged or published | Tagging `v1.0.0` publishes images to GHCR (`release-images.yml`, both `v1.0.0` and `1.0.0`) and can publish the docs site (`docs-site.yml`, after Pages is set to GitHub Actions). Public acts, so they wait for the owner's word |
| Temporal SQL runs in SQLite over a copy | `AS OF` queries load the version's artifact into an in-memory SQLite table named `dataset`; the dialect is SQLite's, not the source's, and results are capped at 1,000 rows. Customer SQL sent to customer databases is never rewritten (settled decision #8) |
| No pagination on version history or diff samples | Listings return every version; diff samples are capped at a declared 20 while counts stay exact. A dataset with thousands of versions would want cursors, which do not exist yet |
| `today()` is the UTC date of the frozen instant | Before P7 it was the host's local date. Recorded in the run's execution context (`timezone: UTC`); a deliberate semantic change, stated rather than hidden |
| Tool library is 167, not the roadmap's 420 | Window, statistical/ML, geospatial, fuzzy-matching, enrichment and recipe-management families are absent by name in `roadmap-v2.md`. Each needs something the IR does not have yet (a window node, a geometry type, a network policy) rather than more declarations |

---

## 8. Progress ledger — roadmap v2

**Update this table when you finish a phase.** Status: `not started` / `in progress` / `done`.

| # | Phase | Status | Sessions | Notes |
|---|---|---|---|---|
| 08 | Type system & IR | **done** | 4/4 | Types, IR, 2 backends, 20 steps. **IR is the only executor since P9** (`executor.py` compiles every step to IR; unmodelled steps are Extension nodes). Lineage still from `columns.py` — see below |
| 09 | Design system & themes | **done** | 2/2 | Graphite/teal/copper; light+dark+system; density |
| 10 | Connector factory (→250) | **done** | 6/6 | 211 connectors, 4 generators, 50 at tier 2, schema watch + incidents, secret references |
| 11 | Ingestion intelligence | **done** | 3/3 | Sniffing pipeline with evidence, 10 readers, ingest specs, resumable upload, streaming profile, 6 nested tools |
| 12 | Pushdown & dialects | **done** | 4/4 | Surfaces, planner, plan executor, plan panel. **Wired into extraction runs in P9** (`service_extraction/shaping.py`: a job's steps run at the source as SQL where the dialect can, the rest here; grain-changing steps refused for incremental loads) |
| 13 | Data grid | **done** | 4/4 | Canvas grid, selection, clipboard, profiling, header interactions, step deltas. Editing wired by 15 |
| 14 | Formula engine | **done** | 3/3 | Lexer, parser to IR, 87-function catalogue, formulas push down |
| 15 | Write-back | **done** | 3/3 | Change sets, identity, dry run, blast radius, batching, Table editor page |
| 16 | Tool library (→420) | **partial** | 3/6 | 173 tools + the registry, harness, API, docs and UI. Window/statistical/geo/enrichment families deliberately absent |
| 17 | SQL IDE & notebook | **done** | 3/3 | Workbench, notebook, sandbox, recipe-as-code. Python cells disabled on macOS by design |
| 18 | Time travel | **done** | 3/3 | Immutable versions (0038–0040), temporal reads, `AS OF` SQL, diff, rollback, deterministic replay with recorded execution context, erasure reconciled, pin + two-step prune protocol, viewer/editor matrix, scripted live acceptance. Delivered as production-readiness P7 — see `docs/plans/phase-18-decisions.md` |
| 19 | Semantic layer & contracts | **done** | 3/3 | Metrics defined once on the IR (`service_reporting/metrics.py`, migration 0044), resolved everywhere. **Data contracts (C1, 2026-10-15)**: `service_quality/data_contracts.py`, migration 0060; promises per column and per dataset, enforced before storing by recipe runs, imports and stream saves, refused on rollback, recorded on erasure; problems once per source, overdue from the freshness promise, followers, what relies on it |
| 20 | Streaming & CDC | **done** | 4/4 | P9's webhooks and PostgreSQL CDC, then **D1 (2026-10-15)**: `service_extraction/live/` (PostgreSQL, MySQL binlog, MongoDB change streams, SQL Server CDC; Kafka, Event Hubs, Kinesis, Pub/Sub, Pulsar, RabbitMQ, NATS, MQTT), tables kept current by key after a first copy, positions committed with events, guarantees stated per kind, live recipes with four window kinds, watermarks, lateness and exactly-once state (`live/windows.py`, `live_recipes.py`), `platform-live-runner`, migration 0062, a `live` CI job against every server |
| 21 | Collaboration | **done** | 3/3 | Comments with @mentions (P8). **C2 (2026-10-15)**: recipes co-edited in a shared copy merged by a CRDT (`service_transformations/coedit.py` + `studio/coedit.ts`, shared fixtures, selective per-person undo), revisions refusing stale saves, presence with step focus, suggestions any viewer can make and editors accept step by step, threads with replies on dataset cells, a per-dataset change feed (migration 0061) |
| 22 | Optimizer | **partial** | 1/4 | `ir/rewrites.py`: predicate/limit pushdown through row-wise nodes, filter and limit merging, proven by a four-way differential test and reported in every plan. No statistics, cost model, caching or federation |
| 23 | Extensibility | not started | 0/3 | Needs most |

**Business documentation (2026-09-23):** [Business requirements](business-requirements.md)
and its [40-page PDF](../output/pdf/Pipewright_Business_Requirements_Document.pdf)
consolidate use cases, target users, current requirements and the documented backlog.
The BRD is a business review draft at commit `79eb302`, including the first three P2
increments without declaring P2 complete; later development is outside that snapshot.

### Recommended next action

**The current plan is `docs/plans/live-data-and-performance.md`**: D1
(roadmap Phase 20, live data) is done as of 2026-10-15; D2 (Phase 22,
statistics, a cost model, queries across sources, caching, incremental runs
and resource limits) is next. Before it, `docs/plans/contracts-and-collaboration.md`
finished C1 (Phase 19's data contracts) and C2 (Phase 21, working together).
Phase 23 (extensibility) still needs its own measured plan. Rules for
anyone touching live feeds:

- **A live feed kind is one class in `service_extraction/live/`** with the
  surface `live/base.py` describes (declare settings and a guarantee, test,
  read a batch from a saved position, and for change capture take a
  position, read a table whole and name its key). Register it in
  `live/__init__.py` and give it a round trip in `test_live_queues.py` or
  `test_live_change_capture.py` against a server in `docker-compose.live.yml`;
  its tier 2 rests on the `live` CI job, which `scripts/check-live-servers.py`
  fails rather than letting a test skip.
- **A batch's position is committed with its events** (`streams.read_source`),
  and acknowledgements happen only after the commit (`Batch.finish`). Never
  acknowledge first. A kind that cannot recognise a redelivery says
  `at_least_once`, honestly.
- **A live recipe commits its window state, results and `processed_seq`
  together** (`live_recipes.process_recipe`); the window engine
  (`live/windows.py`) is pure and checked against a brute-force reference.
- Feeds and their followed tables are separate rows with no ORM
  relationship: flush the feed before adding its tables (PostgreSQL refuses
  otherwise; SQLite does not enforce foreign keys, so test on both).

Rules for anyone touching where data lands, or the Studio:

- **Every producer of a dataset version checks its contract before storing
  anything** (`service_quality.data_contracts.check_new_data`, called from
  recipe runs, imports, live feed saves (`streams.publish_frame`), rollback
  and both erasures) and hands
  the verdict to the version seam (`contract_verdict=` on
  `apply_dataset_materialization_success` and its wrappers), which records
  the outcome in the version's transaction. A new producer must do both; an
  upload or a quarantine makes a new dataset, which has no contract yet.
- A contract's freshness is the dataset's one `FreshnessPolicy`; never add a
  second clock.
- **The Studio edits a saved recipe through `use-recipe-editing.ts`**, whose
  merge rules (`coedit.ts`) must stay in step with
  `service_transformations/coedit.py`: change one, change both, and add the
  case to `coedit-fixtures.json`, which both test suites read. Compare step
  settings with `stableJson`, never `JSON.stringify` (key order differs).
- Anything that changes a recipe outside the Studio calls
  `coedit.record_save` (or the recipe restorer), so its revision moves on and
  the shared copy starts again with a reason.

**Before that, the sequence was `docs/plans/adoption-readiness-workflow.md`
(A0–A9)**, written from the 2026-09-23 adoption review. **A0 (product
definition, vocabulary, navigation tree, templates, voice guide, plus the
quick-win defect fixes) and A1 (navigation and shell) are done as of
2026-10-13, and A2 (golden path and onboarding) and A3 (Studio redesign) as
of 2026-10-14, as are A4 (sources, destinations and migration) and A5 (copy,
design system and consistency), A6 (trust, help and support for
buyers), A7 (scale and reliability) and, as of 2026-10-15, A8 (adoption
pack) and A9 (launch gate, everything but the owner's own steps: tagging
1.0.0, publishing the docs site and running the cold-user sessions).** Each phase's section in the plan lists what shipped, the
measured cold-user task results and what moved to later phases. Rules for anyone touching the web app now:

- **`apps/web/src/lib/navigation.ts` is the navigation.** A new page goes into
  an area's tabs (or an `also` pattern for something inside a tab) or into
  `STANDALONE_PAGES`; `navigation.test.ts` fails otherwise. Do not add rail
  items, menus or page-level "Back to …" links.
- **Use the A0 vocabulary** (spec S2): recipe not pipeline, check not rule,
  import not extraction job, schema change not drift, deliver not publish, in
  sentence case. `/extraction` and `/data-quality` redirect to `/sources` and
  `/checks` (`next.config.ts`).
- **`AppShell` is the list/detail template**: title, one-line purpose, at most
  three actions (use `ActionMenu` for the rest), content. `AppFrame` derives
  the tabs and breadcrumb from the URL; pass `title` on object pages.
- **Shared components are styled from `packages/shared-ui`** only because
  `globals.css` has an `@source` line for it; keep it.
- **On-screen words are tested** (A5; `docs/design-system.md` explains it all).
  `lib/language.test.ts` reads every on-screen string through the TypeScript
  parser and fails retired words (pipeline, tenant, snapshot, publish...),
  stored field names, HTTP paths, em-dashes, purpose lines over 15 words,
  descriptions or tour steps over 25, lowercase or Title Case labels and US
  spelling; its allowlist needs a reason per entry. `type-scale.test.ts` fails
  text under 12px, uppercase and tracked letters anywhere. `components.test.ts`
  fails a hand-built table, dialog, tab list or pill, or a local Button, Modal,
  Badge, Table, PageHeader, EmptyState, StatTile, Tabs or Toast: use
  `@platform/shared-ui`. `navigation.test.ts` fails a page with no browser-tab
  title or "About this page" help. On the server, `test_error_words.py` holds
  raised error messages to the same words, and `test_audit_words.py` needs
  every audited route to have a phrase in `service_governance/audit_words.py`;
  a new mutating route needs one.
- **Show stored codes through a label**, never raw: `lib/labels.ts`
  (`sentenceLabel`, `fileFormatLabel`, `triggerLabel`, `tierTone`, `typeLabel`),
  `lib/run-labels.ts` (`formatRunTypeLabel`, `formatStageLabel`), `StatusBadge`.
- **Run logs are read by people.** Messages passed to `_log_event` and audit
  or comparison notes are shown on the run page as written; write them in the
  product's words.
- **Notifications go through `create_user_notification`**, which applies the
  person's preference for the event's category. `category_for` in
  `preferences.py` files a new event type by its name and level (`_failed` or
  a warning is a failure, `_succeeded` a routine success, anything else a
  workflow message); check a new type lands where you mean.
- **There is one recipe editor: the Studio.** Link to a recipe with
  `recipeHref(projectId, recipeId)` (`/studio?recipe=`); the old
  `/pipelines/{id}`, `/datasets/{d}/pipelines/{id}` and `/pipelines/new`
  addresses only redirect. A new built-in step goes in `step-catalog.ts`
  (label, keywords, `optionLabels` for coded options; `step-catalog.test.ts`
  checks) and gets a summary in `step-summary.ts`. Nothing under 12px in
  `features/studio` (`type-floor.test.ts`).
- **Sessions renew while in use.** `POST /auth/session/renew`
  (`service_auth/session.py`) up to `AUTH_SESSION_MAX_HOURS` (default 12)
  after sign-in; the web app renews in its last 15 minutes
  (`lib/auth/renewal.ts`). A 401 on a request that carried a session sends
  the person to `/login?expired=1&next=…` (`lib/auth/session-end.ts`), and
  `proxy.ts` does the same for a run-out cookie. Only same-site `next`
  paths are followed (`safeNextPath`).
- **A producer keeps one dataset.** An import reuses `job.target_dataset_id`
  and a recipe `output_dataset_id` through `reusable_dataset`; each run adds a
  version. Replays still make their own dataset. Do not create a dataset per
  run again.
- **Imports go through `service_extraction/connector_sources.py` for every
  connector that is not a SQL database.** It checks settings against the
  connector's fields, encrypts its secret fields, and lists, previews and
  reads through the SDK; the stream lives in `ExtractionJob.stream_json`. SQL
  databases keep their own path (`is_sql`).
- **Tables are written by `service_destinations/sql_writer.py`** for both
  PostgreSQL and MySQL: `plan_table` (the preview and the write use the same
  plan) then `write_frame`. Column types come from the values
  (`column_kind`), not the pandas dtype, because parsed files hold object
  columns. "Update matching rows" is delete-then-insert in one transaction.
- **Copy a database plans through the type lattice** (`copy_database.py`,
  `shared_python.types`): a lossy cast is marked lossy, a type the target
  lacks gets a note, and what the copy does not carry is counted from the
  source's inspector. Keep the report honest when adding a target.
- **Server paths go through `shared_python.server_files.confine`.** Anything
  that reads or writes a folder on the server stays inside
  `SERVER_FILES_ROOT` (default `data/server-files`).
- **URL-fetching connectors install `shared_python.outbound`'s guard.** The
  cloud metadata address is always refused; loopback and private networks
  are governed by `OUTBOUND_ALLOW_LOOPBACK` and
  `OUTBOUND_BLOCK_PRIVATE_NETWORKS`.
- **Every read path that hands rows, values or column names to a person
  goes through `service_enterprise/policy_view.py`** (A6): `Reader.for_user`
  (or `PUBLIC` for a shared link), then `view_for(...).frame/preview/profile/
  schema` or `narrow_frame`. Import it inside the function to avoid a cycle.
  A new read path belongs in `test_policies_everywhere.py`.
- **The network gate is in `get_current_user`** (`service_auth/network_gate.py`,
  registered by `service_enterprise`): sign-in, SSO, renewal, sessions and API
  tokens all pass it. Client addresses come from `request_address`, which
  trusts `X-Forwarded-For` only for `TRUSTED_PROXY_HOPS` hops.
- **Storage is wrapped in `EncryptedStorageBackend` when
  `STORAGE_ENCRYPTION_KEY` is set** (`storage/factory.py`); files without the
  `PWENC1` header still read. Go through the backend, never the disk.
- **Counts in words**: `countOf` on the web (`lib/format.ts`) and
  `shared_python.words` (`noun`, `count_of`, `listing`) on the server; never
  "(s)". Platform roles show through `platformRoleLabel` ("Platform
  administrator" or "Member"; only `admin` means anything platform-wide).
- **The help is `docs/user/`**, rendered at `/help` by `lib/help/markdown.ts`.
  A page is listed in `lib/help/pages.ts`; `help.test.ts` fails a broken link,
  a tab whose "Read more" has no section, or a retired word. The API guide's
  curl examples are run by `test_api_guide.py`: change the API and the guide
  together.
- **Element CSS lives in `@layer base`** in `globals.css`. An unlayered rule
  beats every Tailwind utility; `global-styles.test.ts` fails one.
- **A workflow has tasks, a recipe has steps.** A task that is not filled in
  (`graph.missing_setting`) lets the workflow save but not run; the editor
  checks the same rules live (`features/workflows/missing-setting.ts`). Keep
  the two in step. The Deliver task goes through `deliver_dataset`, like
  Send to.
- **Tier words**: "Tested", "Tested live", "Tested on a recording", "Not yet
  tested" (`service_connectors/protocol.py`). The catalogue shows tested
  connectors first and the rest under "Available on request"; never relabel
  an untested connector as tested.
- **Long work goes to the worker through `service_pipeline_runs/background.py`**
  (A7): `background.register(run_type, handler, on_fail=...)` at import, a
  request `queue`s a run with its `request_json` and answers at once, the
  handler reports with `background.progress` (which renews the lease), and
  `on_fail` marks whatever else the run was for (a large upload's dataset)
  when it fails outside the handler's own care or its worker stops. Add the
  module to `tick_background`'s imports in `workflow_worker.py`. The page
  follows the run (`dataset-being-read.tsx`, the copy and delivery windows).
  Thresholds: `IN_REQUEST_BYTES` (25MB uploads), `deliver.IN_REQUEST_ROWS`
  (50,000), copies always.
- **Stored files go through `build_storage_backend`** (`local` or `s3`,
  wrapped for encryption when keyed). Relative `UPLOAD_ROOT_PATH` and
  `SERVER_FILES_ROOT` are anchored to `apps/api-gateway`. Every gateway and
  worker must see the same files: a bucket or one `ReadWriteMany` volume.
- **Rate limits are `shared_python.rate_limit.hit(db, LIMIT, caller)`**, a
  window row per key in the database, raising `TooManyRequestsError` (429,
  `Retry-After`). Tests that sign in many times set `RATE_LIMITS_ENABLED=false`
  or patch `hit`.
- **The limits a buyer reads are `api_gateway/status.py` `ceilings()`**,
  each read from the constant or setting that enforces it; a new enforced
  limit belongs there (`test_ceilings.py`).
- **Picking a workflow run up compares task fingerprints**
  (`executor.settings_hash`: the task's type and settings), never timestamps:
  a succeeded task is reused while it is unchanged and every task before it
  was reused. A stalled or crashed run finishes through `_finish`, so it
  notifies like any failed run. While a run works, `shared_python.lease.kept`
  renews its lease from a side thread; without it, a run longer than its lease
  was failed by a second worker while still running.
- **Traces are `api_gateway/tracing.py`**, off unless `OTEL_ENABLED`; SQL
  spans come from SQLAlchemy's engine events (`trace_statements`) because
  the OpenTelemetry SQLAlchemy package refuses SQLAlchemy 2.1. The
  correlation id is `X-Request-ID` (`CorrelationIdMiddleware`), on the span
  and the audit entry.
- **Browser tests are `apps/web/e2e/`** (Playwright, `npm run test:e2e
  --workspace @platform/web` with `E2E_BASE_URL`): `auth.setup.ts` signs in
  once (the sign-in rate limit would refuse a sign-in per test), tours are
  marked done from `ALL_TOUR_IDS`, and `accessibility.spec.ts` fails a
  serious or critical axe finding or a page without exactly one `h1`. An
  editor whose name sits in a toolbar passes `heading` to `AppFrame`.
- **Walk every page at the end of a phase with `apps/web/e2e/walk-pages.mjs`**
  (after `npx playwright test --project setup`; `--width 1024`, `--project`,
  `--only`): it reads the routes from `src/app`, fills ids from a real
  project, and reports error text, console errors, 5xx answers, sideways
  scrolling, unnamed controls, cut-off tab lists and headings. A7's final
  walk: 71 pages at 1280 and 1024, 0 problems, and the three detail pages
  this project lacked walked from projects that had them.
- **Read a stored dataset with `service_ingestion/read_copy.frame_of`**
  (storage, path, bytes, file type, the version's `ingest_spec_json`), never
  by parsing the file yourself. It reads with the settings the person
  confirmed at import and keeps a columnar copy beside the file; anything
  that deletes or rewrites a stored file calls `forget_copy` (erasure uses
  `strict=True`). Each `DatasetVersion` carries its own spec
  (`stored_file_spec(db, path)`); a rollback restores the target's.
- **A new dataset version records its measures** in
  `apply_dataset_materialization_success` (savepoint, best effort) and checks
  the dataset's alerts (`service_observability/alerts.py`). Alert events are
  sent by the worker after commit (`send_due`, claimed with a conditional
  update). A workflow task tags the measures its data wrote, not twice.
- **Outbound events reach channels through `dispatch_external_notifications`**;
  a webhook channel signs with `Pipewright-Signature: t=..,v1=HMAC-SHA256(t.body)`,
  records each attempt (`webhook_deliveries`) and retries 408/429/5xx twice.
  A new event type goes in `ALLOWED_EXTERNAL_NOTIFICATION_EVENT_TYPES`,
  `EXTERNAL_NOTIFICATION_EVENT_TYPES` (shared types) and `EVENT_LABELS`.
- **Project bundles are `api_gateway/bundles.py`**: names, not ids, travel;
  items are made through each service's own create function; a stand-in
  dataset is checked for the columns each item uses. A new kind of project
  object that should move between projects needs a section there.
- **After changing the API, run `scripts/generate-client.py`** (from
  `apps/api-gateway`). `clients/python/tests/test_client.py` fails until the
  generated `_operations.py` matches; two routes may not share a function
  name (give one `name=` in the decorator).
- **Embeds** (`service_reporting/embeds.py`): HS256 tokens per embed secret,
  verified with that secret only; `/embed/<token>` is the one page without
  `X-Frame-Options`, framed only by the web's `EMBED_ALLOWED_ORIGINS`
  (`src/proxy.ts`). Public pages fetch through `lib/api/public.ts`, which
  passes the viewer's address on for the rate limit.
- **The audit log names what a request made and what a deletion removed**
  (201 answers are read for the new id; a DELETE reads the name first), and
  the sign-in check notes the actor on `request.state.audit_actor`, so API
  token changes are not "Someone". The project's Activity stream
  (`api_gateway/activity.py`) reads that log plus runs, incidents, comments
  and alert events.
- **Shell and navigation words come from `apps/web/messages/en.json`** via
  `t()`/`tList()` (`lib/i18n.ts`, keys type-checked); dates, times, numbers
  and text sorting only through `lib/format.ts`, in the catalogue's locale
  (en-GB). `i18n.test.ts` fails a formatter or `toLocaleString` anywhere
  else, and the language lint reads the catalogue.
- **One version** (A9): the gateway's `APP_VERSION` default, its
  pyproject, `apps/web/package.json` (and the lock file), the client's
  pyproject and the Helm chart's `version`/`appVersion` move together;
  `test_one_version.py` fails otherwise. Regenerate the client and
  `docs/api/openapi.json` (`scripts/generate-client.py`) after a bump.
- **A new installation's first administrator** is made at start-up from
  `AUTH_BOOTSTRAP_USERNAME`/`_PASSWORD` while no account exists
  (`api_gateway/first_run.py`); `platform-bootstrap-user` still makes others.
- **The browser calls the API at `/api/v1` on its own host** (the web image's
  default); Caddy and the chart's ingress send `/api` to the gateway, and the
  API reference is `/api/docs`. The web's server reaches the gateway by
  `API_INTERNAL_BASE_URL`, which the chart fills in itself.
- **The Helm chart is installed on a new kind cluster in CI by the deployment
  guide's own commands** (`scripts/helm-install-check.sh` reads the shell
  blocks of "On Kubernetes with Helm"). Changing those steps changes the
  test; a hook (the migration job) must not read the release's own
  ConfigMap or Secret, which Helm makes after hooks.
- **The help's pictures are of the demo**, taken by
  `apps/web/e2e/screenshots.mjs` into `docs/user/images/` and shown with
  `![what it shows](images/name.png)`; `help.test.ts` fails a missing,
  undescribed or unused picture. Retake them after changing a pictured page.
  `apps/web/scripts/build-docs-site.mjs` builds the same pages as a static
  site; `.github/workflows/docs-site.yml` publishes it only when started.
- **CI has no `.env`.** Locally `api_gateway/config.py` loads
  `apps/api-gateway/.env` into the environment, so a test that stores a
  secret sets its own `APP_SECRET_ENCRYPTION_KEY`. Run
  `APP_SECRET_ENCRYPTION_KEY= npm run verify` before pushing such work.
- **Toolbars and tab strips wrap or fit; they do not scroll sideways**
  (`ribbon.tsx`, `area-tabs.tsx`): a scrolled-away button is hidden from
  everyone and unreachable by keyboard.
- **`test_error_words.py` reads every string the services hold**: no "(s)"
  count anywhere, and no retired word (node, rule, gate, pipeline...) in a
  `message=`, `title=` or `summary=`.

**The production-readiness sequence (P0–P9) is complete** as of 2026-09-23 —
see `docs/plans/production-readiness-workflow.md` for what each phase delivered
and what it deliberately left. Tracks A, B and C of the product roadmap are
complete, 18 (time travel) shipped as P7, and 19, 20 and 22 each shipped a
first slice as P9. **What is left is the rest of Track D**, in this order of
value: Phase 20's remaining sources (MySQL binlog first — the connector exists,
the change log reader does not) and streaming transforms; Phase 19's data
contracts on top of the drift detector; Phase 22's statistics (the rewrites
exist, a cost model needs row and distinct counts the platform does not collect
yet); Phase 21's co-editing; Phase 23; and more tool categories on the Phase 16
registry. The one cutover still pending is lineage from the IR (below).

The thesis track is finished: 08 (types + IR) → 09 (design) → 13 (grid) → 14 (formulas) →
12 (pushdown) → 15 (write-back) → 17 (SQL IDE) are all done, and 16 shipped its
machinery plus 167 tools. Together they are the whole argument — an analyst edits a
live table in a grid, reaches any of 167 tools from a right-click or Ctrl+K, drops
into SQL or Python when the visual tools run out, and every edit is a reviewed
statement with lineage. What is left is the rest of depth (19–23) and more tool
categories. Both cutovers this section used to list — the IR as the only
executor, and pushdown wired into extraction runs — were made in P9.

### Phase 08: the IR is the only executor; lineage is the one thing still not cut over

Since P9 (commit `3ca069c`), `service_transformations/executor.py` compiles every
step to IR and runs it through `ir.pandas_backend.execute`. Steps the algebra
does not model (fills, dedupe-with-order, splits, the tool step's harness) are
`Extension` nodes with registered handlers, so they still run — they just never
push down. The per-step pandas table is gone; `test_executor_cutover.py` proves
the outputs and warnings match what the old path produced.

**Lineage is still derived from `columns.py`.** `service_lineage/from_ir.py`
derives *schemas* from the IR, not column-to-column edges, so the lineage graph
the API serves still comes from the per-step table in `columns.py`.
`test_matches_ir.py` proves the two agree. Cutting lineage over means writing
edge derivation from IR expressions first (each `Project`/`Aggregate` output
names its inputs via `columns_used()`), then deleting `columns.py`. A deliberate
separate step, sized on its own; not an oversight.

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

### Phase 11 notes: ingestion intelligence

`services/service-ingestion`. Read `sniff/evidence.py` first -- every stage of
the pipeline returns a `Finding` and the whole package follows from that shape.
Then `spec.py`, which is what the pipeline produces and the only way rows are
materialised.

- **`AMBIGUOUS` is not "low confidence".** It means several readings fit and the
  file does not choose. Such a finding is `blocking`, the upload is refused, and
  both readings come back in words. Do not "improve" this by adding a default;
  the roadmap's requirement is that an ambiguous date is asked about.
- **The date scan reads every value, not a sample.** The single row that settles
  a thousand-row column can be anywhere, and a sample is exactly how it gets
  missed. `test_corpus.py::disambiguated-by-a-late-row` is the guard.
- **`analyse(..., limit=...)` has no safe default.** `ANALYSIS_ROWS` for a
  preview, `None` to read the file. The sample leaking into the import path was
  a real bug: every upload was silently cut to five thousand rows and reported
  success.
- **A value written with a decimal point is a decimal**, even when round. `10.0`
  narrowed to an integer drops the cents from a price column.
- **A leading zero means an identifier.** `01234` read as a number becomes 1234,
  and unlike most inference mistakes nothing about the result looks wrong.
- **An `.xlsx` is a zip.** `containers.is_document_zip` is why it is not
  unwrapped as one, and `formats.detect_format` calls the same function rather
  than a second, weaker check.
- **A modal line width can tie**, when a file has as many preamble lines as data
  rows. Both `header.py` and `formats.py` break the tie towards the *wider*
  shape; breaking it the other way makes the preamble the table.
- **A `.sql` dump is parsed, never executed.** `split_statements` scans the
  original characters so a semicolon inside a literal does not truncate the
  file. Only `CREATE TABLE` and `INSERT` are acted on; everything else is
  counted and ignored.
- **A spec is found again by column fingerprint first, name pattern second.**
  The fingerprint is order- and case-insensitive, because a reordered or
  re-spelled column is the same report.
- **`nested.flatten` and `nested.normalise` require an explicit field list.** A
  tool whose output columns depend on the rows cannot be predicted by lineage,
  and `test_tool_library.py` enforces that predicted equals actual for every
  tool. `nested.infer_json_schema` exists to produce the list.
- **The corpus is generated, not checked in.** `tests/corpus.py` is the
  description of what makes each file awful; a binary fixture is opaque. It is
  loaded by path because pytest runs with `--import-mode=importlib` and a bare
  `from corpus import ...` resolves against the rootdir -- and the module must
  be put in `sys.modules` before it executes, or `dataclasses` cannot resolve
  its own annotations.

### Phase 10 notes: the connector factory

`services/service-connectors`. Read `protocol.py` first for `Tier`, then
`generators.py` for how the catalogue is assembled. Four tables produce it:
`manifests/*.yaml`, `dialects.py`, `stores.py` and `datastores.py`.

- **A tier is a citation, not an assertion.** `verified_by` names a test file;
  `test_generators.py` resolves it and checks the file actually drives that
  connector; `ConnectorSpec.__post_init__` refuses a tier above 4 without one.
  Adding a tier without a test that mentions the connector fails the suite.
- **Nine PostgreSQL-wire dialects stay at tier 4 on purpose.** CockroachDB and
  friends run the exact code path `test_containers.py` exercises. Promoting them
  would conflate "the driver works" with "the product works", and
  `test_a_postgres_wire_dialect_is_not_quietly_promoted` pins that.
- **A skipped container test is a green build.** `test_containers.py` skips a
  server it cannot reach, which is right for a laptop and wrong for CI — so
  `scripts/check-connector-servers.py` runs first in `ci.yml` and fails the
  build instead. `docker-compose.connectors.yml` is the laptop equivalent.
- **The vendor contracts are deliberately redundant with the manifests.** Both
  were written from the vendor's documentation, so a disagreement means one is
  wrong. That redundancy is what found the pagination bugs; do not "simplify"
  `test_vendor_contracts.py` by reading the values out of the manifest.
- **Pagination parameter names travel with the strategy.** `PageParams` reads
  `page_param`/`size_param`/`offset_param`/`cursor_param`/`start_page` from the
  config. A name declared and then ignored is worse than none: the API answers
  with page one and the loop collects the same rows to `MAX_PAGES`.
- **`next_url` is a separate strategy from `cursor`**, because a large family of
  APIs return the *address* of the next page rather than a token.
  `resolve_next_url` refuses a cross-origin one — the credential is in a header
  and httpx sends it wherever it is pointed.
- **`httpx` `params=` replaces a URL's query, it does not add to one.** Passing
  an empty dict alongside a next-page URL silently discarded the page marker.
  `merge_query` exists for that; do not go back to `params=`.
- **The tier caveat is built in exactly one place.** `with_tier_note(result,
  spec)`. Three connectors used to compose the sentence themselves and a fourth
  quietly did not; a structural test now fails any adapter that reads rows
  without either attaching the note or delegating to a base class that does.
- **A URL-safety rule applies to the values that reach the URL.** Scanning the
  whole config made every Basic-auth connection unconfigurable, because those
  credentials are email addresses and `@` is not allowed *in a path segment*.
- **The watch keys snapshots on the qualified name.** `public.orders` and
  `analytics.orders` are different tables; a bare name compares one against the
  other and then collides on the unique index.
- **"We could not look" is not drift.** A credential that expired or a host that
  is down is reported as skipped with the reason. Recording it as missing
  columns files a breaking incident every time a VPN drops.
- **`watch.sweep` and `sweep.sweep_project` are different things.** The first
  compares shipped manifests against a caller-supplied previous state and needs
  no database; the second is the nightly job over configured connections. The
  docstrings say so, because the names do not.

### Phase 17 notes: the workbench, the notebook and the sandbox

`services/service-workbench`. Read `sandbox.py` first if you touch anything
there; read `safety.py` first if you touch the SQL side.

- **Read-only is a default enforced at three layers**, and they are not
  redundant: the permission table decides who may call `run` at all, the service
  narrows a requested mode to what the role carries (writes need **admin**), and
  the response reports the policy that was actually in force. Removing any one
  of them lets a client believe it is read-only when it is not.
- **`sql_text.split` scans the original characters.** Not a stripped copy --
  the offsets are part of the answer, because "error in statement 3" has to be
  able to point at statement 3. If you change it, the dollar-quoted function
  body test is the one that catches a naive rewrite.
- **A leading keyword does not tell you whether a statement writes.** A
  data-modifying CTE leads with `WITH`; `EXPLAIN ANALYZE INSERT` leads with
  `EXPLAIN` and performs the insert. Both are tested.
- **Statement timeouts are set per dialect and a missing one is reported.**
  Without them a workbench is a way to take a database down.
- **The sandbox's capabilities are probed by trying, in a child process.**
  `hasattr(resource, "RLIMIT_AS")` is true on macOS and `setrlimit` raises, so
  the earlier `hasattr` check claimed a limit that did not exist. On this
  machine the probe fails and **Python cells are disabled with a stated
  reason** -- that is correct, not a bug, and `test_notebook.py` skips the
  cell-running tests accordingly while still asserting the refusal.
- **Two sandbox escapes are regression tests, not theory.** `BuiltinImporter`
  hands back a module cached in `sys.modules` without firing an `import` event;
  `os._wrap_close.__init__.__globals__` reaches the real `os` regardless of what
  is in `sys.modules`. The first needs the purge, the second needs the audit
  hook. Neither alone is sufficient.
- **`run()` is the mechanism, `require_usable()` is the policy.** Keeping them
  apart is what lets the escape tests run on a platform the policy declines.
- **Notebooks run in the request.** Bounded rather than queued -- see the
  `notebook.py` docstring for why, and for what would change that.
- **`recipe_yaml.py` lives in service-transformations**, not here: it is about
  recipes, and the workbench merely exposes it.

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

| 2026-08-23 | `5754fbb2` | **Phase 17 complete.** `service-workbench`: statement splitter, read-only-by-default policy, multi-statement execution with per-dialect timeouts, EXPLAIN, live schema browser, cursor-aware autocomplete, saved queries, history, notebooks with a shared frame namespace, a probed Python sandbox, and lossless recipe-as-code YAML. 19 routes, migration 0028, three pages. Closed two real sandbox escapes and a capability check that claimed a memory limit macOS does not provide. 4,392 -> 4,701 Python, 573 -> 636 web tests |
| 2026-08-23 | `5754fbb2` | **Phase 16 partial (machinery complete).** Tool registry, 167 tools across 10 categories, IR catalogue 87 -> 186 functions, universal test harness, catalogue + preview API, generated reference, tool browser with live preview, type-aware column context menu, palette synonyms. Fixed `abs`/`round` raising on all-null columns, `to_date` failing a run on one bad value, mixed date formats silently losing rows, and `starts_with`/`contains` having no lowering at all. 2,113 -> 4,392 Python, 544 -> 573 web tests |
| 2026-08-22 | `5754fbb2` | **Phase 15 complete.** `service-writeback` (identity, change sets, compiler, dry run, blast radius, batching), 11 routes, migration 0027, Table editor page. Fixed a dry run that left DDL behind on SQLite, per-edit validation that blocked add-then-fill, and a blast-radius share rule that fired on a 3-row table. 1,993 -> 2,113 Python, 510 -> 544 web tests |
| 2026-08-22 | `5754fbb2` | **Phase 14 complete.** Formula lexer/parser producing IR, catalogue 40 -> 87 functions, formulas push down. Fixed a planner crash on a bare local scan and arithmetic typing that returned `unknown` for decimal x float. 1,827 -> 1,993 Python tests |

| 2026-09-16 | `add9b3f2` | **Phase 10 complete.** Connector factory: 211 connectors from four generators, 50 at tier 2 backed by vendor-contract fixtures, real PostgreSQL/MySQL/MariaDB containers in CI, and the whole S3 family. OData and JSON:API protocol connectors, the schema watch with drift incidents and a nightly schedule type (migration 0029), secret references, and a `/connectors/watch` API plus UI. Found five live bugs — dropped pagination parameter names, seven manifests treating a next-page URL as a token, httpx wiping a follow-up query, a SQL connector `read()` that had never worked, and a URL check that banned `@` in every Basic-auth username — plus a tenancy leak and a stream-name collision in review. 4,701 → 5,621 Python tests |

| 2026-09-16 | `add9b3f2` | **Phase 11 complete.** Ingestion intelligence: a sniffing pipeline where every stage reports confidence and evidence and an ambiguous date blocks rather than defaults; ten per-format readers; the ingest spec, stored against a column fingerprint and reused next month; chunked resumable upload with checksum; a streaming profiler using Welford; six nested-data tools (167 → 173); a 72-file awful corpus; migration 0030 and an analyse-before-commit UI. Found seven real bugs including every import being silently truncated to 5,000 rows, `10.0` narrowed to an integer, `01234` becoming 1234, and a preamble becoming the table. 5,621 → 5,943 Python, 636 → 652 web tests |

| 2026-09-20 | `7b73c2ff` | Maintenance on branch `pw-dev/orchestrator-maintenance`: secret-vault path fix, project/dataset/user/org lifecycle endpoints (rename, archive, delete, deactivate, revoke), delete affordances across the UI, People and Organisations admin pages, dashboards page, workflow-run cancel, report delivery history, a 204-parse fix. 5,943 → 6,583 Python, 652 → 656 web tests |
| 2026-09-22 | `7b73c2ff` | **Development orchestrator removed.** `tools/dev-orchestrator/` deleted; `pw-dev-orchestrator` uninstalled from `.venv`; `.pw-dev/` runtime state cleared after preservation. The unmerged Phase 18 run (28 commits), its staged docs patch, the full planning record and run evidence are preserved in `backups/orchestrator-removal-2026-09-22/` (see its `RECOVERY.md`); the `pw-dev/run-20260918-d770792f/*` branches were kept. Rules moved to a single rules file (since folded into `CONTRIBUTING.md`); `docs/plans/phase-18-review-requirements.md` rewritten as runner-independent requirements. `npm run verify` green after removal: 6,583 → 6,021 Python tests (the orchestrator's own 562 left with it), 656 web |

| 2026-09-23 | `7b73c2ff` | **Production-readiness P0 (Truth & trust).** Adoption review published; `docs/plans/production-readiness-workflow.md` written (P0–P9). Language pass (labels.ts: type/rule/severity names, friendly step messages; applied across Studio, upload, data-quality, login). DQ column dropdown. Schedule cron presets. Studio save-toast Run now/Schedule actions. Runtime visibility: oldest_queued_at + assessRuntime, Home Background-work card, stalled banners on Workflows/Schedules, linked health chip, honest health panel. System-status humanised (chips + collapsed drivers + raw toggle). Rail labelled by default + Administration section. Breadcrumb shows project name. Warning debt 20→0 (JWT keys, pydantic shadow filtered at site, starlette deprecation in pytest.ini). 6,021→6,022 Python, 656→673 web. Verified live in browser. |

| 2026-09-23 | `7b73c2ff` | **Production-readiness P1 (Identity core).** Migration 0031: users gain email/display_name/token_version; new api_tokens + auth_codes tables. Self-service password change and sign-out-everywhere (token_version invalidates every prior JWT); admin one-time reset codes; invite flow (inactive account + activation code, redeemed on the login screen); scoped revocable API tokens (pw_ bearer, read/write/admin, shown once, hashed at rest); display name in greeting/People; org create+rename (PATCH /organisations/{id}); Settings Security + API-tokens panels; password-strength meter; docs/security.md. Audit middleware now records /auth admin actions (narrowed the credential skip to login/password/redeem/tokens only). 6,022→6,038 Python, 673→678 web, zero warnings. Every flow verified live: token mint/scope-403/revoke-401, invite→inactive→activate, password change 200→401, admin reset, org rename — plus Settings/People UI in the browser. |

| 2026-09-23 | `4d2333f` | **Production-readiness P2 (Guided first win).** Project page leads with a live-ticking, dismissible checklist (Add data → Shape → Guard → Schedule) and the old chip-wall regrouped behind a Workspace menu (Build/Govern/Operate/Publish); entry-points merged to Add data · Connect a source (Register dataset moved to advanced). Home “Get started” now mirrors the first project’s real state. One-click **Create a demo project** seeds a full worked example from the same service functions a user’s clicks call — orders CSV (missing amount, missing email, negative refund) → filter pipeline → not-null rule → daily schedule → revenue-by-region chart → dashboard — deletable like any project, composed in the gateway (the one layer already allowed to touch every service) and covered by an end-to-end test against a real DB. Save-pipeline naming prompt + inline rename; first-run mini-tours for Data quality and Schedules; type fidelity via a stored `canonical_type` with a cross-surface test. Resumable chunked upload carried to P3. `npm run verify` green with zero warnings; every surface verified live in the browser (checklist, Workspace menu, both mini-tours all 3 steps, demo seed → chart renders on its dashboard, Home get-started mirror confirmed accurate against the API). Commits 6c5c55e, 9fe4d4c, d7f19b4, 4d2333f — author/committer harshkvpatil98, no AI attribution. |

| 2026-09-23 | `1d3af1b` | **Production-readiness P3 (Operational backbone).** Migrations 0032 (runtime_heartbeats) + 0033 (upload_sessions). Runtime heartbeats: the workflow worker and schedule ticker each beat a row every loop, so platform status carries ground truth (fresh=alive, stale=dead, none=never started); assessRuntime consumes beats first and falls back to queue-age inference. Packaged runtime: scripts/worker.sh supervises both processes, dev.sh starts them (PW_DEV_NO_WORKERS=1 to opt out), run_due_schedules gains a --loop ticker mode, docker compose gains app/worker profiles with restart policies. System-status Runtime panel + Home card show per-component heartbeat/host + queue depths. A stalled queue (>30 min, no beating worker) opens a runtime incident from the ticker and auto-resolves on drain. Workflow-run failures now notify in-app like every other run; the first-run checklist offers Slack/email targets. Dashboard sharing finished end to end: unauthenticated GET /public/dashboards/{token} + a /shared/dashboards/{token} viewer (robots-noindex, results-only payload, immediate revocation), with Share/Copy link/Revoke on the dashboards page. Real cross-project /runs (status filter) and /datasets (name search) replace the redirects, scoped by the same owner-or-shared rule as the project list, with nav + palette entries. Upload sessions moved to a durable upload_sessions table (absorbs the resumable item carried from P2) — verified live: a 20MB upload's first chunk survived a mid-upload gateway restart. `npm run verify` green with zero warnings: 6,069 Python passed / 573 skipped, 683 web passed, lint/typecheck/build green. Every surface verified live in the browser (Runtime panel healthy + down states, both mini-tours, stalled-queue incident open+resolve against the real DB, notification offer, shared-dashboard chart render, /runs status filter, /datasets search). Deferred stretch: dead-letter view for failed workflow nodes with re-run. Commits 0c0c538, 25414bb, 1a393de, c10d6c6, e619875, b8ec220, 8f46f24, bfdf560, 1d3af1b — author/committer harshkvpatil98, no AI attribution.|

| 2026-09-23 | `a2bbd62` | **Production-readiness P4 (Enterprise identity).** Migrations 0034 (user_mfa), 0035 (sso_login_states), 0036 (users.auth_source). TOTP two-factor: RFC 6238 in-repo (no third-party TOTP dep), enrol with a server-rendered segno QR + secret, confirm-before-active, login two-step (password → short-lived distinct-audience ticket → TOTP or one-time recovery code), regenerate/disable (both require a live code), admin reset; Settings panel + login MFA step. OIDC SSO wired end to end onto the existing pure logic: /auth/sso/status (public), /start (discovery + PKCE + durable one-time state), /callback (state verify, code exchange, JWKS-verified ID token, claim mapping, JIT provisioning with group→role and no silent demotion, session cookie), 'Continue with SSO' on login when configured, graceful redirect-with-message on provider error. SAML deliberately absent (signature-verification refusal stands) and surfaced via the status endpoint. SCIM-lite deactivate-on-absence job (`scim-sync` CLI): only auth_source='sso', never the last admin, ends sessions on deactivate. docs/enterprise-identity.md written. `npm run verify` green, zero warnings: 6,106 Python passed / 573 skipped, 683 web passed, lint/typecheck/build green. Verified: TOTP against RFC vectors + 19 MFA tests; 12 SSO-flow tests with a real RS256 token + matching JWKS (transport faked); 6 SCIM tests. Live against the running gateway: full MFA enrol→activate→two-step login (TOTP and recovery code, wrong-code 403), public SSO status, 'Continue with SSO' button, graceful failure when the IdP is unreachable. HONEST GAP: the OIDC/SAML wire protocol is unverified against a live Auth0/Okta/Entra tenant (none available here); the authenticated MFA Settings panel was not screenshotted because the browser session expired and password entry into the login form is a restricted action. Deferred: inbound SCIM 2.0 push, per-org session policy. Commits fe1e3cc, 9f614e1, c02d68b, a2735dd, a2bbd62 — author/committer harshkvpatil98, no AI attribution.|

| 2026-09-23 | `d9ba8ba` | **Production-readiness P5 (Deployability & scale).** Helm chart (deploy/helm/pipewright): per-component images/resources, pre-install/upgrade `alembic upgrade head` Job, ingress routing /api→gateway and /→web on one host (SSO cookie carries), optional HPAs for gateway+web, operator-owned secret via existingSecret, image tag required (never 'latest'), one-ticker scaling guidance baked in. Production docker-compose.prod.yml with a Caddy auto-TLS proxy (deploy/Caddyfile) and a managed-DB escape hatch. CI workflow release-images.yml builds+pushes gateway + web images to GHCR on a v* tag. docs/operations.md runbook: upgrade, backup/restore with the `backup.sh --verify` drill, scaling (workers scale freely, one ticker unless distinct SCHEDULER_RUNTIME_ID, uploads durable so no sticky sessions), sizing table, observability (/metrics Prometheus, correlation-id tracing, DB_SLOW_QUERY_MS). New opt-in slow-query log (shared_python.db.slow_query + DB_SLOW_QUERY_MS): logs only statements past the threshold with the correlation id, off by default, 3 tests. Dependency-free scripts/perf-baseline.py hits the ten hot endpoints (p50/p95/req-s, --budget-ms CI gate); first numbers recorded (0 failures; /status is the fan-out outlier). `npm run verify` green, zero warnings: 6,109 Python passed / 573 skipped, 683 web passed, lint/typecheck/build green. Helm validated by YAML+brace checks, compose by `docker compose config`; perf script run live against the dev gateway. Deferred (push further): SBOM + pip-audit/npm audit CI gate. No `helm` binary here to run `helm template` against a cluster. Commits 3886fcb, 7c571cb, 168ed89, b04f3d1, d9ba8ba — author/committer harshkvpatil98, no AI attribution.|

| 2026-09-23 | `ccf9067` | **Production-readiness P6 (Governance depth).** Five features, each committed and pushed on its own. **Audit Center** (`apps/api-gateway/src/api_gateway/audit_center.py`): admin-only cross-project `/audits` stream with filters + CSV/JSON export + a retention sweep (`audit_retention_days`) wired into `run_due_schedules.py`; web `/audits` page + Administration nav. **Policy simulation**: `preview_policies_as_user` extends security-preview to "view as role/user" (`viewed_as_username` on the response); web policy-simulation panel in Governance. **Approvals UX**: `change_request` comment target + a reviewable comment thread with "Request changes" on the changes page. **Erasure lifecycle** (against phase-18-review-requirements §2): correction vs destructive mode, no silent success — completion only when nothing blocked, destructive refuses to overwrite derived datasets (blocked), unreadable datasets blocked; migration 0037, mode selector + blocked display in Governance. **Catalog**: edit ownership/certification/description/tags from a dataset's own page (`dataset-catalog-panel.tsx`) and link/unlink glossary terms per column; naming an unknown steward is refused, empty clears, repeat links idempotent. `npm run verify` green: 6,128 Python passed / 573 skipped, 683 web passed, lint/typecheck/build green (the one "Grid palette could not resolve" line is a pre-existing studio jsdom test log, unrelated to P6). Deferred (push further): PII auto-suggest data-classification tags — a service-intelligence feature sized on its own. HONEST GAP: verified via unit/service tests + curl; the authenticated web surfaces were not screenshotted because the browser session expired and login-form password entry is a restricted action. Commits 428b4ac, 6011f22, 82e614c, 6d98e8a, ccf9067 — author/committer harshkvpatil98, no AI attribution.|

| 2026-09-23 | `55f3c28` | **P6 deferred items closed + P7 (Time travel) increment 1.** Closed P6's two open items: (a) data-classification tags — the catalog panel on a dataset page now scans for PII (the existing deterministic pattern/checksum detector, no model call) and turns findings into classification tags (`pii` umbrella, per-kind tags, `sensitive` for high-harm kinds) a steward adds in one click; (b) the last blemish on the zero-warning bar — the `Grid palette could not resolve` `console.warn` was a jsdom test-env artifact from `grid-scale.test.ts` rendering the grid without CSS vars; captured and asserted as the expected palette warning (production warning intact). Then began **P7 per `docs/plans/phase-18-review-requirements.md`, increment 1 (version storage & publication)**: `content_digest` primitive (`shared_python.storage`, `sha256:<hex>`); `dataset_versions` table (migration 0038, schema-only per decision #5) with one immutable row per materialisation, `version_number` monotonic and `(dataset_id, version_number)` unique, content hash + snapshot metadata, never renumbered (decision #6); the §5 transaction-ownership seam (`apply_dataset_materialization_success` flushes and leaves the commit to the caller, `finalize_…` is the commit-owning wrapper the four producers still call) so head advance + version publication land or roll back together; all four producers (uploads, extraction, transformations, quality quarantine) record a version with the digest of the bytes they wrote; read surface `GET …/datasets/{id}/versions` (viewer, §6-correct) + a Version history panel on the dataset page, storage keys kept out of the API (§4/§5). `npm run verify` green, **zero warnings** (grid warning now gone): 6,145 Python passed / 573 skipped, 683 web passed, lint/typecheck/build green. Alembic chain can't run on sqlite (a pre-existing migration uses Postgres JSONB); table validated via `Base.metadata.create_all` as the suite does. **P7 is NOT complete** — remaining increments: §1 per-producer logical-identity write-ups (esp. extraction's dataset-per-run), `AS OF` read/query, diff (decision #7 identity rules), rollback (append-a-version, decision #6), deterministic replay with recorded execution context (§3), erasure-vs-immutable-snapshot reconciliation (§2: destructive erasure still overwrites the head artifact in place), concurrent-GC protocol (§4), full authz matrix for query/rollback/replay (§6), and the live end-to-end acceptance script (§8). HONEST GAP: verified via unit/service tests; authenticated web surfaces not screenshotted (browser session expired; login-form password entry is a restricted action). Commits 235723c (data-classification), 0d2dd24 (grid-warning), 84b2a88 (content-digest), 73bc325 (version-storage), 55f3c28 (version-read) — author/committer harshkvpatil98, no AI attribution.|
| 2026-09-23 | Business requirements | Created a business-review BRD and 40-page PDF covering target groups, personas, use cases, 65 current requirements, 41 planned/partial scope groups, 7 exploratory bets, acceptance/risk/rollout guidance and the 173-tool inventory. Reconciled stale counts and the first three P2 commits against baseline `79eb302`. All pages rendered and visually reviewed; text checks confirmed every requirement/tool ID and 40 bookmarks, with no unresolved placeholders or boundary overflows. `npm run verify` passed outside the sandbox: 6,041 Python passed, 573 skipped, 678 web passed, lint/typecheck/build green; local skips do not establish live infrastructure coverage. The first sandbox attempt had 306 socket-permission setup errors, not a passing check. No application source was changed for this document; concurrent P2 development is separate. |

| 2026-09-23 | P7 increment 2 | **P7 (Time travel) increment 2: temporal reads, §1 decisions, live verification.** Versions now store the preview they published (migration 0039, schema-only); `GET …/versions/{n}` + `GET …/versions/{n}/preview` read a dataset **as of** a version (both GET → viewer, §6-correct); a View-data modal per version in the history panel. `docs/plans/phase-18-decisions.md` records the §1 per-producer identity answers — every producer creates a new dataset per run today, so each dataset has exactly one recorded version until rollback lands; extraction keeps dataset-per-run (the watermark lives on the job); temporal reads mirror the head preview's security posture (apply_policies has no read-path caller — simulation only), so no new bypass. **Verified live in the browser this time** (the prior HONEST GAP is closed for these surfaces): dev Postgres migrated 0037→0039 (both new migrations ran clean on real Postgres); dev gateway restarted from this checkout on :8100 — it needs `BACKEND_CORS_ORIGINS` as a JSON list including `http://localhost:3002` or every client-side panel fails with "Failed to fetch" (the config default allows only :3000); uploaded a CSV → version 1 recorded, server digest matched a local sha256 of the same bytes byte-for-byte, 404 for a missing version; history panel + current pill + View-data modal render the snapshot; PII scan on a card/phone/email dataset found all three (high) with the method stated, Add-as-tags → steward → certify → Save persisted and surfaced as catalog facets (certified count and tag list confirmed via API). `npm run verify` green, zero warnings: 6,148 Python passed / 573 skipped, 683 web passed. Remaining P7 (unchanged): AS-OF SQL query, diff, rollback, replay with recorded context, erasure reconciliation, GC protocol, authz matrix for the write ops, scripted e2e acceptance. Two demo datasets (p7_sales, p7_people) left in the Consumption E2E project as evidence. Commits: temporal-read backend, version-view UI, phase-18-decisions doc, this docs update — author/committer harshkvpatil98, no AI attribution.|

| 2026-09-23 | `9744ba1b` | **P7 (Time travel / product Phase 18) complete.** Increments 3–6 on top of the earlier storage, temporal-read, diff, rollback and erasure work: (1) **§4 pin + two-step prune protocol** — migration 0040 (`dataset_version_pins`, `retention_state`/`delete_after`/`pruned_at`/`artifact_removed_at`), `version_lifecycle.py` (pin durable-before-read under a row lock; mark with a 30-min lease → re-validate under the lock → tombstone → delete bytes; rescue on pin; refuse after prune; crash-resume; shared bytes never deleted), a `dataset_versions` retention policy wired into the governance sweep and the ticker, `EDITOR_SEGMENTS` (rollback/replay) + `query` read-only in the central matrix; (2) **§3 frozen clock + execution context** — `ir/clock.py` is the one clock for now/today/age_years, every transformation run records instant, semantic version, steps snapshot + digest, input pins (base + join/union datasets) and the output pin; (3) **deterministic replay** — `POST /runs/{id}/replay` re-executes recorded steps against pinned versions at the recorded instant, compares by digest or by ordered columns + canonical types + row multiset, answers equivalent / divergent / incompatible / unavailable / failed / unverifiable; audit page shows output pins for every producer, the context, and a Replay action; (4) **`AS OF` SQL** — `POST …/versions/query` in the workbench over an in-memory SQLite copy, by version or instant with the stated tie rule, viewer role; Query action + "Query as of" on the history panel. **Verified live**: dev Postgres migrated 0039→0040; gateway restarted from this checkout on :8100; `scripts/e2e/p7_time_travel.sh` ran **39/39** against it (upload→v1 digest = local sha256, context pins, replay equivalent, correction erasure → v2 with v1 still readable, diff with/without identity, rollback → v3 with v1's digest, AS OF by version/instant/before-first → 404, write refused, retention policy report-only); in the browser: history panel with Query/Diff/Restore (diff with identity → 1 changed/email; restore → v4 = v2's fingerprint), temporal query modal incl. Ctrl+Enter, run audit page pins + execution context + Replay → Equivalent. Browser gotcha: the web client reads its token from `localStorage["idp.access_token"]` first, so a cookie alone shows "Invalid or expired access token" in client panels. `npm run verify` green, zero warnings: 6,162 → 6,211 Python passed / 573 skipped, 683 → 685 web. Commits 3184037, 3e62192, 8b84a4a, b1a84f2 + this close-out — author/committer harshkvpatil98, no AI attribution. **Next: P8.** |

| 2026-09-23 | `9744ba1b` | **P8 (BI & collaboration) complete**, five commits: **dashboard builder v2** (aacbcc2 — a real authenticated dashboard page where none existed; one-call tile data under saved or ad-hoc global filters; in-place layout editing with drag reorder, width/height, add chart/text, remove; text tiles + stored auto-refresh via migration 0041; donut; KPI vs previous period with honest degradation; one chart-data helper for preview/chart/tile/share); **comments everywhere** (033f5f9 — shared discussion panel on datasets, pipelines, dashboards, change requests with @mention autocomplete; fixed the P6 review thread that called `/comments` instead of `/discussion` and never worked; `discussion` added to operator segments so operators can comment; mention notifications carry the target); **emailed invitations/reset codes** (662e6c8 — one `send_plain_email` primitive with attachments; code returned only when not emailed, with the reason; login prefills `?code=`); **report delivery + PDF** (476dc45 — Slack target with link, email target and per-recipient attachments, per-channel outcomes on the delivery via migration 0042, honest summary; reportlab PDF, paginated, landscape when wide, states what it leaves out; obsolete "no layout engine" refusal test retired with reason); **dashboard subscriptions** (792a07d). Dev Postgres migrated 0040→0042 clean. **Verified live in the browser:** dashboard page with filter chip, text tile, bar, KPI note, donut; ad-hoc filter apply; layout save; comment posted with a highlighted mention; reports page with target picker, PDF format and per-channel ✗ chips after a live run whose PDF was 2.2 KB `%PDF-1.4`; subscribe modal. HONEST GAP: no SMTP/Slack reachable here, so external channels were exercised with captured senders in tests and produced the stated failures live. `npm run verify` green, zero warnings: 6,211 → 6,239 Python passed / 573 skipped, 685 → 692 web (this row first said 6,240; the gate's own output said 6,239). Author/committer harshkvpatil98, no AI attribution. **Next: P9.** |

| 2026-09-23 | `9744ba1b` | **P9 (market-decider depth) complete — the production-readiness sequence P0–P9 is finished.** Five commits: **the IR is the only executor** (3ca069c — `executor.py` compiles every step to IR, unmodelled steps are Extension nodes with registered handlers, the per-step pandas table is gone; `test_executor_cutover.py`); **pushdown wired into extraction runs** (f5c5b19 — job `steps` planned against the connector surface, pushable prefix runs as SQL around the extract, rest here, plan recorded on the run, grain-changing steps refused for incremental loads, zero-row column probe; fixed a pre-existing `uuid` JSON failure in profiling that broke every Postgres extraction); **semantic layer** (04735a9, migration 0044 — metrics defined once with owner/measure/filters/dimensions and a governance version history, resolved by charts/dashboards/reports at compute time, rendered as SQL in the workbench, usage listed; Metrics page); **streaming** (cc2f9be, migration 0045 — public `POST /api/v1/hooks/{token}` with the token shown once and sha256 at rest, PostgreSQL CDC through a `test_decoding` logical slot read in micro-batches by the ticker with peek → store-by-position → advance, at-least-once stated, capability check names the fix, materialise into one append-only versioned dataset; dev compose Postgres now `wal_level=logical`; Live sources panel); **optimizer groundwork** (cb577cd — `ir/rewrites.py`, five provable identities before the planner splits, four-way differential test, rewrites listed in every plan; fixed the shape-YAML placeholder that used `type:`/`config:` keys the recipe parser rejects, and the parser now names the shape it expects). Dev Postgres migrated 0042→0045 clean. **Verified live in the browser:** shaped extraction run with plan + rewrites feedback (two filters after a projection and sort merged and pushed into WHERE against real Postgres); Live sources create (token modal), events viewer with LSN/xid, Poll now, Materialise → dataset link, delete with consequences; Studio plan strip with the "Rewritten first" block; metrics page and workbench panel earlier in the phase. Closed en route: `test_mfa.py` round-trip minted a ticket at a fixed past instant and verified against the wall clock — a time bomb from P4 that went off ~1h40m after it was written; it now mints on the real clock. **Deliberately left (HANDOFF §7):** lineage still from `columns.py`; CDC live test skips on CI (`wal_level=replica`); MySQL/Mongo/SQL Server CDC, queues, streaming transforms, exactly-once; data contracts; statistics/cost model/caching/federation. `npm run verify` green, zero warnings: 6,239 → 6,297 Python passed / 573 skipped, 692 web, ruff/eslint/tsc/build green. Author/committer harshkvpatil98, no AI attribution. **Next: the rest of Track D — see Recommended next action.** |

| 2026-09-23 | `9744ba1b` | **Adoption-readiness review** (no product code changed). Browser walk of every web route on the dev stack (59 pages, header menus, palette, new-project flow, Studio interactions, light/dark, logged-out sign-in) plus two read-only audits: information architecture/copy (31 rail items, 3 taxonomies, 24 eyebrow labels, 451 sub-12px text usages, 362 help strings at mean 13.9 words, duplicated Button/Modal/StatusBadge, 27 hand-rolled tables, no end-user docs) and feature coverage (329 API operations; 211 connectors of which 50 tested/161 never executed and none wired to ingestion beyond PostgreSQL/MySQL/SQLite; PostgreSQL the only real destination; no migration tooling). Defects found and recorded, not fixed: OpenAPI generation 500s so `/docs` is broken; Dashboards and the pipelines list absent from the rail; pipeline editor cannot open Studio-made recipes; `[object Object]` in dataset parser findings; PII detector flags dates as phone numbers; error banners before input on Charts/Notebooks/Workflows; v1 developer copy on Schedules; `/demo`, `/case-study`, `/testing` reachable; `docs/security.md` says SSO/MFA are planned. Written up as `docs/plans/adoption-readiness-workflow.md` (review + A0–A9 workflow with cold-user task gates). Temporary review project deleted; theme preference restored. **Next: A0.** |

| 2026-10-12 | Repository docs | **Documentation and hygiene for the public repository; no product code changed.** `main` fast-forwarded to `pw-dev/orchestrator-maintenance`. Added LICENSE (MIT), SECURITY.md (private advisory reporting), CODE_OF_CONDUCT.md, CHANGELOG.md, issue and PR templates, `.editorconfig`, and `license = "MIT"` in the root and web `package.json` and the gateway and service `pyproject.toml` files (setuptools floor raised to 77, the first that reads an SPDX `license`). README and CONTRIBUTING rewritten against `main`; `docs/security.md` no longer calls TOTP/OIDC planned (D11). `AGENTS.md`, `CLAUDE.md` and `docs/agent-context.md` untracked and ignored, their rules folded into CONTRIBUTING.md. CI diagnosis: the 2026-09-16 failure is the Linux sandbox gap now in §7, and `test_login_returns_bearer_token` also failed on any database without `user_mfa` — fixed by patching the lookup. `npm run verify` green with the connector servers up: 6,302 Python passed / 568 skipped, 692 web; a Linux/Python 3.11 container run of the CI bootstrap and pytest bundle (sandbox file deselected) passed apart from that login test before its fix. |

| 2026-10-13 | `75332b59` | **Adoption-readiness A0 + A1 complete.** A0: spec S1–S6 written into the plan (personas, 18-noun vocabulary, navigation tree, page templates, principles, voice guide) and the quick wins shipped — D1 OpenAPI 500 (function-local `Response` import under postponed annotations; `test_openapi.py`), D4 `[object Object]` parser findings, D5 dates as phones and every date as a birth date, D6/D7/D8 errors before input on Charts/Notebooks/Workflows, D19 21 read-only POSTs no longer audited (route list tested against the gateway), D20 designed not-found/error pages, D14–D17; `/demo`, `/case-study`, 23 dead or retired components and 9 placeholder feature stubs removed. A1: `lib/navigation.ts` read by rail, tabs, breadcrumb, switcher and Search, with a test that walks every `page.tsx`; rail of seven areas with tabs; eyebrows and the Workspace menu gone; new Datasets, Runs and project Settings pages; Overview, Sources, Schedules, Projects, Workflows, Dashboards and the dataset page rebuilt on the templates and vocabulary; renamed routes redirect. Found and fixed: Tailwind never scanned `packages/shared-ui`; the shared Modal could not scroll; tour Enter skipped steps; `humanDuration` "1 minutes"; listing extraction jobs 500'd for any project with a stepless import (P9 regression, `test_job_read.py`). Cold-user tasks in the browser: dashboards in 2 clicks, connect a database in 3. `npm run verify` green: 6,307 Python passed / 573 skipped, ESLint/tsc/build clean; 735 web tests after the last edits. Commits c2d9ce3 … d1ecc13 pushed to `main`. **Next: A2.** |
| 2026-10-14 | `75332b59` | **Adoption-readiness A2 complete.** Sample data (three untidy shop files, `GET /samples`, `POST /projects/{id}/samples/{sample}` through ordinary ingestion) and three recipe templates (`service_transformations/templates.py`, role matching, ordinary steps; "date" hint matched "notes", short hints now whole-word) behind one "Add data" dialog and the Studio's "Start from a template". Welcome on an empty workspace; checklist lights only the next step; Checks, People and Reports are lists with create dialogs; empty states offer a next step. "About this page" on every tab (help text beside each tab in `navigation.ts`, length tested). Notifications: migration 0046 (`group_key`/`group_count`, `notification_preferences`), each/daily summary/off per category, repeats of an unread failure count up. Charts named in words with "Put it on a new dashboard". 48 em-dash sentences rewritten with `wording.test.ts` guarding; every page has a browser-tab title (tested). Fixed: spaced phone numbers read as integers. Cold-user task "CSV onto a dashboard": 9 clicks plus typing, 0 error banners; every tab crawled on a full and an empty project with no error. `npm run verify` green: 6,344 Python passed / 573 skipped, 741 web, ESLint/tsc/build clean. Commits 7d792af … pushed to `main`. **Next: A3 (Studio redesign).** |
| 2026-10-14 | `75332b59` | **Adoption-readiness A3 complete.** Spec T1–T8 written first (measured: grid ~380×150px at the owner's laptop size, settings a grid-width from the step, 24 sub-12px sizes, header click silently adding a step, a second form editor). Studio rebuilt: header with name/source/saved state/undo/redo/Details/More/Save/Run; steps timeline with inline settings and one-line summaries (`step-summary.ts`); one Add-a-step palette over 20 built-ins and 173 tools (`/`, right-click a column, tools named for the column first); header click sorts the view only (`view-sort.ts`) with "Sort the whole table"; undo/redo (`recipe-history.ts`); browser drafts offered back (`recipe-draft.ts`); Details drawer (columns, where it runs, file, comments); 12px floor tested. One editor: `/studio?recipe=` opens and PATCHes; the form editor and helpers deleted, its three addresses redirect, links use `recipeHref`. Found during the run and fixed: 60-minute sessions with no renewal and raw "Invalid or expired access token" in panels; now `POST /auth/session/renew` (capped by `AUTH_SESSION_MAX_HOURS`), sign-in returns to the same page with a message, proxy keeps the query, sign-in `next` limited to same-site paths (was an open redirect); right-click also sorted a column; step defaults shared arrays with the catalogue. Cold-user task: 8 clicks, 58 s. `npm run verify` green: 6,351 Python passed / 573 skipped, 762 web, ESLint/tsc/build clean. Pushed to `main`. **Next: A4 (sources, destinations and migration).** |

<!-- Add a row above when you finish a session. Keep it to one line. -->
| 2026-10-14 | `75332b59` | **Adoption-readiness A4 complete.** Spec U1–U6 written first. U1: an import's and a recipe's runs add versions to one dataset (`reusable_dataset`, `output_dataset_id`, migration 0047 with backfill). U2: imports from any connector that can read through `service_extraction/connector_sources.py` (settings validated and secrets encrypted per connector, list/preview/import/resume, `stream_json`, migration 0048); "Connect a source" catalogue with tiers. U3: `sql_writer.py` loads PostgreSQL and MySQL (replace / add rows / update matching rows, keys become the primary key, types inferred from values), S3 and a server folder through the SDK's file connectors, a preview before writing, each delivery a run; Destinations page rebuilt; "Send to → A destination". U4: Copy a database plans through the type lattice (lossy casts marked, not-carried items counted), creates tables with keys and NOT NULL, streams rows, reports per table. U5: download any version as CSV/Parquet with policies applied. Security found on the way: the local-files connector read any server path (now `SERVER_FILES_ROOT`), URL-fetching connectors could reach the metadata service and the server (now `shared_python/outbound.py`). Also fixed: delivered columns all TEXT, TIMESTAMPTZ discovered as TIMESTAMP, "timestamp(3) with time zone" unparsed, REST `//path` became a host. Measured live: REST source (tier 2) imported 3 rows; MySQL update-matching-rows twice gave 20 added then 20 updated / 0 added; PostgreSQL shop schema (3 tables) copied to MySQL with microseconds, JSON, exact decimals, keys and NOT NULL. `npm run verify` green: 6,407 Python passed / 591 skipped, 770 web, ESLint/tsc/build clean. Pushed to `main`. **Next: A5 (copy, design system and consistency).** |
| 2026-10-14 | `75332b59` | **Adoption-readiness A5 complete.** Spec V1–V6 measured first (3,786 on-screen strings via the TS parser; 41 pages in the browser). V1: `lib/language.test.ts` (retired words, code names, HTTP paths, em-dashes, purpose ≤15 / description and tour step ≤25 words, capital and sentence case, UK spelling; replaces `wording.test.ts`) and `test_error_words.py` for raised API errors. V2: every flagged string rewritten; Run audit, Dataset audit, both comparisons and System status rebuilt in words with names from the API (`triggered_by_name`, `pipeline_name`, `dataset_names`; dataset audit names); run logs, audit/comparison notes, role descriptions, impact summaries and 29 error messages reworded at the source; Power BI/Tableau dialogs became "Send to"; raw-JSON "Try a change" and create-pipeline dialogs removed. V3: `service_governance/audit_words.py` turns all 165 audited routes into phrases and names the object; Audit Center outcome filter fixed (sent values no entry had). V4: 343 sub-12px sizes, 200 uppercase uses, 10 letter-spacings gone (`type-scale.test.ts`). V5: shared-ui Badge/Table/Tabs/Toast/StatTile/PageHeader/Overlay (+Modal drawer, compact EmptyState, icons); 33 tables, ~80 pills, 3 dialogs, 3 tab lists migrated (`components.test.ts`). V6: `docs/design-system.md`, light theme for demos. Measured: pages with sub-12px text 17→0, uppercase 16→0, raw ids 4→0, retired words 13→1 (vendor "endpoint" on Connectors). `npm run verify` green: 6,416 Python passed / 591 skipped, 783 web, ESLint/tsc/build clean. Pushed to `main`. **Next: A6 (trust, help and support for buyers).** |
| 2026-10-14 | `75332b59` | **Adoption-readiness A6 complete.** Spec W1–W8 measured first. W1: `service_enterprise/policy_view.py` on every read path (dataset page, versions, SQL, charts, pivots, dashboards and public links, Studio preview and joins, assistant, comparisons, downloads, deliveries); `test_policies_everywhere.py` fails all six with policies off. W2: `/help` from `docs/user/` (12 pages), Help menu Documentation / What's new / Contact support (`SUPPORT_CONTACT`, `GET /status/support`), "Read more" from every tab; `help.test.ts`. W3: `test_api_guide.py` runs the guide's 12 curl requests in order. W4: catalogue of 50 tested connectors, 161 "Available on request", tier words rewritten. W5: org network allow-lists (migration 0049), `TRUSTED_PROXY_HOPS`, session policy shown, AES-256-GCM files at rest + `platform-encrypt-storage`. W6: incidents and failed workflows to email/Slack, weekly summary (migration 0050). W7: `docs/security.md` rewritten, `scripts/check-oidc.py` (tested against a local provider), security headers. W8: D1–D20 hold; fixed SSO nonce never compared and token-chosen algorithm, unlayered CSS cancelling every button/link utility, unfilled workflow tasks reading "ready to run", Deliver task PostgreSQL-only, add-task buttons off-screen, ribbon on four pages, tab strip squeezed by side panels, malformed ids crashing, raw platform roles, audit middleware writing tests into the configured DB. `npm run verify` green: 6,455 Python passed / 591 skipped, 797 web. Live OIDC still unproven (no tenant); rate limiting is A7. **Next: A7.** |
| 2026-10-14 | `75332b59` | **Adoption-readiness A7 complete.** Spec X1–X10 measured first. X1 CI green (Linux notebook sandbox, dependency audit, image builds). X2 `STORAGE_BACKEND=s3` with encryption, two gateways on one bucket in CI (MinIO), Docker/Helm shared files. X3 `service_pipeline_runs/background.py` (queue, lease, progress, `on_fail`; migration 0053): uploads over 25MB, deliveries over 50,000 rows and database copies on the worker, pages follow them; upload limit 100MB. X4 per-task retries, pick up from where it failed (task fingerprints, migration 0054), runs per project. X5 rate limits (migration 0052). X6 OpenTelemetry behind `OTEL_ENABLED` (SQL spans from engine events). X7 p95 budgets in CI. X8 Playwright golden path and axe on every template in CI. X9 twelve limits on System status. X10 70 pages walked at two widths and the scale features rehearsed live. Found and fixed: pick-up refused for every run on PostgreSQL (`updated_at`, hidden by SQLite's clock); stalled or crashed workflow runs failed silently; a large read failing before it began left its dataset "being read"; failed reads showed no reason; worker memory limit equal to a 100MB read (now 4Gi); audit entries never recorded the correlation id; OTel SQLAlchemy refused SQLAlchemy 2.1 in CI; editors without a heading; toolbars and Trust's tabs hidden at laptop widths; 125 "(s)" counts and retired words in task messages. Measured: 99MB CSV through the page answered at once, rows shown in 23 s, worker peak 1.98GB; 1,003,735 rows to MySQL, request 106 ms, worker 21 s; worker killed mid-delivery, run failed and notified, picked up with the check reused and every row delivered. `npm run verify` green: 6,507 Python passed / 598 skipped, 806 web; with the connector servers and MinIO 6,536 / 569. Also: a run longer than its lease would have been failed by a second worker while working; `shared_python/lease.py` keeps it. Live OIDC still unproven. **Next: A8 (adoption pack).** |
| 2026-10-15 | `75332b59` | **Adoption-readiness A8 complete.** Spec Y1–Y8 measured first. A7 leftovers closed: 180s leases renewed from a side thread, Keycloak SSO live in CI, 200MB uploads in half the memory, a columnar read copy (checks on 4M rows 22s to 1s). Y1 signed webhooks with retries and a deliveries view (0056). Y2 project bundles (`api_gateway/bundles.py`). Y3 `clients/python` generated from OpenAPI, `pipewright` CLI. Y4 dashboard embeds: HS256 per-embed secrets, expiry, filters, `EMBED_ALLOWED_ORIGINS` frame-ancestors (0057); fixed every public viewer sharing one rate limit. Y5 metric alerts on every new version, sent after commit by the worker (0058); measures now recorded for uploads, imports and recipes, not only workflows. Y6 Activity stream (0059); audit log now names created and deleted things and API-token actors. Y7 `messages/en.json` + `t()`, dates/numbers only in `lib/format.ts` (en-GB). Y8 walked 77 pages at 1280 and 1024 with no problem after fixing: charts opening on a dataset too large to chart, the Assistant claiming "nothing looks like personal data" when it had not scanned, "quality rule" wording, "New secret" without asking, "Add an alert" for a channel, the guide overstating when checks open incidents. `npm run verify` green with no .env: 6,547 Python passed / 598 skipped, 827 web. **Next: A9.** |
| 2026-10-15 | `75332b59` | **Adoption-readiness A9 (launch gate) complete, except the owner's steps.** Spec Z1–Z7 measured first. Z1 demo runs its recipe and check, chart on the cleaned orders. Z2 `e2e/screenshots.mjs` → 8 pictures in `docs/user/images`, help shows images; found Title Case on Data health, "metric" wording, Checks default dataset, project making missing from its activity, alert form order. Z3 static docs site (`apps/web/scripts/build-docs-site.mjs`, tested), `docs-site.yml` manual, release notes 1.0.0, `docs/api/openapi.json`. Z4 following the documents on a clean machine found seven install faults, all fixed: no first administrator (now `first_run.py`), migration hook reading resources Helm makes later, no encryption key in the chart Secret, web image calling localhost:8000 (now `/api/v1`), API reference outside `/api` (now `/api/docs`), ingress 1MB body limit, Compose web without the gateway address and no root production settings file; release images now `v1.0.0` and `1.0.0`. CI `helm` job installs on kind by the guide's own commands (green); Compose rehearsed locally with Caddy. Z5 1.0.0 everywhere (`test_one_version.py`), `docs/positioning.md`, README opening. Z6 `docs/cold-user-sessions.md` + files. Z7 76 pages × 2 widths clean; verify green with no .env (6,553 Python / 598 skipped, 831 web); CI all green. **Waiting on the owner:** tag v1.0.0 (publishes images), set Pages to GitHub Actions and run docs-site.yml, run the five cold-user sessions. |
| 2026-10-15 | `75332b59` | **Phase 19 complete: data contracts (C1).** Plan `docs/plans/contracts-and-collaboration.md`, measured first (a recipe dropping a column others use ran and silently lost it, no schema change, no message; two saves of one recipe silently overwrote each other, kept for C2). `service_quality/data_contracts.py`, migration 0060: promises per column and per dataset, drafted from the data, versioned in words; enforced before storing by recipe runs, imports and stream saves (409 with the reasons, head kept), refused on rollback, recorded on erasure; problems once per source; overdue from the freshness promise; owner and followers told by the worker after commit; what relies on a dataset; Trust → Contracts, the dataset's contract page and editor, a chip, a Studio notice and a restore warning; activity kind, bundles, audit phrases, client, help. Found and fixed: every failed recipe run and import kept only "Waiting to start." in its log (a shared list never seen as changed); a PostgreSQL-only failure in the consumers query (contract tests now run on PostgreSQL too); six run-log and warning strings with retired words, now tested. Rehearsed live on the dev stack: the baseline recipe stopped and then resolved by a good run, an import from PostgreSQL stopped when its table lost a column, overdue opened and closed by the worker, the restore dialog refusing. 77 pages walked at 1280 and 1024, no problem; `npm run verify` green with no `.env`, 6,573 Python passed / 613 skipped, 837 web |
| 2026-10-15 | `75332b59` | **Phase 21 complete: working together (C2).** Measured first: two saves of one recipe silently overwrote each other; no presence; viewers could neither comment nor propose; recipe change requests had no "before" and could never be applied; "Changes need approval" could not be switched on; comments were flat; a dataset had no history of what happened. Shipped: recipe revisions with stale saves refused (409 naming who); a shared copy per recipe merged by a CRDT twinned in Python and TypeScript with shared fixtures and a three-person convergence test; per-person selective undo; presence with step focus; suggestions from any viewer, reviewed step by step in the Studio and Approvals (Accept/Decline), authors and reviewers told; the approval setting; threads with replies and cell anchors on dataset rows; a per-dataset feed on History (migration 0061). Found and fixed: key-order comparisons calling equal settings different (Bob's Studio stuck on "Unsaved changes"), a presence and shared-copy insert race (test fails 3/3 on old code), an endless Studio preview loop (found by the accessibility suite), a first save reopening as an empty recipe (found by the golden path), and CI's verify failing after C1 because create_all on PostgreSQL altered shared table definitions (fixed and pushed separately). Rehearsed live with three browsers: rename propagated in 842 ms, undo left the other's change, both showed Saved, a viewer's suggestion declined with a note that reached him. `npm run verify` green with no `.env`, 6,608 Python passed / 628 skipped, 848 web; golden path and accessibility suites green against the dev stack; every page walked at 1280 and 1024 with no problem |
| 2026-10-15 | `75332b59` | **Phase 20 complete: live data (D1).** Plan `docs/plans/live-data-and-performance.md`, measured first (a change committed during a poll was lost every time; no snapshot, no table "as it is now"; 20,000 changes took 41 polls, 20 minutes; saving rewrote every event; webhook retries stored twice; two kinds; the CDC test skipped on CI). Shipped `service_extraction/live/` (13 kinds: PostgreSQL, MySQL, MongoDB and SQL Server change capture; Kafka, Event Hubs, Kinesis, Pub/Sub, Pulsar, RabbitMQ, NATS, MQTT; webhooks), tables kept current by key after a first copy, positions committed with events and acknowledgements after, guarantees per kind, live recipes (`live/windows.py`: four window kinds, watermark, drop or restate; `live_recipes.py`: steps, lookup, exactly-once state), `platform-live-runner`, migration 0062, a Live feeds tab and page per feed, `docker-compose.live.yml`, `scripts/check-live-servers.py` and a `live` CI job. Faults found: the ::1 outbound refusal, sums counted once per measure, mixed lowest/highest, PostgreSQL deletes skipped, a foreign key broken on PostgreSQL (SQLite hid it), the Kinesis test server's repeats. Rehearsed live: first copy of 1,000 rows in 1s, changes in 6s, 20,000 in 8s, 120 Kafka messages summarised by minute, a webhook retry saved once, the add-feed and live-recipe forms in a browser. 76 pages walked at 1280 and 1024 with no problem. 6,684 Python passed, 667 skipped; 854 web. |
