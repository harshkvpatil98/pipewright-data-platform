# Pipewright

Pipewright is a production-style data pipeline platform. It combines a Next.js frontend, a FastAPI gateway, PostgreSQL persistence, and modular Python domain services so users can move from source database or file all the way through transformation, quality enforcement, publishing, scheduling, and operational review inside one project-scoped workflow.

The name is *pipe* + *-wright* (a maker, as in shipwright or wheelwright): the craft of building data pipelines.

## Why this project matters

Most portfolio apps stop at CRUD. This repo goes further by modeling the operational side of data work: ingestion, profiling, repeatable transformations, derived datasets, run history, audit views, testing workflows, publish targets, schedules, notifications, and deployment packaging. That makes it easier for reviewers to evaluate architectural judgment, platform thinking, and product completeness instead of just UI polish.

## What the platform does

- Authenticates users and scopes data to owned projects.
- **Extracts from PostgreSQL, MySQL, and SQLite** with connection testing, schema/table discovery, and bounded query preview.
- **Loads incrementally** — full refresh, append, or key-based merge (upsert) with a persisted watermark per job.
- Uploads `csv`, `xlsx`, and `json` datasets.
- Persists schema, preview, profile, lineage, and run history.
- Runs **20 transformation step types**, including joins across datasets, unions, aggregations, pivot/unpivot, and safe derived-column expressions.
- Creates derived datasets from saved pipeline runs.
- **Enforces data quality rules** with error/warning severity and quarantines failing rows into their own dataset.
- **Detects schema drift** automatically on every extraction and grades it breaking / risky / compatible.
- Exposes audit, comparison, and saved statistical testing workflows.
- Publishes datasets to PostgreSQL and supports Power BI and Tableau publish flows.
- Supports schedules, manual triggers, retries, notifications, and status visibility.

## Key implemented features

### Platform core

- JWT login and authenticated project workspaces
- Project-scoped sources, datasets, runs, destinations, BI connections, schedules, and notifications
- Shared TypeScript contracts between frontend and backend

### Extraction and ingestion

- Database extraction for PostgreSQL, MySQL, and SQLite over one SQLAlchemy code path
- Saved connections with credentials encrypted at rest and redacted in every API response
- Connection testing (latency + server version), table/view discovery, column inspection, bounded preview
- Operator-authored SQL is enforced read-only: single-statement, `SELECT`/`WITH` only, with data-modifying CTEs rejected
- Chunked reads with a row cap so wide tables cannot exhaust memory
- Incremental loading: `full_refresh`, `incremental_append`, `incremental_merge`, with watermark tracking and reset
- File upload ingestion for `csv`, `xlsx`, and `json`
- Stored dataset preview, schema, profile, and parser metadata

### Transformation workflows

- 20 step types across column shaping, value cleaning, row selection, and reshaping
- Multi-dataset steps: `join_datasets` (inner/left/right/outer, composite keys, many-to-many guard) and `union_datasets`
- Reshaping: `aggregate` (11 functions), `pivot`, `unpivot`
- `derive_column` with a sandboxed expression evaluator — AST allowlist, no `eval`, vectorised over pandas
- Saved pipelines with a structured editor and in-memory preview before persistence
- Pipeline execution that creates derived datasets and tracked `pipeline_runs`

### Data quality and schema governance

- Eight rule types: `not_null`, `unique`, `allowed_values`, `range`, `regex_match`, `expression`, `row_count`, `freshness`
- `error` severity quarantines failing rows and fails the evaluation; `warning` reports without blocking
- Quarantined rows are materialised as their own dataset for inspection and replay
- A misconfigured rule is recorded as a failure of that rule rather than aborting the whole evaluation
- Schema drift detected automatically on every extraction, graded breaking / risky / compatible, with acknowledgement

### Review and quality

- Dataset audit and run audit pages
- HTML audit export
- Dataset comparison, run comparison, ad hoc statistical tests, saved tests, and rerun history

### Delivery and operations

- Saved Postgres, S3, and local-export destination configs with connection tests
- Dataset publish to PostgreSQL
- Saved Power BI and Tableau connections with test and metadata discovery
- Dataset publish flows for Power BI and Tableau
- Schedules for transformation runs and PostgreSQL publish
- In-app notifications and optional external notification targets for email and Slack webhooks
- `/system-status` and `GET /api/v1/status` for operational visibility

## Architecture summary

The repo uses a modular monolith shape. `apps/web` is the Next.js frontend, `apps/api-gateway` is the only public backend deployable, and domain behavior lives in `services/service-*` packages for auth, projects, datasets, ingestion, extraction, transformations, quality, destinations, schedules, notifications, comparisons, and pipeline runs. Shared backend infrastructure lives in `packages/shared-python`, while `packages/shared-types` and `packages/shared-ui` keep contracts and UI primitives aligned across the stack.

This is stronger than a typical CRUD app because workflow state is persisted across uploads, lineage, runs, audits, schedules, publish outcomes, and notifications. The project also includes migrations, env templates, Docker Compose, smoke checks, and CI parity verification, which gives reviewers a more realistic engineering handoff story.

## Tech stack

- Frontend: Next.js App Router, React, TypeScript
- Backend: FastAPI, SQLAlchemy, Alembic, Uvicorn
- Data services: Python service packages by domain
- Source connectivity: SQLAlchemy engines (psycopg, PyMySQL, SQLite)
- Database: PostgreSQL
- Tooling: npm workspaces, Rush, Docker Compose, pytest, Ruff, ESLint, Vitest

