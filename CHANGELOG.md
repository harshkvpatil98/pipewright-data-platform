# Changelog

What shipped, newest first, grouped the way the history is: the first version,
the roadmap phases (v1 phases 01–07, v2 phases 08–23), the production-readiness
phases P0–P9 and the adoption-readiness work A0–A9. There are no tagged
releases and nothing is published to a package index, so entries are named by
phase rather than by version. Dates are commit dates.

Each session's detail — what was verified live, what was deliberately left, and
the test counts at the time — is in the session log in
[docs/HANDOFF.md](docs/HANDOFF.md#10-session-log); the plans are in
[docs/plans/](docs/plans/).

---

## A0–A1 — product definition and navigation (2026-10-13)

- **The product, defined** in
  [the adoption-readiness plan](docs/plans/adoption-readiness-workflow.md):
  personas, an 18-noun vocabulary with the words it retires, one navigation
  tree, four page templates, five design principles and a voice guide.
- **One navigation tree** (`apps/web/src/lib/navigation.ts`) read by the rail,
  the tab strip, the breadcrumb, the project switcher and Search, with a test
  that every page is placed in it. The rail went from 31 items to seven areas
  with tabs; the Workspace menu and 46 eyebrow labels are gone.
- **Pages people use, rebuilt in plain words**: a project Overview that is the
  checklist plus recent data and runs; Data → Sources for files, databases and
  live feeds, with dialogs instead of forms at the top; new Data → Datasets
  and Automate → Runs lists; Overview → Settings; a dataset page that leads
  with its rows and keeps three actions in its header; Schedules in words
  ("Every weekday at 18:30") in five columns instead of thirteen; Home and
  System status naming the platform's parts in words.
- **Renamed addresses redirect**: `/extraction` → `/sources`,
  `/data-quality` → `/checks`. `/demo` and `/case-study` are removed.
- **Fixed** (adoption-review defects D1, D4–D8, D12, D14–D20, plus five found on
  the way): the API reference at `/docs` loads; no page opens on an error;
  dates are no longer called phone numbers or birth dates; previews no longer
  fill the audit log; listing database imports no longer fails for a project
  with a plain import; shared components get their styles; dialogs fit a
  laptop screen; Enter no longer skips tour steps.

## Unreleased — repository documentation and hygiene (2026-10-12)

- **What a public repository needs**: an MIT [LICENSE](LICENSE);
  [SECURITY.md](SECURITY.md), routing reports to GitHub private vulnerability
  reporting and scoping them to this product (connector credentials,
  write-back, access control and tenancy, the notebook sandbox, SQL injection,
  secrets in logs); a [code of conduct](CODE_OF_CONDUCT.md) (Contributor
  Covenant 2.1); bug, connector and proposal issue templates, with the issue
  chooser sending security reports to private reporting; a pull request
  template; `.editorconfig`; and `license = "MIT"` in the root and web
  `package.json` and in the gateway's and every service's `pyproject.toml`.
- **README rewritten against `main`**: what the platform does after P0–P9,
  architecture, configuration, measured test results, deployment, known
  limitations, a repository map and a documentation index that separates the
  current docs from the ones written for the first version.
- **CONTRIBUTING rewritten**: prerequisites, the gate, what a local run does
  not cover, and the invariants the code relies on.
- **Assistant working files left the repository**: `AGENTS.md`, `CLAUDE.md`
  and `docs/agent-context.md` are untracked and ignored. Their development
  rules now live in CONTRIBUTING.md, and the references to them were reworded.
- **Docs corrected**: [docs/security.md](docs/security.md) no longer calls TOTP
  and OIDC "planned" (adoption-review defect D11) and points to the security
  policy; `infra/README.md` points to `deploy/`; a new row in
  [HANDOFF §7](docs/HANDOFF.md#7-known-gaps--stated-not-hidden) records why
  notebook cells do not run on Linux.
- **CI**: `test_login_returns_bearer_token` now patches the second-factor
  lookup that P4 added to the login route, instead of reading `user_mfa` from
  whatever database `DATABASE_URL` names.
- Measured with `npm run verify`: ruff clean, 6,302 Python tests passed and 568
  skipped, 692 web tests passed, ESLint, `tsc` and the production build clean.

## Adoption-readiness review (2026-09-23)

No product code changed. A browser walk of all 59 web pages plus two code
audits, scored per dimension, with 20 defects (D1–D20) and the findings behind
them recorded with file evidence, and the A0–A9 workflow that follows:
navigation and vocabulary, a golden path, a canvas-first Studio, sources and
destinations that load, copy and component consolidation, docs and API proof,
scale, an adoption pack and a launch gate. **A0 is next.**
([adoption-readiness-workflow.md](docs/plans/adoption-readiness-workflow.md))

## P9 — market-decider depth (2026-09-23)

- **The IR is the only executor**: every step compiles to the relational IR;
  steps the algebra does not model run as `Extension` nodes.
- **Pushdown wired into extraction runs**: a job's steps run at the source as
  SQL where the dialect can, the rest locally, with the plan recorded on the
  run. Also fixed a `uuid` column failing every PostgreSQL extraction.
- **Semantic layer**: metrics defined once on the IR with an owner and a
  version history, resolved by charts, dashboards and reports (migration 0044).
- **Streaming sources**: inbound webhooks and PostgreSQL change data capture
  through a logical replication slot, materialised into one append-only
  versioned dataset, at-least-once (migration 0045).
- **Optimizer groundwork**: five provable IR rewrites applied before the
  planner splits a tree, proven by a four-way differential test.
- Defused a P4 test that minted an MFA ticket at a fixed past instant.

## P8 — BI and collaboration (2026-09-23)

- Dashboard builder v2: a real dashboard page, global filters, text tiles,
  auto-refresh, in-place layout editing (migration 0041).
- Comments with @mentions on datasets, pipelines, dashboards and change
  requests; fixed the P6 review thread that called the wrong endpoint.
- Invitations and reset codes emailed when the server can send mail.
- Reports delivered to Slack and email with the file attached, PDF output, and
  per-channel delivery outcomes (migration 0042); dashboard subscriptions.

## P7 — time travel, product Phase 18 (2026-09-23)

- An immutable, content-hashed version on every materialisation by every
  producer (migrations 0038–0040), with a version history panel.
- Temporal reads, `AS OF` SQL by version or instant, diff with and without an
  identity key, and restore that appends a version.
- A frozen evaluation clock and a recorded execution context per run;
  deterministic replay that answers equivalent, divergent, incompatible,
  unavailable, failed or unverifiable.
- Version pins and a two-step prune protocol; erasure reconciled with
  immutable versions; deleting a dataset reclaims every version's artifact.
- A scripted live acceptance run (`scripts/e2e/p7_time_travel.sh`).
- Also: a dependency vulnerability audit with CycloneDX SBOMs in CI (the P5
  deferred item), and the business requirements document with its PDF.

## P6 — governance depth (2026-09-23)

- The Audit Center: one admin-only, cross-project trail with filters, export
  and a retention sweep.
- Policy simulation: view a dataset as a role or as a person.
- Request changes with a comment on the change request itself.
- An erasure lifecycle — correction versus destructive — that never reports
  success it did not achieve (migration 0037).
- Catalog editing from a dataset page (ownership, certification, glossary
  terms) and PII scan results turned into classification tags.

## P5 — deployability and scale (2026-09-23)

- A Helm chart with a pre-install/pre-upgrade migration Job, ingress and
  optional autoscaling; a production compose file behind Caddy with automatic
  TLS; gateway and web images pushed to GHCR on a `v*` tag.
- The operations runbook ([docs/operations.md](docs/operations.md)).
- An opt-in slow-query log (`DB_SLOW_QUERY_MS`) and a dependency-free
  performance baseline script.

## P4 — enterprise identity (2026-09-23)

- TOTP two-factor authentication against RFC 6238, with recovery codes
  (migrations 0034–0036).
- OIDC single sign-on end to end: discovery, PKCE, one-time state, JWKS
  verification, group-to-role mapping, just-in-time provisioning.
- SCIM-lite offboarding (`scim-sync`) and
  [docs/enterprise-identity.md](docs/enterprise-identity.md). SAML is absent by
  design.

## P3 — operational backbone (2026-09-23)

- Worker and ticker heartbeats, a Runtime panel, and a stalled queue that opens
  an incident and resolves itself (migrations 0032–0033).
- `make dev` starts the workers; compose gains `app` and `worker` profiles.
- Workflow-run failures notify; dashboard sharing by revocable public link;
  real cross-project Runs and Datasets pages; upload sessions that survive a
  gateway restart.

## P2 — guided first win (2026-09-23)

- One type vocabulary across import, the dataset page and the Studio.
- A guided checklist on the project page, a one-click demo project carried
  through to a published chart and dashboard, first-run tours, and naming a
  pipeline when it is saved.

## P1 — identity core (2026-09-23)

- Email and display name, self-service password change, sign-out everywhere,
  admin reset codes, invitations, and scoped revocable API tokens (migration
  0031); [docs/security.md](docs/security.md).

## P0 — truth and trust (2026-09-23)

- A language pass in the buyer's vocabulary, runtime visibility on Home and
  the status pages, and the warning count in the test summary taken from 20
  to 0.
- The development orchestrator was removed in the same session (see below).

## Lifecycle and maintenance (2026-09-20)

- Rename, archive and delete for projects and datasets (with their files);
  leaving an organisation; account disabling; retiring schedules,
  destinations, targets and saved tests; delete actions across the UI.
- People and Organisations admin screens, the dashboards page, stopping a
  queued workflow run, and report delivery history.
- Fixed: a secret at a path containing a space, and a 204 response read as
  malformed JSON.

## Development orchestrator — added and removed (2026-09-17 to 2026-09-23)

A `pw-dev` orchestrator that ran phase work through planner, worker and
reviewer roles was added under `tools/dev-orchestrator/` (6586b00), changed in
26 further commits, and removed in f9892a2 in favour of working directly in the
repository. Its own tests left with it, and none of it was ever part of the
product; the unmerged work it produced is preserved outside the tracked tree
(see the 2026-09-22 row of the HANDOFF session log).

## Phases 10–11 — the connector factory and ingestion intelligence (2026-09-16)

- **Phase 10**: 211 connectors from four generators, 50 at tier 2 backed by
  vendor-contract fixtures and real PostgreSQL, MySQL and MariaDB containers in
  CI; OData and JSON:API protocol connectors; a schema watch with drift
  incidents and a nightly schedule type; secret references.
- **Phase 11**: a sniffing pipeline where every stage reports confidence and
  evidence and an ambiguous date blocks the import; ten per-format readers;
  ingest specs reused by column fingerprint; chunked resumable upload with a
  checksum; a streaming profiler; six nested-data tools.

## Roadmap v1 phases 01–07 and roadmap v2 phases 08, 09 and 12–17 (2026-08-23)

Built on the first version, after fixing its setup and adding extraction
(PostgreSQL, MySQL, SQLite with incremental loads), data quality rules with
quarantine, and schema drift detection:

- **01–07**: orchestration (workflow DAGs, a queue and worker, cron,
  backfills), trust (derived column lineage, anomalies, incidents), team
  (roles, versions, approvals, audit log), reach (a connector SDK with a
  conformance suite), consumption (charts, dashboards, pivots, Excel export,
  a catalog), intelligence (PII, join keys, entity resolution — no model
  calls), and enterprise (tenancy, row and column security, retention,
  `/metrics`).
- **08**: a canonical type system and a relational IR with pandas and SQL
  backends. **09**: the design system — three-state theming and density.
  **12**: pushdown planning. **13**: the canvas data grid. **14**: the formula
  engine. **15**: write-back. **16**: the tool-library machinery. **17**: the
  SQL workbench, notebooks and the Python sandbox.

## The first version (2026-04-15)

The repository as first published: a Next.js and FastAPI platform with JWT
login, project-scoped CSV, Excel and JSON uploads with preview, schema and
profile, saved transformation pipelines that create derived datasets, audits,
comparisons and saved statistical tests, PostgreSQL publish with Power BI and
Tableau flows, schedules and notifications.
