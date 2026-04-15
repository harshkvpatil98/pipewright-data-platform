# Architecture Guide

This document explains how the repo is organized, how the major services interact, and why the implementation feels production-style rather than like a toy demo.

## High-level architecture

At runtime, the platform has three primary layers:

1. `apps/web`: a Next.js App Router frontend
2. `apps/api-gateway`: a FastAPI gateway that exposes the public API
3. `services/service-*` and `packages/*`: domain packages and shared platform code used by the gateway

The frontend talks to one API base URL. The gateway owns HTTP concerns, auth boundaries, and route composition. Domain logic stays in service packages such as auth, projects, datasets, ingestion, transformations, destinations, schedules, notifications, comparisons, and pipeline runs.

## Repo structure

```text
apps/
  api-gateway/        FastAPI application, config, Alembic, bootstrap CLI
  web/                Next.js App Router frontend
services/
  service-auth/
  service-projects/
  service-sources/
  service-datasets/
  service-ingestion/
  service-transformations/
  service-pipeline-runs/
  service-comparisons/
  service-destinations/
  service-schedules/
  service-notifications/
packages/
  shared-python/      DB helpers, storage, security, logging, reporting
  shared-types/       Shared TypeScript contracts
  shared-ui/          Shared UI primitives
  config/             Shared frontend tooling config
scripts/              Setup, dev, test, verify, smoke, CI bootstrap
docs/                 Setup, feature, demo, architecture, deploy, reviewer docs
samples/              Demo input files such as demo-customers.csv
```

## Why the modular design is strong

The repo does not place all business logic inside controllers or page handlers. Instead, it keeps domain responsibilities separate:

- `service-auth` handles user auth concerns
- `service-projects` owns project scope
- `service-datasets` owns dataset records and retrieval
- `service-ingestion` owns file processing, profiling, and dataset artifact generation
- `service-transformations` owns preview and persistent pipeline execution
- `service-pipeline-runs` owns run history and execution ledger behavior
- `service-comparisons` owns comparison and statistical testing workflows
- `service-destinations` owns destinations, BI connections, and publish flows
- `service-schedules` owns schedule persistence and due execution
- `service-notifications` owns in-app and external notification behavior

This keeps the gateway lean and makes future extraction into separate deployables easier if the platform ever outgrows the current modular-monolith shape.

## Frontend and backend interaction

### Frontend

`apps/web` is a Next.js application with project-scoped product surfaces. The key implemented pages are:

- `/login`
- `/projects`
- `/projects/[projectId]`
- `/projects/[projectId]/datasets/[datasetId]`
- `/projects/[projectId]/destinations`
- `/projects/[projectId]/bi-connections`
- `/projects/[projectId]/schedules`
- `/projects/[projectId]/notification-targets`
- `/projects/[projectId]/tests/saved`
- `/projects/[projectId]/datasets/[datasetId]/audit`
- `/projects/[projectId]/runs/[runId]/audit`
- `/system-status`
- `/demo`
- `/case-study`

### Backend

`apps/api-gateway` mounts the routers from the service packages behind `/api/v1`. It also exposes:

- health endpoints
- status endpoints
- internal schedule execution endpoints when configured
- OpenAPI docs at `/docs`

### Shared contracts

`packages/shared-types` provides typed payload contracts used by the frontend. This reduces drift between API responses and UI expectations.

## Data flow through the platform

### 1. Ingestion

When a user uploads a dataset:

- the gateway authenticates the user
- project ownership is checked
- a `pipeline_run` is created with `run_type=dataset_ingestion`
- the raw file is stored through the storage abstraction
- the file is parsed
- preview, schema, and profile data are generated
- the dataset row is updated with artifact and profiling metadata
- the run is marked succeeded or failed with structured summary and logs

### 2. Transformation preview

Preview uses the same parsing and transformation logic as execution, but it runs in memory only and does not persist a derived dataset or `pipeline_run`.

### 3. Transformation run

Running a saved pipeline:

- loads the saved pipeline definition
- reads the base dataset artifact
- applies the configured transformation steps
- stores the result as a derived dataset artifact
- writes a new dataset row with lineage fields
- records a `pipeline_run`

### 4. Review workflows

After ingestion or transformation, users can inspect:

- dataset preview and profile
- transformation suggestions
- dataset and run audit pages
- dataset comparison and run comparison
- saved statistical tests and rerun history

### 5. Downstream publish

From dataset detail, users can publish to:

- PostgreSQL
- Power BI
- Tableau

Each publish flow is tracked through the same run history model.

### 6. Scheduling and notifications

Saved schedules can trigger:

- transformation pipeline runs
- PostgreSQL publish operations

Schedule outcomes feed notifications and appear in status surfaces.

## Storage and persistence

### PostgreSQL

PostgreSQL stores:

- users
- projects
- sources
- datasets
- transformation pipelines
- pipeline runs
- destinations and BI connections
- schedules
- notifications
- saved tests and test run history

Alembic manages schema migrations from `apps/api-gateway`.

### File storage

Uploaded and derived dataset artifacts are stored through the shared storage abstraction in `packages/shared-python`. The current runtime backend is local filesystem storage. This is why the app can persist artifact-based workflows without storing raw files directly in the database.

## Scheduling, notifications, and publishing in the architecture

### Scheduling

`service-schedules` stores schedule definitions and runtime metadata such as due times, retry state, and lease ownership fields. Automatic due execution can be triggered through:

- the internal API
- the `run-due-schedules` CLI

### Notifications

`service-notifications` supports:

- in-app notifications per user
- optional external targets for email and Slack webhook delivery

This is useful because operational outcomes stay visible in the product instead of disappearing into logs only.

### Publishing

`service-destinations` owns both delivery destinations and BI connections. That keeps downstream delivery logic in one coherent integration boundary.

## Why this feels production-style

- It models real workflow state, not just page-level form submissions.
- It keeps bounded contexts separate behind one gateway.
- It uses shared contracts and shared infrastructure packages.
- It includes migrations, env templates, CI verification, smoke checks, and deployment docs.
- It includes operational surfaces such as status, schedules, publish runs, and notifications.
- It is honest about current limitations instead of pretending unfinished distributed concerns are solved.

## Honest limitations

- Ingestion is synchronous and in-process.
- Scheduler safety is lease-based in Postgres, not a full distributed orchestration platform.
- Local filesystem storage is the default backend.
- External notification delivery is best-effort.
- BI support is practical publish-first functionality, not full BI administration.

## Related docs

- `docs/features-guide.md`
- `docs/demo-guide.md`
- `docs/deployment-guide.md`
- `docs/reviewer-quick-summary.md`
- `docs/agent-context.md`