## Quickstart

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env
cp apps/api-gateway/.env.example apps/api-gateway/.env

make setup
make dev
```

In a second terminal:

```bash
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
```

Then open:

- Web app: `http://localhost:3000`
- API docs: `http://localhost:8000/docs`
- API health: `http://localhost:8000/api/v1/health/live`
- System status: `http://localhost:3000/system-status`

## Local setup

For a detailed setup walkthrough, including prerequisites, Docker, migrations, admin bootstrap, and troubleshooting, start here:

- `docs/installation-guide.md`
- `docs/local-setup-guide.md`
- `docs/troubleshooting.md`

## Demo flow

The cleanest reviewer path is:

1. Open `/case-study` for the product and architecture summary.
2. Open `/demo` for the guided walkthrough.
3. Sign in with the bootstrap admin user.
4. Open or create a project.
5. Upload `samples/demo-customers.csv`.
6. Inspect dataset preview and profile.
7. Create a pipeline, preview it, save it, and run it.
8. Compare source versus derived data, open audit pages, and export HTML.
9. Configure a destination or BI connection and run a publish flow.
10. Review notifications, schedules, and `/system-status`.

The step-by-step version lives in `docs/demo-guide.md`.

## Main routes and pages

### Reviewer entry points

- `/case-study`
- `/demo`
- `/system-status`
- `/login`

### Main product routes

- `/projects`
- `/projects/[projectId]`
- `/projects/[projectId]/extraction`
- `/projects/[projectId]/data-quality`
- `/projects/[projectId]/schema-drift`
- `/projects/[projectId]/datasets/[datasetId]`
- `/projects/[projectId]/datasets/[datasetId]/audit`
- `/projects/[projectId]/runs/[runId]/audit`
- `/projects/[projectId]/datasets/[datasetId]/compare/[otherDatasetId]`
- `/projects/[projectId]/tests/saved`
- `/projects/[projectId]/destinations`
- `/projects/[projectId]/bi-connections`
- `/projects/[projectId]/schedules`
- `/projects/[projectId]/notification-targets`
- `/notifications`

## Screens and module overview

- `Projects`: project list and workspace entry point
- `Project workspace`: sources, datasets, and run history
- `Dataset detail`: schema, preview, profile, lineage, suggestions, publish actions
- `Pipelines`: create, preview, save, and run transformation pipelines
- `Audit`: dataset and run audit summaries with HTML export
- `Testing Lab`: comparisons, statistical tests, saved tests, and reruns
- `Destinations`: saved delivery configs and PostgreSQL publish
- `BI connections`: Power BI and Tableau connection management and publish flows
- `Schedules`: cron-based transformation or publish automation with manual trigger
- `Notifications`: in-app outcome tracking and optional external targets
- `System status`: health, module visibility, and scheduler snapshot

## Testing and verification

```bash
make test
make verify
make smoke
```

- `make test`: pytest for backend packages plus web Vitest
- `make verify`: Ruff, pytest bundle, ESLint, TypeScript typecheck, and production web build
- `make smoke`: lightweight environment and API checks for release readiness

## Deployment and CI summary

- `.github/workflows/ci.yml` runs the same verification path as `make verify`
- `docker-compose.yml` provides a development-style local stack
- `docker-compose.prod.yml` provides a production-oriented single-host reference setup
- `apps/web/Dockerfile.prod` builds the web app with `next build` and `next start`
- Alembic migrations run before gateway startup in the documented Docker flows

See `docs/deployment-guide.md` and `docs/release-checklist.md` for details.

## Current limitations

- Ingestion and extraction run synchronously in-process; there is no separate worker tier.
- Schedules use Postgres-backed lease claims, not a full distributed job system.
- External notifications are best-effort email and Slack webhook fan-out.
- S3 and local-export destinations can be saved and tested, but dataset publish is only implemented for PostgreSQL.
- Extraction supports PostgreSQL, MySQL, and SQLite. Other engines (SQL Server, Oracle, Snowflake, BigQuery) are not implemented.
- Data quality rules are evaluated on demand; they are not yet wired as an automatic gate inside scheduled pipeline runs.
- Schema drift is detected and recorded, but it does not automatically halt a run.
- BI publishing is practical first-path support, not full semantic model or workbook lifecycle automation.
- Secrets for saved integrations are encrypted at rest in the application database, but external KMS or Vault integration is not included.

## Why this is stronger than a normal CRUD app

- It coordinates multi-step data workflows rather than only storing records.
- It persists lineage, run history, audits, publish outcomes, and schedule state.
- It demonstrates modular backend boundaries instead of collapsing all logic into one app layer.
- It includes operational surfaces such as notifications, scheduler execution, and system status.
- It ships with setup, verification, deployment, and reviewer documentation that make it easy to evaluate locally.

## Important docs

- `docs/installation-guide.md`
- `docs/local-setup-guide.md`
- `docs/features-guide.md`
- `docs/architecture.md`
- `docs/demo-guide.md`
- `docs/deployment-guide.md`
- `docs/troubleshooting.md`
- `docs/reviewer-quick-summary.md`
- `docs/project-case-study.md`
- `docs/showcase-guide.md`
- `docs/release-checklist.md`
- `docs/agent-context.md`
