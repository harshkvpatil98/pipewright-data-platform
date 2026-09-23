# Adoption-Readiness Review and Workflow

**Date:** 2026-09-23 (after production-readiness P0–P9 closed).
**Purpose:** an unbiased, evidence-based review of Pipewright as a B2B product
a business would buy and use without a data engineer on call, followed by the
workflow that turns the findings into shipped work. The review looked at every
one of the 59 web routes in a running dev stack through a browser, plus two
read-only audits of the code (information architecture and copy; feature
coverage against what a data-platform buyer expects). Every number below was
measured, not estimated.

**Status:** review complete; **A0 (Product definition and IA reset) is next**.
One phase executes per session-run; the owner says "continue" to start the
next. `docs/HANDOFF.md` records what actually happened.

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

## A0 — Product definition and IA reset *(next)*

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

---

## A1 — Navigation and shell

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

---

## A2 — Golden path and onboarding

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

---

## A3 — Studio redesign

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

---

## A4 — Sources, destinations and migration

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

---

## A5 — Copy, design system and consistency

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

---

## A6 — Trust, help and support for buyers

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
