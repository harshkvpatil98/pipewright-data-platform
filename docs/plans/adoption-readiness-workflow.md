# Adoption-Readiness Review and Workflow

**Date:** 2026-09-23 (after production-readiness P0–P9 closed).
**Purpose:** an unbiased, evidence-based review of Pipewright as a B2B product
a business would buy and use without a data engineer on call, followed by the
workflow that turns the findings into shipped work. The review looked at every
one of the 59 web routes in a running dev stack through a browser, plus two
read-only audits of the code (information architecture and copy; feature
coverage against what a data-platform buyer expects). Every number below was
measured, not estimated.

**Status:** **A0 and A1 done (2026-10-13); A2 to A6 done (2026-10-14); A7
(scale and reliability) is next.** Each phase's "What shipped" note below says what was delivered, what
was measured, and what moved to a later phase. `docs/HANDOFF.md` records the
session.

---

## Part I — The review

### 0. Verdict in one page

Pipewright is an unusually deep and unusually honest data engine wrapped in a
product surface that was assembled phase by phase and never redesigned as a
whole. The engine will impress an engineer who reads the code: 20 steps and
173 tools compile to one relational algebra with two proven backends; every
dataset is versioned, diffable and queryable as of a point in time; every
mutating request is audited; permissions are decided in one place; connector
maturity is disclosed on every card. The surface will lose a business user in
the first ten minutes: 31 navigation items across four sections and three
competing taxonomies, two words for most things and one word for several
things, five different tools that all "transform data", a Studio that puts
one action across three panels and 24 ribbon controls at 10.5px, page copy
written as essays about why a feature exists, and error banners that appear
before the user has done anything.

**What is strong (keep, and sell):**

- The engine: IR, pushdown, versioning and replay, lineage, governance, audit.
- Honesty as a design principle: tiers, null-not-zero, stated refusals. No
  competitor does this and it is a genuine trust asset for B2B.
- Governance depth for the size of the team: row/column security with
  simulation, erasure reconciled with immutable versions, retention, Audit
  Center, MFA, scoped tokens, tenancy.
- Operability: Helm, compose, backup drill, runtime heartbeats, status page.
- Test discipline: 6,870 Python and 692 web tests, CI against real databases.

**What blocks adoption (in order of damage):**

1. **Navigation and vocabulary.** A first-time user cannot tell Sources from
   Connections from Connectors from "Register source", nor Studio from
   Pipelines from Table editor from Workbench from Notebooks. Dashboards and
   the pipelines list are not in the navigation at all.
2. **The Studio is a workbench, not a product.** Three panels plus a ribbon
   plus a plan strip plus a status bar for one job; the settings for the step
   you just added open on the far side of the screen; 451 uses of sub-12px
   text across the app, 28 of them in Studio alone.
3. **It is not yet an integration platform.** 211 connectors are a catalogue;
   only PostgreSQL, MySQL and SQLite can create a dataset. The only real load
   target is PostgreSQL. "Migrate Postgres to Snowflake" is not possible in
   either direction. A buyer who reads "211 connectors" and then cannot pull
   from HubSpot will feel misled, however honest the tier badge is.
4. **Copy is written for the author, not the buyer.** Page subtitles average
   20 words and explain rationale; the Schedules page mentions DB leases,
   `next_run_at` and cron slots; the Notebooks page quotes `RLIMIT_AS`.
5. **No customer-facing help.** No user guide, no in-app docs, an API
   reference that returns a 500, a security document that says SSO and MFA are
   "planned" when they shipped, and reviewer/recruiter pages (`/demo`,
   `/case-study`) still reachable in the product.
6. **First-run friction.** Empty states without actions (Studio with no
   datasets has no button), five zero-value stat tiles above the checklist on
   a brand-new project, errors shown before any input (Charts, Notebooks,
   Workflows), 70 unread notifications from routine runs.

### 1. Scorecard

Same dimensions as the 2026-09-23 adoption review that drove P0–P9, re-scored
after P0–P9 shipped, plus the dimensions this review added. Scores are out of
10; "evidence" is what moved or did not move them.

| Dimension | Score | Evidence |
|---|---|---|
| Core data engine | 9 | IR is the only executor, pushdown wired into runs, rewrites proven differentially, versions/replay/AS OF live. Remaining: lineage still from `columns.py`, no window functions. |
| Governance and audit | 8.5 | Row/column policies with simulation, erasure modes, retention, Audit Center export, PII detection. Remaining: audit records every chart preview as an event; incidents never leave the app. |
| Identity and access | 7 | MFA (RFC vectors), OIDC with PKCE/JWKS, scoped tokens, tenancy — but SSO never run against a real IdP, no SAML, no inbound SCIM, no per-object permissions. |
| Deployability | 7 | Helm, prod compose with TLS, GHCR images, backup drill. Remaining: artifacts on local disk with no PVC or object store, so gateways cannot scale out. |
| Operational trust | 7.5 | Heartbeats, stalled-queue incidents, status page, correlation ids. Remaining: no tracing, no rate limiting, workflow runs never retried. |
| Feature coverage (transform/govern/observe) | 8 | Steps, tools, quality rules, anomalies, drift, incidents, catalog, metrics layer, dashboards, reports. |
| **Feature coverage (integrate/migrate)** | **3.5** | Datasets come from files and three SQL engines only; one real destination; no upsert; no migration or DDL tooling; CDC is Postgres-only. |
| BI and consumption | 6.5 | 9 chart types, dashboards with filters and share links, PDF reports, metrics. No embeds, drill-down, metric alerts, caching; every chart recomputes over the artifact. |
| Collaboration | 6 | Comments with mentions on four object types, change requests. No activity feed, no object-level sharing. |
| Visual design | 6 | Coherent tokens, light and dark, a real design language. Undermined by inconsistency: 24 eyebrow labels, 3 status-badge implementations, 2 modals plus 6 hand-rolled dialogs, 27 hand-rolled tables, uppercase pill buttons beside normal buttons on the same row. |
| **Information architecture and navigation** | **3.5** | 31 rail items, three taxonomies (rail / Workspace menu / eyebrows), Dashboards and the pipelines list unreachable from the rail, "People" twice, "Sources" opens "Extraction". |
| **Studio usability** | **4.5** | Powerful, but ribbon 24 controls at 10.5px, one action spread across ribbon, step rail and inspector, no H1 or description, header click silently adds a Sort step, empty state without an action. |
| Ease of first use | 4.5 | Checklist and tours exist and are good; everything around them (zeros above the fold, form-first pages, errors before input, two "sources") undoes them. |
| Language fit | 4 | P0's language pass reached the newer pages; older pages (Schedules, Run audit, Dataset audit, Testing lab, Destinations) still speak in table and column names. |
| **Documentation and support** | **3** | 22 docs, none for end users; two describe the pre-Studio flow; the only doc linked from the UI is `security.md`, which is wrong about SSO/MFA; OpenAPI generation fails. |
| **Honesty and trust signalling** | 9 | The single best thing about the product. Keep it, but present it so it reassures rather than alarms (see A6). |

### 2. Navigation and information architecture

Evidence is from `apps/web/src/components/shell/app-frame.tsx`,
`features/projects/components/workspace-menu.tsx`, and the route inventory.

- **F-IA-1 — Too many top-level destinations.** With a project open an admin
  sees 31 rail items: Workspace 4, Project 20, Administration 3, Platform 4.
  The project section alone lists Overview, Sources, Studio, Table editor,
  SQL workbench, Notebooks, Workflows, Data quality, Charts, Metrics, Catalog,
  Reports, Schema drift, Incidents, People, Changes, Audit log, Governance,
  Schedules, Destinations — at 1491×812 the last six are below the fold. A
  business user needs five or six destinations, each with tabs.
- **F-IA-2 — Three taxonomies for one product.** The rail groups by
  Workspace/Project/Administration/Platform. The "WORKSPACE ›" pill on the
  project overview opens a second menu grouped Build/Govern/Operate/Publish
  with different labels ("Extraction" where the rail says "Sources") and four
  destinations the rail omits. Page eyebrows are a third grouping with 24
  distinct labels (Ingest, Govern, Trust, Team, Enterprise, Consumption,
  Reporting, Semantic layer, Reach, Operate, Testing lab, Intelligence …). The
  welcome tour describes a fourth ("each icon is a stage of the pipeline …
  sources on top, delivery at the bottom") that the rail does not follow.
- **F-IA-3 — Core pages missing from navigation.** `/dashboards` (the thing a
  BI user wants most) is reachable only from the Workspace menu and from a
  dashboard's own "All dashboards" pill; the Charts page says "Drop these
  onto a dashboard" with no link. The project pipelines list is reachable
  from nowhere in navigation. BI connections, Notification targets and Saved
  tests are Workspace-menu-only.
- **F-IA-4 — Same word, different things; different words, same thing.**
  "People" appears twice (project members, platform users) with different
  icons. Rail "Sources" opens a page titled "Extraction"; "Reports" opens
  "Scheduled reports"; "Changes" opens "Changes awaiting review"; "Audit log"
  (project) vs "Audit Center" (admin) vs `/audits`. "Metrics" is both the
  semantic layer and the dataset-health page. "Workspace" means the whole
  platform in the rail and the current project in the menu and eyebrows.
- **F-IA-5 — Two unrelated "sources".** The project overview's "Connect a
  source" opens a v1 "Register source" modal (CSV/Excel/JSON/API/PostgreSQL/S3,
  status, "Configuration JSON") that writes a metadata registry nobody reads
  downstream; the overview's "Sources 0" stat counts those, while the rail's
  "Sources" page manages extraction connections and jobs. A user who connects
  a database sees "Sources: 0" on the overview.
- **F-IA-6 — Five ways to transform data, unexplained.** Studio (grid +
  ribbon), the legacy pipeline editor (form UI reached from the dataset page's
  primary button "Create Pipeline" — the dataset page never links to Studio),
  Table editor (write-back to live tables), SQL workbench, Notebooks. The same
  object is called steps, recipe and pipeline within one screen. Workflow
  nodes are also "steps". The pipeline editor cannot open Studio-made
  pipelines ("This step type is not supported in the editor" on
  `derive_column`).
- **F-IA-7 — Icons do not discriminate.** 37 glyphs, but `book` is used for
  four rail items, `grid` for three, `shield` for three, `activity` for three.
