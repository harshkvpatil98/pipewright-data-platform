# Pipewright

Pipewright is a data workbench a team runs on its own servers. It brings data
in from files, databases and business apps, lets people clean and combine it
in a visual Studio without writing code, checks that it is right, runs the
work on a timetable, and delivers the results to databases, storage, BI tools
and dashboards. Every step is recorded and every version of every dataset is
kept.

The name is *pipe* + *-wright* (a maker, as in shipwright or wheelwright): the
craft of building data pipelines.

[![License: MIT](https://img.shields.io/badge/license-MIT-lightgrey)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)
![Node 22](https://img.shields.io/badge/node-22-339933?logo=node.js&logoColor=white)
![Next.js 16](https://img.shields.io/badge/next.js-16-000000?logo=next.js&logoColor=white)

## What it is for

- **For** teams that own their data without a data-engineering team (finance,
  operations, analysts); organisations that must keep data on their own
  infrastructure, with single sign-on, policies on every read and a full
  audit log; and consultancies serving several clients, with work moved
  between projects and dashboards embedded in a client's own site.
- **Not for** replacing a data warehouse, big data (it works on one machine,
  in memory), real-time streaming, an enterprise BI suite, or machine
  learning.
- **Tested at** uploads of 200MB, charts of datasets up to 500,000 rows,
  checks on 4 million rows, and deliveries of a million rows; the full
  envelope, and what is not proven yet, are in
  [docs/positioning.md](docs/positioning.md).

It is deliberately honest about its limits. Every connector carries a tier
that says whether it has ever run against a real system, a capability that does
not work on this deployment is declared as such, and the known gaps are listed
in one table ([docs/HANDOFF.md §7](docs/HANDOFF.md#7-known-gaps--stated-not-hidden))
instead of being discovered.

## Status

Active development; there are no tagged releases. The production-readiness
sequence P0–P9 finished on 2026-09-23 (identity, operations, deployability,
governance, time travel, BI and collaboration, and the first slices of
streaming, the semantic layer and the optimizer). The next sequence is the
adoption-readiness workflow A0–A9 in
[docs/plans/adoption-readiness-workflow.md](docs/plans/adoption-readiness-workflow.md),
written from a review of all 59 web pages: one navigation vocabulary, a guided
first run, a canvas-first Studio, and docs for end users. A0 (the product
definition and vocabulary) and A1 (navigation) shipped on 2026-10-13: the app
is organised as seven areas (Overview, Data, Build, Automate, Trust, Share
and, for administrators, Admin), each with its pages as tabs. A2 (the first
run) shipped on 2026-10-14: sample data, recipe templates, a welcome, help on
every page and notification preferences; a CSV reaches a dashboard in nine
clicks. A3 rebuilt the Studio around the data, with step settings where you
click, one search for every step, undo, and one recipe editor. A4 widened
what goes in and out: import from any connector that can read, deliver to
PostgreSQL, MySQL, S3 or a server folder, download any version, and copy a
whole database with a report of what did not come across. A5 put every
screen into the product's own words, with one type scale and one set of
components, kept that way by tests. A6 made it ready for a buyer's review:
help inside the product (`/help`, from [docs/user/](docs/user/)), an API
guide whose examples a test runs, row and column policies on every read,
network allow-lists, a stated session policy, files encrypted at rest, and
failures that reach email and Slack. A7 made it hold up under load: files in
an S3-compatible bucket shared by several gateways, uploads up to 200MB and
large deliveries and copies on the background worker with progress,
workflows that retry and can be picked up where they failed, rate limits,
OpenTelemetry traces, performance budgets and browser and accessibility tests
in CI, and the server's limits stated on System status. A8 opened it to
partners and scripts: signed webhooks, project bundles, a generated Python
client and `pipewright` command line, dashboards embedded in other sites by
signed links that run out, alerts on a dataset's measures, one activity
stream per project, and the shell's words in a message catalogue. The progress ledger lives in [docs/HANDOFF.md](docs/HANDOFF.md).

At a glance, measured on `main`:

| | |
|---|---|
| Python domain services | 24, in `services/` |
| Database migrations | 59 Alembic revisions, head `0059_activity` |
| Web pages | 64 Next.js App Router pages |
| Connectors | 211: 50 tier 2 ("Tested", run against a container or fixture in CI), 161 tier 4 ("Not yet tested", written from vendor documentation, offered on request) |
| Transformation library | 20 pipeline step types plus a `tool` step over 173 tools in 11 categories |
| Tests | 7,145 Python tests collected and 827 web tests ([results below](#running-tests)), plus 6 browser tests in CI, one of them signing in through a live Keycloak |

## What the platform does

### Bring data in

- **Upload** delimited text, Excel, JSON and JSON Lines, XML, YAML, Parquet,
  Avro, ORC, SQL dumps (parsed, never executed), SAS and Stata files, plain or
  compressed, through a sniffing pipeline where every stage reports its
  evidence; an ambiguous date blocks the import and asks, rather than
  guessing. Uploads are chunked, resumable and checksummed, and an ingest spec
  is remembered by column fingerprint for next month's file.
- **Import** from PostgreSQL, MySQL and SQLite with connection testing, schema
  discovery, bounded preview, and full-refresh, incremental-append or
  key-based merge loads with a watermark per job. A job's transformation steps
  run at the source as SQL where the dialect can express them. Any other
  connector that can read (REST APIs, apps, object storage) imports through
  the same jobs, with "only new rows" where the connector can resume. Every
  run of one import adds a version to one dataset.
- **Connector catalogue** of 211 connectors (databases, warehouses, object
  stores, SaaS and protocol connectors such as OData and JSON:API), each with a
  tier shown on its card, in its config form and in the warnings of any run
  that used it. A nightly schema watch opens a drift incident when a source
  changes shape.
- **Streaming sources**: a token-keyed inbound webhook receiver and PostgreSQL
  change data capture through logical replication, read in micro-batches and
  materialised as versions of one append-only dataset, at-least-once.

### Shape it

- **Studio**: a canvas data grid with Excel keybindings and clipboard, column
  profiling, spreadsheet formulas (an 87-function catalogue), a right-click and
  Ctrl+K path to every tool, and a plan panel that shows which steps run at the
  source and why the rest do not.
- **One relational IR** behind every step, tool and formula, with a pandas and
  a SQL backend proven equal by differential tests, a pushdown planner, and
  provable rewrites (predicate and limit pushdown, filter merging) applied
  before it splits a plan.
- **SQL workbench and notebooks**: read-only by default with per-dialect
  statement timeouts, EXPLAIN, a live schema browser and autocomplete; notebook
  Python cells run in a probed sandbox and are disabled, with the reason
  stated, where the sandbox cannot enforce its limits. Recipes round-trip as
  YAML.
- **Write-back** to live tables the platform does not own: change sets with row
  identity, a dry run that leaves nothing behind, blast-radius checks, batching
  and a per-cell concurrency check, from the Table editor.

### Trust it

- **Data quality**: eight rule types with `error` and `warning` severity;
  failing rows are quarantined into their own dataset.
- **Lineage** at column level, derived from the steps rather than stored.
- **Time travel**: every materialisation records an immutable, content-hashed
  version. Read or query a dataset as of a version or an instant (`AS OF` SQL),
  diff two versions, restore one, and replay a run against its pinned inputs
  with an answer of equivalent, divergent, incompatible, unavailable, failed or
  unverifiable.
- **Governance**: roles per project, change requests with review comments, an
  admin-only Audit Center across projects with export and retention, policy
  simulation ("view as role or person"), row and column security, an erasure
  lifecycle that never reports success it did not achieve, and a catalog with
  owners, certification, glossary terms and PII-derived classification tags.
  PII detection and the other inference in `service-intelligence` are
  deterministic and make no model calls.

### Run and share it

- **Orchestration**: workflow DAGs on a leased queue with a worker process,
  cron schedules with backfills, worker and ticker heartbeats, and a stalled
  queue that opens an incident and resolves itself when work moves again.
- **Consumption**: charts, a dashboard builder with filters, text tiles and
  auto-refresh, public share links that can be revoked, reports delivered to
  Slack and email as Excel, CSV, HTML or PDF, dashboard subscriptions, and metrics defined
  once in a semantic layer and resolved everywhere they are used.
- **Delivery**: deliver a dataset to PostgreSQL or MySQL (replace, add rows,
  or update matching rows by key), to S3 or a compatible store, or to a
  folder on the server, after a preview of what will be written; download
  any version as CSV or Parquet with the project's row and column policies
  applied; copy a whole database between PostgreSQL and MySQL with a plan
  that marks every lossy type and a report of what was not carried. Power BI
  and Tableau have their own publish flows; in-app notifications plus email,
  Slack and signed webhook channels, every webhook attempt recorded.
- **Partners and scripts**: dashboards embedded in other sites by signed
  links that run out and can be turned off, with filters a partner's server
  fixes per customer; alerts when a dataset's measure crosses a line;
  one activity stream per project; project bundles that move recipes,
  checks, dashboards and workflows between projects; and `clients/python`,
  a client generated from the API and a `pipewright` command line.
- **Identity**: scrypt-hashed passwords, JWTs that one "sign out everywhere"
  invalidates, scoped revocable API tokens, invitations, TOTP two-factor
  authentication, OIDC single sign-on with group-to-role mapping, and a
  SCIM-lite job that deactivates accounts that left the directory.

## Architecture

```
 Browser
    │
    ▼
 apps/web ─────────────── Next.js 16 App Router, React 19, TypeScript, Tailwind v4
    │  REST /api/v1
    ▼
 apps/api-gateway ─────── FastAPI: mounts every service's router; one permission
    │                     dependency on the whole API; audit middleware; Alembic
    ▼
 services/service-* ───── 24 domain packages loaded in-process (a modular monolith):
    │                     auth, access, projects, enterprise, governance, sources,
    │                     datasets, ingestion, extraction, connectors, transformations,
    │                     quality, lineage, intelligence, workbench, writeback,
    │                     reporting, destinations, comparisons, pipeline-runs,
    │                     workflows, schedules, notifications, observability
    ▼
 PostgreSQL 16 ────────── metadata, queue, versions, audit trail
 file storage ─────────── uploads and dataset artifacts (local by default)

 platform-workflow-worker  drains the leased workflow queue
 platform-schedule-ticker  fires schedules, polls CDC sources, runs retention sweeps
```

The gateway is the only public backend; the workflow worker and the schedule
ticker run from the gateway's image with a different command. Services reach each other through
registered hooks rather than imports, and shared infrastructure (storage,
settings, errors, secret references, the type system) lives in
`packages/shared-python`. `packages/shared-types` mirrors the Python schemas in
TypeScript. The frontend has no icon or chart library: every icon and chart is
hand-written SVG drawn from semantic theme tokens, in light, dark and system
themes.

The rules the code relies on are listed in
[CONTRIBUTING.md](CONTRIBUTING.md#invariants); the full architecture notes, phase
by phase, are in [docs/HANDOFF.md](docs/HANDOFF.md).

## Tech stack

- **Frontend**: Next.js 16, React 19, TypeScript 5.9, Tailwind CSS 4, Vitest
- **Backend**: FastAPI, SQLAlchemy 2, Alembic, Pydantic v2, Uvicorn
- **Data**: pandas, pyarrow, fastavro, openpyxl; source access through
  SQLAlchemy (psycopg, PyMySQL, SQLite), httpx and boto3
- **Database**: PostgreSQL 16
- **Tooling**: npm workspaces, Rush, Docker Compose, Helm, pytest, Ruff, ESLint
- **CI**: GitHub Actions — the verify gate, a weekly dependency audit with
  CycloneDX SBOMs, and image builds to GHCR on a version tag

## Quick start

Prerequisites: Node.js 22, Python 3.11 or newer (on macOS use Homebrew's
`python@3.12`; the system Python is too old), and Docker for PostgreSQL.

```bash
make setup    # .env files from the examples, npm install, .venv, an encryption key,
              # and — with Docker running — Postgres plus the migrations
make dev      # gateway :8000, web :3000, and the workflow worker and schedule ticker
```

In a second terminal, create the first admin from the credentials in `.env`:

```bash
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" \
  --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
```

Then open `http://localhost:3000`, sign in, and choose **Create a demo
project** on Home. It seeds a worked example through the same service
functions a user's clicks call: an orders CSV with a missing amount, a missing
email and a negative refund, a filter pipeline, a not-null rule, a daily
schedule, a revenue-by-region chart and a dashboard. The project can be deleted
like any other. `samples/demo-customers.csv` is a second file to upload by hand.

| URL | What |
|---|---|
| `http://localhost:3000` | The web app |
| `http://localhost:3000/system-status` | Health, runtime heartbeats and queue depths |
| `http://localhost:8000/api/v1/health/live` | Gateway liveness |
| `http://localhost:8000/metrics` | Prometheus metrics |
| `http://localhost:8000/api/docs` | Interactive API reference (also `/api/redoc`) |

## Configuration

Three env files, each created from its example by `make setup`:

| File | Controls |
|---|---|
| `.env` (from [`.env.example`](.env.example)) | Compose project name, ports, the development Postgres credentials, and the bootstrap admin |
| `apps/api-gateway/.env` (from [its example](apps/api-gateway/.env.example)) | `DATABASE_URL`, JWT settings, CORS origins, storage paths and upload limits, scheduler identity and lease, SMTP for email delivery, and `APP_SECRET_ENCRYPTION_KEY` |
| `apps/web/.env` (from [its example](apps/web/.env.example)) | The API base URLs the browser and the server use |

- `APP_SECRET_ENCRYPTION_KEY` is a Fernet key that encrypts saved credentials
  and webhook secrets. `make setup` generates one; changing it later makes the
  stored secrets unreadable.
- Production templates are in `apps/api-gateway/.env.production.example` and
  `apps/web/.env.production.example`. Never reuse the development JWT secret or
  the `platform/platform` database credentials.
- Single sign-on is configured with the `OIDC_*` variables in
  [docs/enterprise-identity.md](docs/enterprise-identity.md); the slow-query
  log with `DB_SLOW_QUERY_MS`, described in [docs/operations.md](docs/operations.md).
- `ALLOWED_UPLOAD_EXTENSIONS` in both gateway env examples is
  `csv,xlsx,json`, which narrows the much wider default in
  `apps/api-gateway/src/api_gateway/config.py`. Remove the line, or list more
  extensions, to accept the other formats the readers handle.
- If the web app runs on a port other than 3000, add its origin to
  `BACKEND_CORS_ORIGINS` (a JSON list), or every client-side panel fails with
  "Failed to fetch".

## Running tests

```bash
npm run verify    # the CI gate: ruff, the pytest bundle, web tests, ESLint, tsc, production build
npm test          # tests only (pytest bundle, then Vitest)
npm run smoke     # prerequisite and API checks for a running stack
```

Measured on `main` on 2026-10-14 (macOS, Python 3.12, Node 22, with the
connector test servers from `docker-compose.connectors.yml` and MinIO
running): ruff clean; **6,536 Python tests passed, 569 skipped, 0 failed**;
**806 web tests passed** in 63 files; ESLint, `tsc` and the production build
clean. Skipped is not passed, so the skips are accounted for: 512 are
ingestion-corpus cases that carry no expectation for the check in question,
43 are parametrized cases that do not apply (a frame tool with no single
target column, a stream that does not paginate or declare a schema), 9 are
tools whose behaviour on null input or shape is documented rather than
computed and one S3 case with no template to leave empty, 3 are notebook cell
tests (Python cells are disabled on macOS), 1 is the PostgreSQL CDC round trip
(the test server runs `wal_level=replica`) and 1 needs a MariaDB server.

CI runs the same gate on Ubuntu with Python 3.11 and real PostgreSQL, MySQL,
MariaDB and MinIO servers, builds the gateway and web production images,
holds ten endpoints to p95 budgets against a seeded database
(`scripts/perf-baseline.py --budgets`), and runs the Playwright suite (the
golden path, and axe on every page template) against a production build. How
to run the connector servers locally, and what else a local run does not
cover, is in [CONTRIBUTING.md](CONTRIBUTING.md#what-a-local-run-does-not-cover).

## Deployment

| Option | What it is |
|---|---|
| [`docker-compose.yml`](docker-compose.yml) | Development stack with profiles: `--profile app` (Postgres, gateway, web), `--profile worker` (worker and ticker). Postgres runs with `wal_level=logical` for CDC |
| [`docker-compose.prod.yml`](docker-compose.prod.yml) | Single-host production: pre-built images from GHCR (`PIPEWRIGHT_TAG` is required), Postgres, all four runtimes, and [Caddy](deploy/Caddyfile) terminating TLS and routing `/api` to the gateway and `/` to the web |
| [`deploy/helm/pipewright`](deploy/helm/pipewright/README.md) | Kubernetes: per-component deployments, a pre-install/pre-upgrade migration Job, ingress, optional autoscaling; the chart never deploys `latest` |
| [`release-images.yml`](.github/workflows/release-images.yml) | Builds and pushes `pipewright-gateway` and `pipewright-web` to GHCR on a `v*` tag |

Run one schedule ticker unless each has a distinct `SCHEDULER_RUNTIME_ID`;
workers scale freely. Upgrades, backup and restore (`scripts/backup.sh --verify`
runs a real restore drill), scaling, sizing and observability are in
[docs/operations.md](docs/operations.md), and recovery from losing the database,
the files or the machine in [docs/disaster-recovery.md](docs/disaster-recovery.md).
`infra/` holds no assets yet; deployment lives in `deploy/`.

## Known limitations

The complete list, with the reason for each, is
[docs/HANDOFF.md §7](docs/HANDOFF.md#7-known-gaps--stated-not-hidden). The ones a
first-time user meets soonest:

- **Connectors are mostly unverified.** 161 of the 211 have never run against
  the real vendor, and say so; five SaaS connectors (Stripe, HubSpot, Shopify,
  Salesforce, Sheets) have not run live, and Snowflake, BigQuery, Redshift, SQL
  Server and Oracle declare only a connection test until their drivers are
  installed. Imports run from any connector that can read, but only the
  tested ones have run against a real server here.
- **No warehouse destinations.** Datasets deliver to PostgreSQL, MySQL, S3
  and a server folder; Snowflake, BigQuery and Redshift are not destinations.
  A database copy runs on the background worker (up to 2,000,000 rows a table).
- **Identity**: SAML is absent by design (it needs XML signature verification).
  Single sign-on is tested against a live Keycloak in CI on every change;
  Okta and Entra ID have not been run, for want of a tenant.
- **Write-back** has run only against SQLite; the PostgreSQL and MySQL paths are
  written and dialect-aware but unexercised against a server.
- **Email and Slack delivery** are tested with captured senders, not against a
  real SMTP server or Slack workspace. Webhooks are tested against a local
  receiver.
- **Streaming** covers inbound webhooks and PostgreSQL CDC only, at-least-once.
- **Notebooks** run in the request (15 s per Python cell) rather than on the
  worker. Python cells are disabled on macOS, where the sandbox cannot limit
  memory; on Linux they run.
- **Uploads** stop at 200MB by default: reading a CSV takes about nine times
  its size in memory on the worker. Larger data comes in through a database or
  storage import.
- The [adoption review](docs/plans/adoption-readiness-workflow.md) lists 20
  user-facing defects (D1–D20) with file evidence and the phases (A0–A9) that
  address them; its status line says which are fixed.

## Repository map

```
apps/
  api-gateway/     FastAPI gateway, Alembic migrations, CLI entry points
                   (bootstrap user, workflow worker, schedule ticker, scim-sync)
  web/             Next.js web app and its Vitest suite
services/          24 Python domain packages, service-*/src and service-*/tests
packages/
  shared-python/   storage, settings, errors, logging, tracing, secret references, types
  shared-types/    TypeScript contracts mirroring the Python schemas
  shared-ui/       shared React components
  config/          shared ESLint and TypeScript configuration
deploy/            Helm chart and the Caddyfile for the production compose file
docs/              handoff, operations, security, identity, roadmap, plans and guides
scripts/           setup, dev, worker, test, verify, smoke, backup, perf baseline,
                   connector and tool-reference generators
samples/           a demo CSV
common/            Rush configuration
output/pdf/        the business requirements document as a PDF
tmp/pdfs/          the script and data that build that PDF
infra/             reserved; nothing deployed from here yet
```

## Documentation

**Current**

| | |
|---|---|
| [User help](docs/user/) | What people read at `/help` in the app: getting started, each area, the glossary, the admin guide, security and the API guide |
| [Handoff](docs/HANDOFF.md) | Project state, architecture rules, gotchas, known gaps, the progress ledger and the session log |
| [Operations](docs/operations.md) · [Disaster recovery](docs/disaster-recovery.md) | Upgrades, backups, scaling, sizing, observability; recovering from loss |
| [Security overview](docs/security.md) · [Enterprise identity](docs/enterprise-identity.md) | Identity, sessions, policies, network lists, encryption at rest, audit; MFA, SSO, SCIM-lite |
| [Design system](docs/design-system.md) | Tokens, the shared components and when to use each, the voice rules, and the tests that keep them |
| [Adding a connector](docs/adding-a-connector.md) · [Transformation tools](docs/transformation-tools.md) | The four ways to add a connector; the generated reference for all 173 tools |
| [Roadmap v2](docs/roadmap-v2.md) | The Studio-era roadmap (its opening status line predates the work; the handoff ledger is current) |
| [Plans](docs/plans/) | The production-readiness (P0–P9) and adoption-readiness (A0–A9) workflows, and the time-travel requirements and decisions |
| [Business requirements](docs/business-requirements.md) ([PDF](output/pdf/Pipewright_Business_Requirements_Document.pdf)) | Use cases, users and requirements, as of commit `79eb302` |
| [Changelog](CHANGELOG.md) · [Contributing](CONTRIBUTING.md) | What shipped, phase by phase; how to work on the project |
| [Security policy](SECURITY.md) · [Code of conduct](CODE_OF_CONDUCT.md) | How to report a vulnerability; how contributors treat one another |

**Written for the first version (last revised April 2026)** — still useful for
setup detail, but they describe the pre-Studio product, and where they disagree
with the handoff, the handoff is right. The `/demo` and `/case-study` pages
they mention were removed in A0, and the app's pages are now organised as the
navigation tree in `apps/web/src/lib/navigation.ts`:
[architecture](docs/architecture.md),
[features](docs/features-guide.md),
[installation](docs/installation-guide.md),
[local setup](docs/local-setup-guide.md),
[demo guide](docs/demo-guide.md),
[deployment guide](docs/deployment-guide.md),
[troubleshooting](docs/troubleshooting.md),
[release checklist](docs/release-checklist.md),
[reviewer summary](docs/reviewer-quick-summary.md),
[case study](docs/project-case-study.md),
[showcase guide](docs/showcase-guide.md).

## Security

Report vulnerabilities privately through
[GitHub's advisory form](https://github.com/harshkvpatil98/pipewright-data-platform/security/advisories/new),
never in a public issue. [SECURITY.md](SECURITY.md) explains what is in scope —
leaked connector credentials, access-control and tenancy bypasses, write-back
that escapes its checks, sandbox escapes, SQL injection and secrets in logs —
and [docs/security.md](docs/security.md) describes the controls.

## License

[MIT](LICENSE) © 2026 Harshwardhan Patil

## Author

Harshwardhan Patil ([@harshkvpatil98](https://github.com/harshkvpatil98))