- **F-IA-8 — Internal pages ship in the product.** `/demo` ("Built for
  reviewers and demos — not a marketing site", links to repository docs),
  `/case-study`, `/testing` ("Saved statistical tests"), all reachable; the
  Help menu's "Guided walkthrough" goes to `/demo`. No `not-found.tsx` or
  `error.tsx` exists anywhere.
- **F-IA-9 — Chrome that is mostly empty.** The status bar is rendered on
  every page but only 8 of 54 in-app pages pass anything to it. The command
  palette is good but is the only place some pages can be found.

### 3. The Studio

Evidence: `features/studio/studio-page.tsx` (1,040 lines) and its components,
plus the browser session.

- **F-ST-1 — One action, three regions.** Adding a filter means: ribbon (top)
  → a step appears in the rail (left) → its settings open in the inspector
  (right, 300px away) → a banner in the middle says "Finish setting up this
  step". The eye travels the whole width for a single task. Compare: the
  right-click column menu, which puts the tool where the data is — that is
  the model the whole Studio should follow.
- **F-ST-2 — Density without hierarchy.** Ribbon: 24 controls in 6 groups,
  labels at 10.5px, group captions at 10px uppercase, overflow fade at the
  right edge. Applied-steps header 11px, count pill 10px, step deltas 10.5px,
  plan strip 12/11.5/11px, ROWS/COLUMNS chips 10px labels. Across the app
  there are 451 uses of six font sizes below 12px (9, 9.5, 10, 10.5, 11,
  11.5px). Nothing is emphasised because everything is small.
- **F-ST-3 — No frame.** Studio has no H1, no description, no "what is this
  and what do I do first" beyond a 12px line in the left rail and an
  auto-tour. The library of 173 tools sits behind one "All tools (173)"
  button while the ribbon shows the 20 built-ins; a user has no way to know
  the difference or why both exist.
- **F-ST-4 — Surprising side effects.** A single click on a column header
  adds a Sort step to the pipeline (by design — "a header sort is a STEP"),
  silently enabling Save. A right-click opened the column menu *and* added
  the sort. Users expect a header click to sort the view, not to edit the
  recipe.
- **F-ST-5 — Dead ends.** With no datasets the canvas shows "No datasets in
  this project yet — Upload a file or run an extraction job" with no button,
  and every ribbon control is disabled. The YAML panel accepts only
  `step:`/`with:` and rejects the `type:`/`config:` spelling used by the API
  (the placeholder on the Sources page used the wrong one until today).
- **F-ST-6 — The plan strip speaks to engineers.** "All steps will run in
  Pipewright — a stored file source cannot run them at the source" is the
  first line a user reads above their data; "each rule is an algebraic
  identity the differential suite checks on both engines" is in the expanded
  strip. True, valuable to some, wrong as the default voice.
- **F-ST-7 — Preview vs run is unclear.** "Preview current", "Computing
  preview", "Showing the last result that ran", "Recomputing" — four states
  with no explanation of what is previewed (50 rows) versus what a run does
  (writes a new dataset version).

### 4. Pages, forms, copy, visual system

- **F-UX-1 — Form-first pages.** Sources, Workflows, Data quality, Reports,
  People (project) and Extraction jobs render a full create form at the top of
  the page whether or not the user wants one; Sources shows 26 inputs on
  load. The pattern elsewhere is a button that opens a modal. Pick one (the
  modal), and make the list the page.
- **F-UX-2 — Stat tiles as decoration.** Projects, project overview,
  Metrics, Dashboards, Schema drift, Incidents, Catalog, Connectors, People,
  Organisations, Notifications and the dataset page each open with three to
  five large number tiles ("PROJECTS 49", "REGISTERED ASSETS 62", "RUNS 10 —
  Persisted orchestration and ingestion history for this project"). On a new
  project they are five zeros above the one thing that matters (the
  checklist). Tiles should appear only when the number drives an action.
- **F-UX-3 — Errors before input.** Charts opens with a red banner ("'id' has
  no numeric values, so 'sum' cannot be computed from it") because defaults
  pick the first column; a new Notebook opens with "Cell 1: This cell is
  empty."; a new Workflow shows "A workflow needs at least one node." and
  keeps showing it after a node is added; the pipeline editor shows "Pipeline
  name is required" before typing.
- **F-UX-4 — Copy density and voice.** 362 help strings measured: mean 13.9
  words, page subtitles mean 20, tours 26, max 46. Rationale-first
  ("The chore this removes: …", "because people remember a column far more
  often than …") reads as a blog, not a product. Twelve of 43 subtitles use
  em-dashes. Older pages use a system register ("Persisted orchestration and
  ingestion history", "Stored artifact size in local development storage",
  "Read-only summary from persisted run, summary_json, and logs_json",
  "Triggered by 533ba9d5-… (you)"). Jargon that reached the UI: watermark
  (11), cron slot, DB lease, `next_run_at`, `summary_json`, `schema_json`,
  `RLIMIT_AS`, artifact, materialisation, tenant, upsert, semantic version,
  "algebraic identity", "Hyper extract".
- **F-UX-5 — Inconsistent components.** Two identical `Button`
  implementations (one unused), two identical `Modal` implementations plus six
  hand-rolled `role="dialog"` overlays, three `StatusBadge` implementations
  (two unused), 27 hand-rolled `<table>`s and no shared table, 63 inline pill
  variants with 10 letter-spacing values, 141 raw `<button>` elements beside
  255 `<Button>`s. On one row a dashboard shows "OPEN" (uppercase pill),
  "Share" (primary) and "Rename" (secondary). The dataset page has ten action
  buttons in its header, three of them "Publish to …".
- **F-UX-6 — Spelling and casing drift.** organis-/organiz-, materialis-/
  materializ-, catalog/catalogue, "Audit Center" beside "Audit log", "Testing
  Lab" beside "Testing lab", "View Audit"/"Create Pipeline" beside "Lineage"/
  "Rename".
- **F-UX-7 — Developer detail on user pages.** Project audit log and Audit
  Center show raw `POST /api/v1/projects/…/charts/preview` paths and HTTP
  status codes to project members, and record every chart or pipeline
  preview as an audit event. Run audit shows raw UUIDs for run and actor.
  Home's "Platform health" lists internal module names (observability,
  postgres, auth, projects, access). System status shows ISO timestamps with
  microseconds and "Runtime id env: not set".
- **F-UX-8 — Datasets multiply.** Each extraction run creates a new dataset,
  so the Datasets and Catalog pages list "Active projects, shaped at source"
  five times with identical names, and the type column says "csv" for a
  database extraction. A business user reads this as duplication.
- **F-UX-9 — Notifications are a firehose.** Every manual run, every
  scheduled run and every report generates an in-app notification; the dev
  account shows 70 unread. There is no grouping, no digest, no per-type
  preference.
- **F-UX-10 — Theme.** Default is "system", so a buyer on a light-mode laptop
  gets the cleaner, more professional light theme; the dark theme is fine for
  operators. Chart bars render in a default blue that is not in the token
  palette (`--series-*` exists). Small, but visible on the first dashboard.
- **F-UX-11 — Accessibility and responsiveness.** No axe or a11y test; 151
  `aria-*` attributes; no browser-support statement; the shell and Studio
  have no responsive breakpoints (desktop only — acceptable, but state it).

### 5. Defects found during the review

Severity: P1 blocks a buyer's evaluation, P2 embarrasses, P3 polish.

| # | Sev | Defect | Evidence |
|---|---|---|---|
| D1 | P1 | OpenAPI generation fails; `/api/v1/openapi.json` returns 500 (`PydanticUserError … ForwardRef('Response')`), so `/docs` and `/redoc` cannot load | live `curl`; candidates are `-> Response` annotations in access, datasets, enterprise, extraction, observability, pipeline-runs routers |
| D2 | P1 | Dashboards and the project pipelines list are not in the rail; Charts page says "Drop these onto a dashboard" with no link | `app-frame.tsx:65-84` |
| D3 | P1 | Pipeline editor cannot edit Studio-made pipelines ("This step type is not supported in the editor." on `derive_column`) | `/projects/…/pipelines/e15ed60a…` |
| D4 | P2 | Dataset page renders parser findings as `[object Object],[object Object]` | `dataset-detail-page.tsx:432` uses `String(value)` on arrays of objects |
| D5 | P2 | PII detector flags a date column as "Phone number, 100% of values look like it" | `pii.py` phone pattern `^\+?[\d\s().-]{7,20}$` matches `1990-06-15`; `_valid_phone` returns True; verified with `scan_dataset` |
| D6 | P2 | Charts page opens with an error banner before any input | defaults pick `id` + `sum` |
| D7 | P2 | New notebook shows "Cell 1: This cell is empty." on load; banner quotes `RLIMIT_AS` | `/notebooks` |
| D8 | P2 | Workflow editor keeps "A workflow needs at least one node." after a node is added; status bar says "Graph has errors" | live |
| D9 | P2 | Schedules page copy is v1 developer text (`next_run_at`, DB lease, cron slot) and the page's tour auto-opens over it | `schedules-page.tsx:349,387` |
| D10 | P2 | `/demo`, `/case-study`, `/testing` reachable; `/demo` is the Help menu's "Guided walkthrough" | route inventory |
| D11 | P2 | `docs/security.md` (the only doc linked from the UI) says SSO and MFA are planned; both shipped | `settings-page.tsx` "Security overview →" |
| D12 | P2 | Two "sources" (v1 registry vs extraction connections); overview shows "Sources 0" with a connected database | `project-detail-page.tsx:122`, `service-sources` |
| D13 | P2 | Extraction creates a dataset per run; Datasets/Catalog list identical names; type shows "csv" for database data | known gap, now a user-facing defect |
| D14 | P3 | Connectors page tier legend squeezes "Never executed against a real instance…" into a 70px column | `/connectors` |
| D15 | P3 | Governance "Run now" wraps onto two lines; dashboard row mixes OPEN pill with normal buttons | `/governance`, `/dashboards` |
| D16 | P3 | Avatar shows "?" on System status, Demo and Case study pages | pages skip `requireCurrentUser` |
| D17 | P3 | Settings "Layout" copy says the default rail is collapsed; it is expanded | `settings-page.tsx`, `app-frame.tsx:127` |
| D18 | P3 | Welcome tour describes a rail order and a Sources ribbon that do not exist | `tours.ts:24,30,48` |
| D19 | P3 | Audit log stores an entry for every preview request; noise drowns real changes | `/audit-log` |
| D20 | P3 | No `not-found.tsx`/`error.tsx`; a bad URL renders the framework default | `apps/web/src/app` |

### 6. Coverage by domain (what exists, what a buyer will ask for)

Measured by walking the FastAPI route table (329 operations, 35 tags),
importing the connector and tool registries, and reading the services.

| Domain | Exists and solid | Partial | Absent (buyers ask) |
|---|---|---|---|
| Sources | Files (15 formats, sniffing, resumable upload); PostgreSQL/MySQL/SQLite extraction with watermarks and pushdown; schema drift; secret references | 211-connector catalogue: 50 tested in CI, 161 never executed, 0 verified live; SDK connectors are not wired to ingestion (only `test`/`discover`); Postgres CDC + webhooks | SaaS, API or warehouse sources that land data; MySQL/Mongo/SQL Server CDC; queues |
| Destinations and migration | Publish to PostgreSQL (replace/append) by hand, schedule or workflow; write-back to live tables | Power BI push, Tableau Hyper (unit-tested); S3/local file drop via workflow node; S3/local "destinations" saved but never written to | Snowflake/BigQuery/Redshift/MySQL/SQL Server/GCS/Azure targets; upsert/merge loads; database-to-database migration; schema (DDL) migration; dataset download API; SaaS reverse ETL |
| Transformation | 20 steps + 173 tools; formula engine; IR with pushdown; joins/unions; lineage; recipe YAML | SQL and Python via workbench/notebooks (Python off on macOS); versioning/promotion for workflows only | Window functions; SQL/Python steps inside pipelines; dbt-style models with refs and tests; pipeline parameters; templates |
| Pipelines and workflows | DAG editor with 7 node types; cron with timezone; backfills; run diff; leased multi-worker queue; change-request approvals | Schedule retries (workflow runs never retried); on-failure edges | Event/webhook/dataset-updated triggers; concurrency limits; run SLAs; git sync / CI integration; external alerts on workflow failure |
| Quality and observability | 8 rule types with quarantine; freshness SLAs; MAD anomaly detection; incidents with lifecycle; usage metering | Drift on uploads/extraction/connector schemas | Incident delivery to email/Slack; expectation suites as code; health dashboards per owner |
| Governance and security | RBAC at one choke point; audit middleware and export; row/column policies with simulation; PII detection and masking; retention and erasure; tenancy; TOTP MFA; scoped API tokens | OIDC (never run against a real IdP); outbound SCIM CLI; catalog, glossary, certification | SAML; inbound SCIM; per-object permissions; access requests; data contracts; IP allowlists; artifact encryption at rest; service accounts |
| BI | 9 chart types; dashboards with filters, refresh and public links; scheduled reports in 4 formats; metrics layer; SQL workbench; notebooks | In-process pandas with row caps | Embeds; drill-down; metric alerts; caching |
| Collaboration | Comments with mentions on datasets, pipelines, dashboards, change requests | Change-request review | Activity feed; object-level sharing; co-editing |
| Platform | Compose, Helm, images, migrate-before-serve, backup drill, Prometheus counts, status | HPA for stateless tiers | Object-storage backend and PVC; tracing; inbound rate limiting; PITR |
| Integration | OpenAPI (currently broken, D1); scoped tokens; connector SDK with conformance suite | Slack/email targets for 6 event types | Generic outbound webhooks; user CLI; SDK; Terraform; runtime plugins; project import/export |
| Documentation | Operator docs (install, deploy, ops, DR, identity, troubleshooting); generated tool reference; BRD | Feature guide and demo guide (describe the pre-Studio flow) | End-user guide; in-app help; release notes; API guide; a docs site |

Two journeys a buyer will try on day one:

- "Sync our Postgres orders table to our warehouse nightly." Possible only
  if the warehouse is PostgreSQL; each run rewrites the whole table.
- "Pull HubSpot contacts, clean them, load to Snowflake." Not possible at
  either end today.

### 7. Trust and B2B readiness

- **Connector honesty is right; its presentation is wrong.** "211 connectors
  · 161 unverified" on the Connectors page, with a wrapped legend, reads as
  a warning. Present the 50 tested connectors as the catalogue, and the rest
  as "available on request, validated with you" (see A6).
- **Security story.** Strong controls, one wrong document, one unproven leg
  (SSO). A buyer's security questionnaire will ask for SSO proof, encryption
  at rest for data files, IP allow-listing and session policy — three of the
  four are absent.
- **Scale story.** Pandas in the gateway process with a 512 MiB default pod
  limit and a 1M-row extraction default; artifacts on local disk. Truthful
  positioning today: departmental data (millions of rows), single-node or
  shared-volume deployment. Say so, or fix it (A7).
- **Support story.** No docs site, no release notes, no support link in the
  Help menu, no changelog. A B2B buyer needs all four before procurement.

---

## Part II — The workflow

### Operating protocol

The protocol from `docs/plans/production-readiness-workflow.md` applies
unchanged: read first; implement completely; push further; `npm run verify`
green with zero warnings; every touched surface verified live in the browser;
HANDOFF ledger and session log updated; commit and push in the repository's
style with author/committer `harshkvpatil98 <harshkvpatil@gmail.com>` and no
AI attribution; never regress the honesty invariants.

Two additions for this sequence:

1. **Design before code for A0–A3.** Each of those phases starts by writing
   the spec into this file (IA tree, page templates, Studio layout, voice
   guide) and gets the owner's "continue" on the spec before implementation.
   A redesign done page by page without a written target reproduces the
   problem this review found.
2. **A usability check per phase.** Each phase's *Verify in browser* block
   includes a "cold user" task run: a scripted task performed from a fresh
   browser profile and a brand-new project, timed and recorded in the
   session log (clicks, wrong turns, time to done). Phases A1–A3 must move
   those numbers.

### Scorecard → target map

| Dimension | Now | Target | Reached by |
|---|---|---|---|
| Information architecture and navigation | 3.5 | 9 | A0, A1 |
| Ease of first use | 4.5 | 9 | A1, A2 |
| Studio usability | 4.5 | 9 | A3 |
| Language fit | 4 | 9.5 | A5 (with a lint that keeps it) |
| Visual design and consistency | 6 | 9 | A5 |
| Feature coverage (integrate/migrate) | 3.5 | 8 | A4 |
| Documentation and support | 3 | 9 | A6 |
| Identity and security proof | 7 | 9 | A6, A7 |
| Deployability and scale | 7 | 9 | A7 |
| BI and collaboration | 6.5 | 8.5 | A8 |

### Quick wins (do inside A0, they need no design decision)

Fix D1, D4, D5, D6, D7, D8, D11, D14, D15, D16, D17, D19 and D20; remove
`/demo`, `/case-study` and `/testing` from the product (keep the demo seeder
behind the Home empty state); delete the two dead `Button`/`StatusBadge`
duplicates and `PlaceholderPage`; add `not-found.tsx` and `error.tsx`; stop
auditing preview requests; render chart series from `--series-*` tokens;
make the Notebooks banner say "Python cells are off on this server" and move
the reason to a tooltip.

---

## A0 — Product definition and IA reset *(done 2026-10-13)*

**Why.** Every finding in §2 comes from the absence of one agreed model of
what the product is and how it is organised. This phase writes that model
down; nothing else can be designed without it.

**Deliver (documents in this file, plus the quick wins above):**

1. **Personas and jobs.** Three: the *data owner* (business analyst who
   connects, cleans, checks and shares), the *operator* (keeps it running),
   the *administrator* (people, security, tenancy). Every page names its
   primary persona.
2. **One product model and vocabulary.** A glossary of at most 20 nouns with
   one meaning each, and the words retired. Proposed: **Source** (anything
   data comes from: file, database, SaaS, stream — replaces registered
   source, connection, connector-in-use, extraction), **Connector** (a type
   of source in the catalogue), **Dataset**, **Recipe** (the ordered steps
   that make a dataset — replaces pipeline, transformation pipeline, applied
   steps), **Run**, **Workflow** (a graph of runs), **Schedule**, **Check**
   (quality rule), **Incident**, **Destination**, **Dashboard/Chart/Report**,
   **Metric**, **Policy**, **Change request**, **Version**. "Step" is used
   only inside a recipe; workflow items are "tasks".
3. **The navigation tree.** One taxonomy, six top-level areas with tabs,
   replacing the rail's 20 project items, the Workspace menu and the eyebrows:
   - **Home** (workspace overview and what needs attention)
   - **Data** — Sources · Datasets · Catalog · Versions
   - **Build** — Studio (recipes) · SQL · Notebooks · Table editor
   - **Automate** — Workflows · Schedules · Runs · Destinations
   - **Trust** — Checks (quality) · Incidents · Drift · Lineage · Policies ·
     Audit
   - **Share** — Dashboards · Charts · Reports · Metrics
   - **Admin** (platform admins) — People · Organisations · Connectors ·
     System status · Settings
   Project is a switcher in the top bar, not a section of the rail.
4. **Page templates.** Four: *List page* (title, one-line purpose, primary
   action, filters, table/cards, empty state with action), *Detail page*
   (header with identity + at most three actions + overflow menu, tabs for
   the rest), *Editor page* (Studio, SQL, Notebook, Workflow: canvas-first,
   one collapsible side panel, no ribbon groups below 12px), *Settings page*.
   Stat tiles are allowed only on Home and Trust.
5. **Design principles (five lines, enforced in review):** the data is the
   page; one primary action per screen; no error before input; no word a
   business user would have to look up; every empty state says what to do
   next and offers the button.
6. **Voice guide** for A5: sentence case, ≤ 15 words per page purpose line,
   no rationale in help text (link to docs instead), no field or table names,
   UK spelling throughout (the codebase already leans that way), no em-dashes
   in UI strings.

**Verify in browser.** Quick wins visible: `/docs` renders the API reference,
Charts and Notebooks open without an error, Workflow banner clears, dataset
page shows parser findings as text, `/demo` returns not-found with a designed
page, chart colours match the palette.

**Exit gate.** Spec sections 1–6 written here and approved with "continue";
quick wins shipped; `npm run verify` green.

### A0 specification (written 2026-10-13)

The owner's instruction for this session was to complete the next two phases
(A0 and A1) with the user experience as the priority, so this specification
was written and then implemented in the same session rather than waiting for
a separate "continue". Where it departs from the proposal above, it says why.

#### S1. Personas and the jobs they come to do

| Persona | Who | Comes to | Lives in |
|---|---|---|---|
| **Data owner** (primary) | An analyst or team lead who owns a subject: sales, stock, customers. Not an engineer. | Bring data in, clean it, check it, share it. | Data, Build, Share |
| **Operator** | Whoever keeps the numbers arriving on time. Often the same person on a different day. | Schedule work, watch runs, act on incidents, deliver data out. | Automate, Trust |
| **Administrator** | IT or the platform owner. | Invite people, set roles and policies, prove what happened. | Admin, a project's People and Settings, Trust → Policies and Audit log |

Every page has one primary persona, recorded beside it in
`apps/web/src/lib/navigation.ts`. When a page's copy has to choose who it is
talking to, it talks to that persona.

#### S2. Vocabulary: eighteen nouns, one meaning each

| Word | Means | Retired from the UI |
|---|---|---|
| **Project** | A space for one team or subject. Everything else lives inside one. | "workspace" for a project |
| **Source** | Where data comes from: an uploaded file, a database connection or a live feed. | registered source, extraction, ingestion, "connection" as a page name |
| **Connector** | A kind of source in the catalogue (PostgreSQL, Stripe, S3). | connector-in-use |
| **Dataset** | A table of data in a project. | artifact, materialisation |
| **Version** | One saved state of a dataset; every change makes a new one. | snapshot (in UI copy) |
| **Recipe** | The ordered **steps** that turn one dataset into another. "Step" is used only inside a recipe. | pipeline, transformation pipeline, applied steps |
| **Run** | One go of a recipe, an import, a workflow or a check. | job run, orchestration run, pipeline run |
| **Workflow** | **Tasks** that run in order, by hand or on a schedule. | node, DAG, graph (in UI copy) |
| **Schedule** | When something runs by itself. | cron slot, trigger (as a noun) |
| **Check** | A rule the data must pass. | data quality rule, expectation |
| **Incident** | Something that went wrong and needs a person. | alert (for incidents) |
| **Schema change** | A column added, removed or retyped at a source. | schema drift, drift event |
| **Destination** | Where data is delivered: a database, a file store, a BI tool. | publish target, BI connection (as a page name) |
| **Dashboard · Chart · Report** | A page of charts · a saved question drawn as a picture · a file sent on a schedule. | consumption, reporting |
| **Metric** | A number defined once and reused everywhere. | semantic layer, measure definition |
| **Policy** | A rule about who sees which rows and columns, or how long data is kept. | governance (as a page name) |
| **Change request** | An edit waiting for someone's approval. The tab that lists them is **Approvals**. | changes awaiting review |
| **Member** | A person with access to a project, with a role: viewer, operator, editor or admin. | "People" meaning two different pages |

Also retired: the 24 eyebrow labels (Consumption, Reach, Intelligence,
Enterprise, Testing lab, Ingest…), "watermark" (say "loaded up to"), "upsert"
(say "update matching rows"), "tenant" (say "organisation").

#### S3. The navigation tree

**One sentence:** the rail is the open project; the top bar is everything
around it.

**Top bar, left to right.** The product mark (goes to the workspace Home) ·
the project switcher (the open project's name; its menu lists projects, the
project's overview, people and settings, all projects, and a new project) ·
the breadcrumb (Area › Tab › object) · Search (⌘K) · theme · notifications ·
Help (tour, keyboard shortcuts, API reference, system status) · account
(settings, sign out).

**Rail: seven items, each a project area with tabs.** With no project open,
an area link opens the project chooser rather than a dead page.

| Area | Tabs | Replaces |
|---|---|---|
| **Overview** | Overview · People · Alerts · Settings | project page + its five tiles, Workspace menu, "People" (project), notification targets, the project settings panel |
| **Data** | Sources · Datasets · Catalog | Sources/"Extraction", the v1 "Register source" registry, the overview's datasets tab |
| **Build** | Studio · Recipes · SQL · Notebooks · Table editor | five rail items and the unlisted pipelines list |
| **Automate** | Workflows · Schedules · Runs · Destinations · BI tools | Workflows, Schedules, Destinations, BI connections (Workspace-menu only before) and the overview's runs tab |
| **Trust** | Checks · Comparisons · Incidents · Schema changes · Policies · Approvals · Audit log | Data quality, Saved tests (Workspace-menu only before), Incidents, Schema drift, Governance, Changes, Audit log |
| **Share** | Dashboards · Charts · Reports · Metrics | Charts, Metrics, Reports and Dashboards (not in the rail before) |
| **Admin** *(platform admins only)* | Accounts · Organisations · Audit (all projects) · Connectors · System status | the Administration and Platform rail sections ("Accounts" so it is not a second "People") |

**Workspace pages** sit outside the rail, reached from the mark, the switcher
and Search: Home `/` with tabs Home · Projects · Runs · Datasets (the
cross-project views), plus Notifications, personal Settings, the Connectors
catalogue and System status (all also in Help, Admin or the account menu).

Departures from the proposal: **Versions** is not a tab because versions
belong to one dataset and live on its page; **Lineage** likewise. **Home**
became two things the proposal folded together: the workspace Home (the
mark) and the project **Overview** (the first rail item), because the rail is
the project. **Comparisons** (saved statistical tests) joins Trust so no list
page is left reachable only by a deep link.

**URLs follow the words where they disagreed:** `/extraction` → `/sources`,
`/data-quality` → `/checks`; every old address redirects permanently.
`/pipelines` keeps its address until A3 makes one recipe editor.

#### S4. Page templates

1. **List page** — title; one purpose line; one primary action at the top
   right; filters if the list can grow; the list; an empty state with a verb
   and its button. Create forms open in a dialog, not at the top of the page.
2. **Detail page** — identity (name, kind, status) and at most three actions,
   the rest in an overflow menu; sections or tabs below.
3. **Editor page** — Studio, SQL, Notebook, Workflow: the canvas is the page;
   one collapsible side panel; nothing below 12px.
4. **Settings page** — sections with a title and a one-line description, each
   saving on its own.

Every page in an area shows the area's tabs, so where you are and what sits
beside it is always on screen. Stat tiles appear only where the number
drives an action (workspace Home and Trust); a page whose tiles would all be
zero shows its empty state instead.

#### S5. Design principles (enforced in review)

1. **The data is the page.** Chrome earns its space or goes.
2. **One primary action per screen.**
3. **No error before input.** A page opens neutral; problems appear after the
   user has done something.
4. **No word a business user would have to look up.** S2 is the dictionary.
5. **Every empty state says what to do next and offers the button.**

#### S6. Voice guide (applied fully in A5; new copy follows it now)

- Sentence case everywhere: titles, buttons, tabs. No uppercase pills.
- A page's purpose line is one sentence of at most 15 words.
- Say what the thing does, not why it was built; rationale goes in the docs.
- No field, table or column names from the code (`next_run_at`,
  `summary_json`, `RLIMIT_AS`), no HTTP verbs, no raw identifiers.
- UK spelling (organisation, catalogue in prose; "Catalog" stays as the tab
  name already in use).
- No em-dashes in UI strings; a full stop or a comma does the job.
- Errors say what happened and what to do next, in that order.

---

## A1 — Navigation and shell *(done 2026-10-13)*

**Why.** F-IA-1..9, D2, D10, D12.

**Deliver.**

- New rail per A0 §3 (six areas, tabs inside each), collapsed-by-default
  icons with labels on hover for operators, expanded for first-time users
  until they collapse it. Distinct icons per item.
- Remove the Workspace menu and the eyebrow labels; page headers use the
  template's purpose line instead.
- Project switcher in the top bar owns project context; the rail no longer
  changes shape with the project.
- Dashboards, Charts, Reports, Metrics under Share; recipes list under Build
  → Studio; BI connections, notification targets and destinations under
  Automate → Destinations and Admin → Settings respectively.
- Merge the v1 source registry into Sources (one list: files uploaded,
  databases connected, streams; the "Register source" modal and
  `service-sources` retire or become the metadata behind that list).
- Unify "People": project access lives on the project's Settings tab; the
  platform People page stays in Admin.
- Status bar: either meaningful on every page (page-specific facts and the
  health chip) or removed from list pages.
- Command palette indexes the new tree and recent objects.
- Redirects from every old URL (bookmarks and docs must keep working).

**Verify in browser.** Cold-user task: "Find where dashboards are and open
one" and "Connect a database and see it in Sources" from a fresh profile;
target ≤ 3 clicks each, no wrong turns. Every old URL redirects.

**Exit gate.** Rail ≤ 7 top-level items; no page reachable only by deep link
except object detail pages; one taxonomy in code (a single `navigation.ts`
that the rail, palette and breadcrumbs all read).

**What shipped.**

- `apps/web/src/lib/navigation.ts` is the one tree (S3 above); the rail, the
  area tabs, the breadcrumb, the project switcher's "same page" target and
  Search all read it. `navigation.test.ts` walks every `page.tsx` in
  `src/app` and fails if one is outside the tree without a stated reason
  (frameless, standalone, or a redirect), if a tab points at a page that
  does not exist, or if the rail grows past seven.
- Rail: Overview, Data, Build, Automate, Trust, Share, and Admin for
  platform admins, each with a distinct new icon; the open project's name
  heads it and it never changes shape. Expanded by default, as before.
- Every page in an area shows the area's tabs. Eyebrow labels (46 call sites)
  and the Workspace menu are gone; `AppShell` is the list/detail template.
- New pages: Data → Datasets (one row per dataset name, repeated loads
  folded under it, "came from" in words), Automate → Runs (status filter,
  plain run names, duration), Overview → Settings. The project Overview is
  the checklist plus recent data and runs; its five tiles, the v1 "Register
  source" registry, "Trigger sample run" and the Workspace menu are gone.
- Sources (renamed from Extraction) is one page for uploaded files,
  databases and live feeds, list first: connecting a database and creating
  an import are dialogs, a previewed table has "Import this table", and
  import modes are in words ("Only new rows", "Loaded up to …"). The v1
  `service-sources` registry is no longer shown anywhere; its API stays for
  compatibility (D12).
- Renamed addresses redirect permanently: `/extraction` → `/sources`,
  `/data-quality` → `/checks`. Titles, browser-tab names and purpose lines
  follow the S2 vocabulary on every tab page.
- Status bar renders only when a page has facts for it (the editors).
  Search lists every tab with its area and one-line description, recent
  objects, projects, "New project" and "Show me around".
- Help menu: Show me around, Keyboard shortcuts, API reference (now that
  `/docs` loads), System status. The welcome tour is rewritten for the new
  layout as `welcome-v2`.
- Found and fixed on the way: Tailwind never scanned `packages/shared-ui`, so
  classes used only there were missing (panel corners, header layouts, the
  empty-state icon); the shared dialog could not scroll and lost its title
  and buttons on a laptop screen; Enter in the tour skipped every other step;
  `humanDuration` said "1 minutes"; and listing extraction jobs returned 500
  for any project with an import that had no shaping steps (P9 regression),
  which broke that project's whole Sources page.

**Measured (browser, 1440×900 window, admin account, dev stack).**

| Task | Clicks | Wrong turns | Notes |
|---|---|---|---|
| Find where dashboards are and open one (from a project's Overview) | 2 (Share, Open) | 0 | Target ≤ 3 |
| Connect a database and see it in Sources (fresh project) | 3 (Data, Connect a database, Connect) plus typing | 0 | Target ≤ 3. The new database is the first section on the page |
| Continue: import a table and open the dataset | 5 more (Browse tables, pick table, Import this table, Create import, Run now) | 0 | Feedback offers "Open the dataset" |

Not a fresh browser profile: the session cookie was set from a dev login,
and the tester knows the product. Five people outside the team remain the
A9 gate.

**Moved to later phases.** The Studio's own layout (ribbon, panels) is A3.
Studio-made recipes still open in the legacy form editor from the Recipes
list (D3, A3). Older pages' body copy, tables and form-first panels outside
the tabs touched here (Checks' "Define a rule", People's "Add someone") are
A2/A5. Datasets still multiply in the backend (D13); the list folds them,
the data model change is A4.

---

## A2 — Golden path and onboarding *(done 2026-10-14)*

**Why.** §0 blocker 6, F-UX-1..3, F-ST-5.

**Deliver.**

- **First-run flow** for a new workspace: create project → add data (upload
  or connect; sample dataset offered) → open in Studio → first check →
  schedule or share. Each step is one screen with one primary action; the
  checklist on Home tracks it and disappears when done. The five stat tiles
  leave the project overview; the overview becomes the checklist plus recent
  activity.
- **Empty states with actions everywhere** (the 54 bare "No X yet" strings and
  the 7 action-less `EmptyState`s become one component with a verb).
- **No form-first pages.** Create actions open a focused modal or a dedicated
  create page; lists are the page.
- **No errors before input.** Charts, Notebooks, Workflows, pipeline editor,
  Studio open in a neutral state with guidance.
- **Sample data and templates.** Three sample datasets (orders, customers,
  invoices) and three recipe templates (clean contacts, monthly revenue,
  dedupe and standardise) available from the add-data step and from Studio.
- **Contextual help.** A `?` on every page header opening a short "what this
  page is for" panel with a link to the docs page (A6 provides the site).
- **Notifications.** Group by object, digest routine successes, notify
  failures individually; per-type preferences on Settings.

**Verify in browser.** Cold-user task: "From nothing, get a CSV onto a
dashboard" — target under 5 minutes, ≤ 15 clicks, zero error banners.

**Exit gate.** Task numbers recorded; no page opens with an error; every empty
state has an action.

**What shipped.**

- **Sample data.** Three small files for one made-up shop (orders, customers,
  invoices) ship with the gateway, deliberately untidy. `GET /samples`, and
  `POST /projects/{id}/samples/{sample}` adds one through the same ingestion
  as an upload. One "Add data" dialog (upload a file, connect a database, try
  sample data) is reached from the Overview, its checklist, Datasets, Sources
  and the Studio's no-data canvas.
- **Recipe templates.** "Clean a contact list", "Monthly totals" and "Remove
  duplicates and tidy text" live in `service_transformations/templates.py`.
  Each matches its roles to the dataset's columns, the person confirms them,
  and the result is ordinary steps. Offered in the Studio as "Start from a
  template" on an empty recipe.
- **Welcome and first-run flow.** A new workspace's Home is a welcome with
  two ways to begin (new project, open the example) and nothing else. The
  project checklist lights only the next step.
- **Lists before forms.** Checks, People (project) and Reports open on their
  list; "New check", "Add a person" and "New report" open dialogs.
- **Empty states with a next step** across the pages that are mostly empty
  for a new project (Metrics, Comparisons, Organisations, audit, find a
  dataset, all runs, an empty dashboard, Checks, Reports, Incidents, People
  search). What is left without a button is deliberate: permission notices,
  the "Select a step" prompt, and short notes inside a panel ("No runs yet").
- **No errors before input.** The form recipe editor waits for the name to be
  touched. Crawled every tab page on a project with data and on a brand-new
  empty project: no error banner, no crash. The one alert is Workflows and
  Schedules saying no background worker is running, which is true on the
  dev stack and is the runtime-health check doing its job.
- **About this page.** A button on every tab strip opens the page's purpose
  and two to four plain sentences. The words sit beside each tab in
  `navigation.ts`; the test caps their length. The docs link waits for A6.
- **Notifications.** Migration 0046: `group_key`/`group_count` and
  `notification_preferences`. Each kind (failures, routine successes,
  incidents, mentions, reports, workflow messages) is "Each one", "Daily
  summary" or "Off"; successes default to the summary; a repeated unread
  failure about the same thing counts up instead of stacking. Settings has
  the choices; the Notifications page is a plain list.
- **Chart to dashboard.** A chart is named in words ("Amount by region"), the
  measure picker says Total, Average, Count rows, and saving offers "Put it
  on a new dashboard".
- **Wording.** Forty-eight sentences that still joined clauses with
  em-dashes are rewritten (`wording.test.ts` keeps them out), and every page
  has a browser-tab title (dashboards and datasets use their own name;
  `navigation.test.ts` checks).
- **Found on the way.** A spaced phone number ("+44 113 496 1037") was read
  as a twelve-digit integer; the sniffer now only treats spaces as thousands
  separators in groups of three. A "date" template role matched the column
  "notes"; short hints now match whole words only.

**Measured (browser, 1176×525 viewport, admin account, dev stack).**

| Task | Clicks | Error banners | Notes |
|---|---|---|---|
| From nothing, get a CSV onto a dashboard | 9 plus typing a project name and picking the file | 0 | New project, Add data, Choose a file, (file), Import as reviewed, Share, Make a chart, Save, Put it on a new dashboard. Target ≤ 15 |
| Clean a sample contact list with a template | 6 | 0 | Add data, Sample customers, Clean in Studio, Start from a template, Clean a contact list, Add these steps: 21 rows to 19 |

Time is not reported: an automated tester's pace is set by its tools, not
the product. No step waited on the server for long enough to notice. Same
caveat as A1: not a fresh profile and not a newcomer; five people outside
the team remain the A9 gate.

**Moved to later phases.** The Studio's own layout and the second recipe
editor are A3. Linking "About this page" to documentation is A6. The
template and sample set is three each; more is A8's adoption pack.

---

## A3 — Studio redesign *(done 2026-10-14)*

**Why.** §3 in full; the owner's own words: "everything is so cramped up,
nothing clear".

**Deliver (spec first, then build):**

- **Canvas-first layout.** The grid takes the page. One left panel, "Steps",
  shown as a vertical timeline (source → steps → result) with the current
  step highlighted. Step settings open **inline under the step in the
  timeline** (or as a popover anchored to the column when invoked from the
  grid), never on the opposite side of the screen. The inspector becomes an
  on-demand "Details" drawer (schema, plan, lineage), closed by default.
- **One way to add a step.** Retire the 24-control ribbon. A single "Add
  step" command (button and `/` shortcut) opens the tool palette: search,
  categories, recently used, and suggestions for the selected column; the 20
  built-ins and 173 tools are one list with the built-ins pinned. The
  right-click column menu remains the fast path and uses the same palette.
- **Typography floor.** Nothing below 12px in Studio; 13px body, 14px for
  step names; the grid header at 12px medium. Density setting keeps three
  levels but the floor holds.
- **Clear modes.** "Preview (first 50 rows)" and "Run (writes version n+1)"
  are two visible affordances with one status line; the plan strip becomes a
  single line ("Runs here" / "Runs in PostgreSQL · 3 of 4 steps") with the
  detail in the Details drawer, and its language passes the voice guide.
- **Safe interactions.** Header click sorts the view only; "Add as step" is
  an explicit option. Undo/redo for step edits. Unsaved-changes prompt uses
  the product's dialog, not the browser's.
- **One editor.** The legacy pipeline editor becomes a "form view" of the same
  recipe (all step types supported, including tools) or is retired with a
  redirect to Studio; the dataset page's primary action opens Studio; the
  recipes list (formerly pipelines) is a Build tab.
- **Frame.** Title, one-line purpose, source picker and step count in a
  header; the tour rewritten to match.

**Verify in browser.** Cold-user task: "Remove empty rows, standardise emails,
sort by date, save the recipe" — target ≤ 2 minutes, ≤ 12 clicks, no
horizontal eye travel for a step's settings (settings open within 200px of
where the user clicked). Screenshots at 1280×800 and 1440×900 attached to the
session log.

**Exit gate.** No sub-12px text in `features/studio`; ribbon removed; one
recipe editor; task numbers recorded.

### A3 specification (written 2026-10-14)

Measured before the work, at the owner's laptop size (1176×525 CSS pixels,
125% zoom): the top bar, tab strip, a 100px ribbon and a status bar leave the
grid about 380×150px between a 260px steps panel and a 300px inspector. A
step's settings open in the inspector, the full width of the grid away from
the step that was clicked. 24 text sizes below 12px. A header click silently
adds a sort step to the recipe. Recipes saved from the Studio reopen in a
different, form-based editor that supports half the step types.

**T1. Layout.** Under the area tabs, one header row and two columns:

```
┌ Recipe name ✎   from [orders ▾] · 3 steps · Unsaved      ↶ ↷  Details  ⋯  [Save] [Run] ┐
├ Steps (320px) ───────────────┬ Preview ───────────────────────────────────────────────┤
│ ● orders  49 rows · 9 cols   │ First 50 rows · 49 → 47 rows · 9 columns · Runs here     │
│ 1 Trim  email          −0    │ ┌──────────────────────────────────────────────────────┐ │
│ 2 Drop empty rows      −2    │ │ grid                                                  │ │
│   ┌ settings, inline ──────┐ │ │                                                       │ │
│   └────────────────────────┘ │ │                                                       │ │
│ 3 Sort  signup_date ↓        │ │                                                       │ │
│ [+ Add a step]   /           │ └──────────────────────────────────────────────────────┘ │
│ ● Result  47 rows · 9 cols   │                                                          │
└──────────────────────────────┴──────────────────────────────────────────────────────────┘
```

- No ribbon, no status bar, no inspector on this page. Facts the status bar
  carried (source, steps, rows, columns) are in the header and the preview
  line.
- **Details** opens a drawer on the right, closed by default: the result's
  columns and types, where the recipe runs (the plan, its SQL and rewrites),
  and the recipe as a YAML file. It closes with Esc.
- The purpose line ("Clean and reshape a dataset step by step. The original
  is never changed.") shows under the name on screens at least 700px tall.

**T2. The steps timeline.** Source at the top, then each step as one line
(number, name, what it acts on, rows it removed or added), then "Add a
step", then the result. Clicking a step opens its settings **directly under
it**, inside the timeline; one step is open at a time. Move up, move down and
remove are on the open step, not hidden behind hover. An empty recipe shows
"Add a step" and "Start from a template" with one sentence each.

**T3. One way to add a step.** "Add a step" (button, or `/` anywhere outside
a text field) opens one palette: a search box; when empty, "Recently used"
(last five, this browser), then **Common steps** (the 20 built-ins in their
five groups), then **More tools** (the library, by category). Search ranks
built-ins and tools together. Choosing a built-in adds it and opens its
settings in the timeline; choosing a tool shows its settings and a preview of
its effect in the palette, then "Add step". Right-clicking a column header
opens the same palette with that column chosen and tools for its type first.

**T4. Safe interactions.**
- A header click sorts **the rows on screen** only. A bar above the grid says
  so ("Sorted by amount, high to low, for viewing. Only the 50 rows shown are
  sorted.") with "Sort the whole table" (adds a sort step) and a clear button.
- Undo and redo (buttons and ⌘Z / ⇧⌘Z outside text fields) cover adding,
  removing, moving and changing steps, templates and YAML. Typing in one
  field is one undo step, not one per key.
- Leaving with unsaved changes through any link in the app asks in the
  product's dialog: Stay, or Leave without saving. Closing or reloading the
  tab uses the browser's own prompt, the only one a browser allows.

**T5. Preview and run.** The preview line names what it is ("First 50
rows"). **Save** stores the recipe; on a saved recipe with no changes it reads
"Saved". **Run** is enabled for a saved recipe with no unsaved changes; it
runs the saved recipe on the whole dataset and reports the result with a
link to it. The plan summary is one phrase in the preview line ("Runs here"
or "3 of 4 steps run in PostgreSQL"); the detail is in Details.

**T6. One editor.** The Studio opens an existing recipe at
`/projects/{id}/studio?recipe={recipe}` and saves it in place (PATCH);
"Save as a new recipe" is in the ⋯ menu. The form editor is retired: its
addresses (`/projects/{id}/pipelines/{recipe}`,
`/projects/{id}/datasets/{dataset}/pipelines/{recipe}`,
`/projects/{id}/pipelines/new`) redirect to the Studio, and every link in the
app goes straight there. A step type the Studio does not know is shown by
name with its settings as text, never dropped.

**T7. Type and touch.** Nothing below 12px in `features/studio`, the grid
included (cells 13px, headers 12px). Step names 14px, settings 13px. Targets
at least 28px tall.

**T8. Tour.** Four stops matching the new layout: the source, Add a step,
the timeline, the preview.

**What shipped.**

- **Layout (T1).** `studio-page.tsx` is a header (name, source, step count,
  saved state, undo, redo, Details, More, Save, Run) over two columns: the
  steps timeline (320px) and the preview. No ribbon, status bar or
  inspector on this page. `DetailsDrawer` holds columns and types, where it
  runs, the recipe as a file and comments; it sits beside the preview on a
  2xl screen and over it otherwise.
- **Timeline (T2).** `steps-timeline.tsx`: source, numbered steps with a
  one-line summary from `step-summary.ts` ("amount is more than 0",
  "signup_date, A to Z") and the rows each removed, Add a step, result.
  Settings open under the step; the "finish setting up" note appears there.
- **Palette (T3).** `step-palette.tsx` replaces the ribbon, the tool browser
  and the column menu. Common steps are grouped and added at once with the
  column pre-filled (`prefillConfig`); tools are set up with a preview and a
  pinned Add step. From a column it leads with tools named for what the
  column holds (`toolsNamedForColumn`). Recently used are kept per browser.
  Built-in steps, options, operators and totals are named in words.
- **Safe interactions (T4).** Header click sorts the rows on screen
  (`view-sort.ts`) with a bar saying so and "Sort the whole table"; only the
  main mouse button sorts. Undo and redo (`recipe-history.ts`, typing folds
  into one step). Leaving uses the app's existing guard, now worded
  truthfully because unsaved steps are kept as a browser draft
  (`recipe-draft.ts`) and offered back on return.
- **Preview and run (T5).** "All 20 rows" or "First 50 of 1,234 rows", the
  change in rows, and the plan in one phrase. Save, then Run, which runs the
  saved recipe and links to the result.
- **One editor (T6).** `/studio?recipe=` opens and saves (PATCH) a recipe;
  "Save as a new recipe" in More. The form editor and its helpers are
  deleted and its three addresses redirect; links use `recipeHref`.
  Comments on a recipe moved into Details.
- **Type (T7).** Nothing under 12px in `features/studio`, including the
  grid's canvas header (`type-floor.test.ts`).
- **Tour (T8).** `studio-v2`, four stops.
- **Sessions (found during the run).** The walkthrough hit an expired
  session: sessions lasted 60 minutes with no renewal, and every panel then
  showed "Invalid or expired access token". Sessions now renew while in use
  (`POST /auth/session/renew`, capped at `AUTH_SESSION_MAX_HOURS`, default
  12), an ended session goes to sign-in and back to the same page with a
  message, and the sign-in form only follows same-site `next` addresses.

**Measured (browser, admin account, dev stack).**

| Task | Clicks | Time | Notes |
|---|---|---|---|
| Remove empty rows, standardise emails, sort by date, save the recipe (sample customers, from the dataset page) | 8 (Clean in Studio, Add a step, right-click email, Standardise an email, Add step, Add a step, signup_date, Save) plus typing two searches | 58 s of tool time | Target ≤ 12 clicks, ≤ 2 minutes. Each step's settings opened in the steps list directly under the step, within 200px of the click |

Layout checked at 1024×498 (the owner's window at 125% zoom), 1280×800 and
1440×900 (the last two rendered in a frame of that exact size, since the
screen is smaller): at 1280×800 the grid shows about 16 rows beside the
whole recipe. Same caveat as A1 and A2 about who did the run.

**Exit gate.** No sub-12px text in `features/studio` (tested). The ribbon is
gone from the Studio; Notebooks, SQL, Table editor and Workflows still use
the shared ribbon (A5). One recipe editor. Task numbers above.

**Moved to later phases.** The other editors' ribbons and type sizes (A5).
Tool summaries from the server still say "null" in places (A5 copy). A
keyboard path through the palette beyond Enter on the top result (arrow
keys) is not there yet.

---

## A4 — Sources, destinations and migration *(done 2026-10-14)*

**Why.** §0 blocker 3, §6. This is the phase that decides whether the product
can be sold as an integration platform at all.

**Deliver.**

- **Wire the SDK to ingestion.** A source of any connector type that
  declares `read` can create and refresh a dataset (full and incremental
  where `incremental` is declared), through the same job model as database
  extraction, with the tier shown on the source. Start with the 50 tested
  connectors; the 5 SaaS adapters get a recorded-session tier as soon as one
  real credential is available.
- **Destinations that load.** PostgreSQL and MySQL (with **upsert on a key**,
  not only replace/append), S3 and GCS as Parquet/CSV, and one warehouse
  (Snowflake or BigQuery, whichever the first customer has) — each with
  test, schema preview, and a delivery record. S3/local destinations that
  exist today either write or are removed.
- **Migration wizard.** Source database → destination database: pick tables,
  map types with the canonical lattice (show lossy casts), carry primary
  keys and not-null, optional incremental sync afterwards, a report of what
  was and was not carried (views, sequences, constraints stated as not
  migrated). Honest scope: data and basic schema, not stored procedures.
- **Dataset download** (CSV/Parquet) from the dataset page and API.
- **One dataset per source job** (append versions on each run) so Datasets
  and Catalog stop multiplying; type column shows the source kind, not the
  storage format.
- **CDC**: MySQL binlog as the second engine if a customer needs it;
  otherwise state Postgres-only on the source card.

**Verify in browser.** From Sources: connect a REST or SaaS source at tier 2
and land a dataset; publish a recipe output to MySQL with upsert twice and
show no duplicates; run the migration wizard Postgres → MySQL on the demo
schema and read the report.

**Exit gate.** A buyer can answer "where can I pull from and push to" from
the Sources and Destinations pages alone, and the answer is true.

### A4 specification (written 2026-10-14)

Measured before the work. Imports reach three SQL engines through
`service_extraction` and nothing else, although the connector SDK has 155
connectors that declare `read` (50 tested in CI at tier 2, 105 never run).
Every import run creates a new dataset, so a nightly import makes 365 a
year. Destinations: PostgreSQL replace or append; S3 and "local directory"
destinations can be saved and tested but nothing writes to them; no MySQL,
no update-matching-rows, no file formats, no record of what a delivery
wrote beyond the run. No way to download a dataset. No database copy.

**U1. One dataset per import.** An import's first run creates its dataset,
named after the import; every later run adds a version to that same
dataset. Datasets made by earlier runs are left as they are (not merged:
they may have been edited, charted or shared since).

**U2. Import from any readable connector.** "Connect a source" opens the
connector catalogue: search, category, the tier on every card with its
explanation, unavailable connectors greyed with the reason. The form is
generated from the connector's own fields; secret fields are encrypted at
rest like database passwords. The connection lists what can be imported
(tables, endpoints, files) and "Import this" creates and runs an import.
Full refresh everywhere; "only new rows" where the connector declares
`incremental` and hands back a cursor. Shaping steps at import stay for
databases (pushdown needs SQL); other sources are cleaned in the Studio.

**U3. Destinations that load.** PostgreSQL and MySQL: replace the table,
add the rows, or update matching rows on chosen key columns (a new table
gets those columns as its primary key). S3 and S3-compatible storage
(custom endpoint: MinIO, R2, Wasabi) and a folder on the server: a CSV or
Parquet file. Each destination has a connection test; delivering shows
what will be written before it is written (columns and their types, or the
file path and format); every delivery is a run with the rows, mode and
target. Warehouses (Snowflake, BigQuery) are not built; the page says so.

**U4. Copy a database.** From a connected database (PostgreSQL, MySQL,
SQLite) to a PostgreSQL or MySQL destination: pick tables, see each
column's type there and here with conversions that lose detail flagged,
carry primary keys and not-null, run, and read a report per table (rows
copied, what was carried) plus what is never carried (views, other
indexes, foreign keys, defaults and auto-increment, check constraints,
triggers, procedures). Data and basic schema only, said on the page.

**U5. Download.** Any version of a dataset as CSV or Parquet, from the
dataset page and `GET …/datasets/{id}/download`.

**U6. Honest cards.** A connection shows its connector's tier; live feeds
say change capture is PostgreSQL only.

**What shipped.**

- **U1, one dataset per producer.** An import's runs and a recipe's runs add
  versions to one dataset (`reusable_dataset`; recipes get
  `output_dataset_id`, migration 0047, backfilled). Replays stay separate.
- **U2, import from any readable connector.** `connector_sources.py` connects
  the import service to the SDK: settings checked against the connector's
  fields, its secret fields encrypted, list / preview / import / "only new
  rows" through the connector, the stream stored on the import (migration
  0048). "Connect a source" is the catalogue with tiers; SQL databases keep
  their own form and path.
- **U3, destinations that load.** `sql_writer.py` for PostgreSQL and MySQL
  (replace, add rows, update matching rows by delete-then-insert, keys as the
  primary key of a new table, types from the values), files to S3 and
  compatible stores and to a server folder through the SDK's file
  connectors, a preview of what will be written, every delivery a run.
  Destinations page rebuilt; "Send to → A destination" on every dataset.
- **U4, Copy a database.** Plan through the canonical type lattice with
  losses marked, not-carried items counted from the source, tables created
  with keys and NOT NULL, rows streamed, a report per table.
- **U5, download** of any version as CSV or Parquet, applying the project's
  row and column policies (the first read path that does).
- **U6, honest cards.** Every connection shows its tier; live feeds say
  change capture is PostgreSQL only; the Destinations page says warehouses
  are not supported.
- **Security found on the way.** Server folders are confined to
  `SERVER_FILES_ROOT` (the local-files connector read any path, `/`
  included); connectors that fetch URLs refuse the cloud metadata address
  and, unless allowed, the server itself (`OUTBOUND_*`); a download applies
  policies.
- **Also fixed.** Delivered columns were all TEXT (the parser's object
  columns); the PostgreSQL TIMESTAMP WITH TIME ZONE name was lost in column
  discovery; the type parser missed "timestamp(3) with time zone"; a REST
  path typed after the default "/" became another host.

**Measured (browser and real servers).**

| Check from the plan | Result |
|---|---|
| Connect a REST or SaaS source at tier 2 and land a dataset | REST API (tier 2) connected, previewed and imported: 3 rows into a dataset |
| Deliver to MySQL with update matching rows twice, no duplicates | 20 added, then 20 updated and 0 added; MySQL holds 20 rows for 20 customers, customer_id the primary key |
| Copy a database PostgreSQL → MySQL and read the report | Three-table shop, 10 rows; keys, NOT NULLs, microseconds, JSON and exact prices arrived; foreign keys, an index, a unique constraint and defaults reported as not carried |

Connector, destination and copy tests run against the servers in
`docker-compose.connectors.yml` (PostgreSQL, MySQL, MinIO) and skip with the
reason without them.

**Moved to later phases.** No warehouse destination (Snowflake, BigQuery)
until a customer names one. MySQL change capture is not built. A copy runs
inside one request (2,000,000 rows a table); a background copy with
progress belongs with A7's scale work. The SaaS connectors remain tier 2
against recorded vendor contracts, not live accounts.

---

## A5 — Copy, design system and consistency *(done 2026-10-14)*

**Why.** F-UX-4..6, F-ST-2, F-ST-6.

**Deliver.**

- Rewrite every page purpose line, section description, empty state, banner
  and tour to the A0 voice guide; move rationale to the docs.
- A **language lint** in the web test suite: fails on listed jargon in UI
  strings, on purpose lines over 15 words, on em-dashes in strings, and on
  `text-[9px]`–`text-[11.5px]` outside the grid canvas.
- **One component per job** in `packages/shared-ui`: Button, Modal (dialogs
  and drawers), Badge, Table (sortable, dense/comfortable), PageHeader,
  EmptyState, StatTile, Tabs, Toast; delete the duplicates; migrate the 27
  hand-rolled tables and the 6 hand-rolled dialogs.
- **Casing and spelling** normalised (sentence case for titles, UK spelling,
  "PostgreSQL" once).
- Light theme as the recommended default in docs and screenshots; dark stays
  first-class.
- A short design-system doc in the repo (tokens, components, voice) so the
  next phase does not drift.

**Verify in browser.** Ten pages side by side before/after in the session
log; lint green with zero allowlist entries except the grid canvas.

**Exit gate.** Language lint in `npm run verify`; shared-ui is the only source
of the nine components; no UI string names a table or column.


### A5 specification (written 2026-10-14)

**Measured before starting.** A script reading every on-screen string from
the source (JSX text, labels, titles, descriptions and sentence-like
literals: 3,786 strings) and a browser script run on 41 pages (text under
12px, uppercase text, raw identifiers, retired words, purpose-line length).

| | Count |
|---|---|
| Strings naming code (`summary_json`, `logs_json`, `schema_json`, `profile_json`, `step_type`) | 14 |
| Retired words on screen (pipeline 29, publish 18, tenant 8, persisted 7, snapshot 6, drift 5, extraction 5, materialise 5, artifact 3, cron 3, lease, payload, "semantic version", "Hyper extract") | 100 |
| Purpose lines over 15 words / descriptions over 25 words | 3 / 21 |
| `text-[9px]`–`text-[11.5px]` uses | 343 in 60 files |
| `uppercase` uses / distinct letter-spacings | 200 / 10 |
| Hand-rolled `<table>`s / `role="dialog"` outside shared-ui / inline pills | 33 in 27 files / 7 / 58 |
| Pages (of 41) with text under 12px / uppercase text / raw ids | 17 / 16 / 4 |

Worst pages in the browser: Audit (all projects) 200 tiny, 105 uppercase,
131 raw ids; project Audit log 115 tiny, 34 raw ids; System status 99 tiny,
41 uppercase, nine retired words; Connectors 1,662 tiny; Run audit and
Dataset audit name `summary_json`, `logs_json`, `profile_json` and show ids.

**V1. A language lint that keeps it.** `lib/language.test.ts` reads the
same on-screen strings through the TypeScript parser and fails on: a
retired word (S2) or a code name; an HTTP verb with a path; an em-dash; a
purpose line over 15 words or a description over 25; a Title Case button or
heading; US spelling of the words the product uses (organize, catalog in
prose, -ize). One allowlist, each entry with its reason, empty except where
the word is the user's own (SQL keywords in the SQL editor). It replaces
`wording.test.ts`. A second test fails `uppercase` and any text size under
12px anywhere in the app.

**V2. Words.** Every flagged string rewritten to the A0 voice. Run audit,
Dataset audit and Run comparison rebuilt in words: names instead of ids,
"what it recorded" instead of `summary_json`, the raw record behind a
"Technical details" disclosure. System status in words and readable times.

**V3. The audit trail in words** (F-UX-7, unassigned until now). An audit
entry reads "Ann created a chart" with the object named, not
`POST /api/v1/projects/…/charts`; the request stays available behind
"Details" for the administrator who needs it.

**V4. Type and case.** Nothing under 12px; no uppercase text; one
letter-spacing (none). Mechanical, then checked page by page.

**V5. One component per job in `packages/shared-ui`.** Button, Modal (with
a drawer side), Badge, Table (header, rows, sortable header cell, two
densities), PageHeader (the AppShell header), EmptyState, StatTile, Tabs,
Toast. The 33 tables, the 58 inline pills and the hand-rolled modals move
onto them; a test fails a `<table>` or a `role="dialog"` outside shared-ui
(the command palette, step palette and tour are palettes and a coach mark,
built on a shared `Overlay`).

**V6. The design-system doc.** `docs/design-system.md`: tokens, the nine
components and when to use each, the voice rules the lint enforces, and
light as the recommended theme for screenshots and demos (dark stays
first-class; "system" stays the default).

**What shipped.**

- **V1, the language lint.** `lib/language.test.ts` reads 3,700+ on-screen
  strings through the TypeScript parser and fails a retired word, a stored
  field name, an HTTP path, an em-dash, a purpose line over 15 words, a
  description or tour step over 25, a lowercase or Title Case label, and US
  spelling. Two allowlist entries, each with its reason (Microsoft's "Tenant
  ID", PostgreSQL's `wal_level`), plus the run page's Technical details IDs.
  `test_error_words.py` holds the API's own error messages to the same words,
  since they are shown as they are.
- **V2, the words.** Every flagged string rewritten. Run audit, Dataset
  audit, both comparison pages and System status rebuilt in words: names
  instead of ids (the audit APIs now send who, which recipe and which
  datasets), "what it made / what it read / steps", the stored record behind
  Technical details. Run logs, audit notes, comparison notes, role
  descriptions, impact summaries and 29 error messages are written in plain
  words at the source. Power BI and Tableau dialogs became "Send to", on the
  shared form fields. The raw-JSON "Try a change" and create-pipeline dialogs
  were removed; the Studio does that job.
- **V3, the audit trail in words.** `service_governance/audit_words.py`
  turns every audited route into a phrase ("ran a recipe", "shared a
  dashboard by link") and names the object while it exists; the request
  stays on the row's tooltip and in exports. A test holds all 165 audited
  routes to words of their own. Search understands product words.
- **V4, type and case.** 343 sub-12px sizes to 12px (classes, the grid
  canvas, SVG labels), 200 uppercase uses and 10 letter-spacings removed;
  where uppercase had hidden a stored code, a label function now shows it.
- **V5, one component per job.** shared-ui gained Badge, Table, Tabs, Toast,
  StatTile, PageHeader, a compact EmptyState and the Overlay that Modal (and
  its drawer side), both palettes and the tour sit on; the icon set moved
  with them. 33 tables, about 80 pills, three dialogs and three tab lists
  moved onto them, and four local duplicates were deleted.
- **V6.** `docs/design-system.md`; the demo guide recommends light for
  screen sharing.
- **Found on the way.** The Audit Center's outcome filter sent values no
  entry has, so filtering by outcome always came back empty and every row
  was coloured as a failure. Buttons wrapped onto two lines in narrow
  headers. Tables inside bordered boxes ran text into the border. The
  workbench's side tabs showed raw lowercase names.

**Measured (41 pages in the browser, same script before and after).**

| | Before | After |
|---|---|---|
| Pages with text under 12px | 17 | 0 |
| Pages with uppercase text | 16 | 0 |
| Pages showing raw ids | 4 | 0 |
| Pages showing a retired or engine word | 13 | 1 (Connectors: vendor descriptions say "endpoint") |
| Purpose lines over 15 words | 3 | 0 |
| Audit (all projects): sub-12px / uppercase / raw ids | 200 / 105 / 131 | 0 / 0 / 0 |
| Connectors: sub-12px elements | 1,662 | 0 |
| System status: retired words | 9 | 0 |
| Hand-built tables / dialogs / tab lists outside shared-ui | 33 / 7 / 3 | 0 / 0 / 0 |

**Moved to later phases.** Stat tiles still open some pages where the number
does not drive an action (F-UX-2, A8's polish pass). The language lint covers
the web app and the API's raised errors; messages built elsewhere on the
server (warnings inside run summaries, connector descriptions) are not
linted yet.

---

## A6 — Trust, help and support for buyers *(done 2026-10-14)*

**Why.** §0 blocker 5, §7, D1, D11.

**Deliver.**

- **API**: fix OpenAPI generation (D1), publish the reference at `/docs`
  with an authentication guide and three worked examples (create source, run
  recipe, read dataset).
- **Docs site** (static, versioned, built from `docs/user/`): getting
  started, one page per area, a glossary (A0 §2), admin guide, security
  overview rewritten to the truth, release notes. In-app `?` links here.
- **Connector presentation**: the catalogue lists tested connectors by
  default; unverified ones appear under "Request validation" with the
  process explained; the tier badge copy reassures ("Tested in CI against a
  real server every merge") rather than alarms.
- **Security proof**: run OIDC against a real IdP tenant (Entra or Okta
  trial) and record it; add session policy (idle timeout, refresh), IP
  allow-list per organisation, and encryption at rest for dataset artifacts
  (or document the disk-level requirement).
- **Incidents and failures reach people**: incidents and workflow failures
  deliver to email/Slack targets; a weekly digest option.
- Help menu: Documentation, Keyboard shortcuts, Contact support (configurable
  address), What's new.

**Verify in browser.** `/docs` loads; every page's `?` opens the right docs
page; an incident arrives in a Slack channel (or the honest failure is shown
with the exact reason when no webhook is configured).

**Exit gate.** A security questionnaire's identity, encryption, audit and
session sections can be answered with links to product pages and docs.


### A6 specification (written 2026-10-14)

**Measured before starting.**

| | Now |
|---|---|
| Read paths that hand dataset rows to a person and apply row and column policies | 1 (download) of 10: detail and preview, version view, as-of SQL, charts and dashboards (including public links), the Studio preview, the assistant, comparisons, the column profile |
| Events that can reach email or Slack | 6 (schedule, delivery and recipe outcomes); incidents and workflow failures reach only the project owner, in the app |
| Help menu | Tour, shortcuts, API reference, status: no documentation, no support contact, no "What's new" |
| Help pages inside the product | 0; "About this page" has nowhere to point |
| Connectors shown by default | 211, of which 161 "Unverified" |
| Security questionnaire sections answerable from the product and docs | Identity (SSO unproven live), audit; not encryption of files, network restrictions or a stated session policy |

**W1. Policies on every read.** A viewer limited by a row or column policy
sees the same limited data everywhere rows reach them, not only in a
download. One test calls each read path as that viewer.

**W2. Help inside the product.** `/help`, built from `docs/user/` with the
app (so it always matches the version running): getting started, one page
per area, the glossary (A0, S2), an admin guide, security, the API guide
and "What's new". The Help menu gains Documentation, What's new and Contact
support (an address the deployment sets); each tab's "About this page" links
to its area's page.

**W3. The API reference, proven.** `/docs` loads; the API guide covers
signing in with a token and three worked examples (connect a source, run a
recipe, read a dataset). A test runs the examples against the API and
checks every documented path exists.

**W4. A catalogue that reassures.** Tested connectors are the catalogue;
the rest sit under "Available on request" with how validation works, and
the tier wording says what testing means rather than warning.

**W5. What a security review asks for.** Network allow-lists per
organisation (sign-in and every request from outside are refused, API
tokens included); the session policy configurable and stated (idle timeout,
renewal, the absolute cap); stored files encrypted at rest when a key is
set, with a command to encrypt existing files; System status says which are
on.

**W6. Failures reach people.** Incidents and failed workflows go to the
project's email and Slack targets and, in the app, to everyone who can act
on them; a weekly summary joins "each" and "daily summary".

**W7. Security overview, true and complete.** `docs/security.md` rewritten
to what ships, with a questionnaire-style page in the product (identity,
sessions, encryption, network, audit, data handling) linking to where each
is set. OIDC against a live identity provider cannot be run here (no tenant
on this machine); a script that does it against a configured provider is
provided and the gap stays stated until someone runs it.

**W8. Defects.** D1 to D20 re-checked live, plus anything found on the way
(a REST import labelled "Database import"); nothing found is left open.

**What shipped.**

- **W1, policies on every read.** `service_enterprise/policy_view.py` gives
  each read path one call that narrows rows, columns, previews, profiles and
  schemas for the reader's role. The dataset page (detail, preview, profile,
  versions, audit summary), SQL over a version, charts, pivots and
  dashboards (public links read as a viewer), the Studio preview and the
  datasets it joins, the assistant, comparisons and statistical tests,
  downloads and every delivery use it. `test_policies_everywhere.py` calls
  each path as a restricted reader; all six of its tests fail with policies
  switched off.
- **W2, help inside the product.** `/help` renders `docs/user/` (12 pages:
  getting started, one per area, glossary, admin guide, security, API guide,
  What's new) with the app, readable signed in or not. The Help menu gained
  Documentation, What's new and Contact support (`SUPPORT_CONTACT`, served
  by `GET /status/support`); every tab's "About this page" links to its
  section. `help.test.ts` holds the pages to the navigation (every link and
  every tab's section exists) and to the app's word rules.
- **W3, the API guide, run by a test.** Signing in with a token and three
  worked examples as curl commands; `test_api_guide.py` runs every example,
  in order, against the API and checks every request the guide names exists
  in the published reference.
- **W4, a catalogue that reassures.** The 50 tested connectors are the
  catalogue; the 161 others sit under "Available on request" with how
  validation works. Tiers read "Tested", "Tested live", "Tested on a
  recording" and "Not yet tested", each saying what was run; untested is
  plain, not amber. Nothing untested reads as tested, and a run from an
  untested source still says so.
- **W5, what a security review asks for.** Network allow-lists per
  organisation (sign-in, sessions, SSO, renewal and API tokens refused from
  outside, with the reason; a list that would lock out its saver is
  refused); `TRUSTED_PROXY_HOPS`; the session policy stated in Your settings
  and System status; stored files encrypted with AES-256-GCM when
  `STORAGE_ENCRYPTION_KEY` is set, `platform-encrypt-storage` for existing
  files; System status's Security panel says which are on.
- **W6, failures reach people.** Incidents reach the owner and every
  operator, editor and admin in the app, and the project's email and Slack
  targets once; failed and partial workflows reach the targets; a weekly
  summary joins "each" and "daily summary". Messages read in words.
- **W7, security overview, true and complete.** `docs/security.md`
  rewritten to what ships, and the questionnaire-style page in the help.
  `scripts/check-oidc.py` checks a configured provider end to end (with
  `--sign-in`, a real sign-in that writes nothing), tested against a provider
  served locally. Browser security headers on every page and API answer.
- **W8, defects.** D1 to D20 re-checked live: all hold. Found on the way and
  fixed: SSO never compared the ID token's nonce and trusted the token's own
  algorithm (four tests, all failing on the old code); unlayered element
  rules in `globals.css` cancelled every button's size and weight and every
  link's colour (a test now fails on any); a workflow with an unfilled task
  read "ready to run", and tasks now say what they need; the workflow
  Deliver task wrote to PostgreSQL only while offering every destination;
  the add-a-task buttons sat off-screen at laptop widths; four pages drew
  an Office-style ribbon; a side panel squeezed the tab strip; a malformed id
  in an address crashed instead of reading "not found"; platform roles
  showed raw codes and the Accounts table overflowed; the audit middleware
  wrote tests' requests into the configured database.

**Measured.**

| | Before | After |
|---|---|---|
| Read paths applying row and column policies | 1 of 10 | 10 of 10 (tested) |
| Events that can reach email or Slack | 6 | 10 |
| Help pages inside the product | 0 | 12, each tab linked to its section |
| Help menu: documentation, support contact, What's new | none | all three |
| API guide requests run against the API by a test | 0 | 12, in order |
| Connectors shown by default | 211 (161 "Unverified") | 50 tested; 161 on request |
| Questionnaire sections answerable with links | identity (SSO unproven), audit | identity, sessions, network, encryption, audit, data handling |
| Pages walked in the browser with a problem (47 checked) | 6 | 0 (Workflows and Schedules rightly say no worker is running here) |

**Not done here, and stated.** OIDC against a live identity provider: no
tenant exists on this machine; the script that does it is provided and the
gap stays in `docs/security.md` until someone runs it. Rate limiting moves
to A7 as planned. A content security policy is left to the proxy.

---

## A7 — Scale and reliability

**Why.** §7 scale story; agent audit of I and D.

**Deliver.**

- Object-storage artifact backend (S3-compatible) with the local backend kept
  for single-node; Helm PVC or bucket configuration; gateways become
  stateless.
- Heavy operations (upload parsing beyond a threshold, publish, chart
  computation over large artifacts, quality evaluation) move to the worker
  with progress shown in the UI.
- Workflow run retries with backoff and per-task retry policy; re-run from a
  failed task; concurrency limit per project.
- Inbound rate limiting on auth and public endpoints; OpenTelemetry traces
  behind a flag; performance budgets in `scripts/perf-baseline.py` enforced
  in CI.
- Browser end-to-end suite (Playwright) covering the golden path and the
  cold-user tasks from A1–A3; axe accessibility checks on the page templates.

**Verify in browser.** Upload a 200 MB file and watch progress; kill the
worker mid-run and see the retry; run two gateways against one bucket.

**Exit gate.** Documented ceilings raised and stated on the System status
page; E2E suite in CI.

---

## A8 — Adoption pack

**Why.** What a second customer asks for after the first one is live.

**Deliver.** Generic outbound webhooks with signed payloads; project export
and import (recipes, checks, schedules, dashboards as one bundle); a minimal
CLI and a Python client generated from OpenAPI; dashboard embeds with signed
URLs; metric alerts; activity feed per project; i18n scaffolding (strings
externalised, English only shipped).

**Exit gate.** A partner can integrate without reading the source.

---

## A9 — Launch gate

A phase with no features. Checklist, every line true:

- Zero P1 and P2 defects open from this review or found since.
- Cold-user tasks from A1–A3 pass with five people outside the team; results
  in the session log.
- Docs site live; release notes for the launch version; security overview
  current; API reference current.
- A demo workspace that seeds in one click from a clean install and matches
  the docs' screenshots.
- `npm run verify` and the E2E suite green on the release tag; images
  published; Helm chart installs on a clean cluster following the docs alone.
- Positioning statement agreed and true: what it is for, what it is not for,
  the row-count and deployment envelope it supports today.

---

*Maintained by the phase sessions themselves. When scope moves between
phases, move the bullet — never duplicate it.*
