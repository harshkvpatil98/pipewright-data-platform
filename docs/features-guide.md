# Features Guide

This guide describes the features that are actually implemented in the current codebase. It is written for reviewers, collaborators, and local users who want a truthful map of the platform.

## Platform core

### What it does

The platform provides a project-scoped workspace for authenticated users. Most meaningful workflows live under `/projects/[projectId]`, including datasets, transformations, delivery, testing, schedules, and notifications.

### Why it matters

This keeps the app focused on owned data workflows instead of treating everything as a flat global admin dashboard.

### Key routes and APIs

- Web: `/login`, `/projects`, `/projects/[projectId]`
- API: `POST /api/v1/auth/login`, `GET /api/v1/auth/me`, `GET /api/v1/projects`, `POST /api/v1/projects`

## Auth and project scoping

### What it does

- JWT login is implemented.
- Project ownership is enforced for project-scoped resources.
- A bootstrap CLI creates the first local user.

### Why it matters

This demonstrates real access boundaries and local environment setup beyond a hardcoded demo login.

### Notes

- There is no self-service signup flow.
- The practical local flow is `platform-bootstrap-user`, then `/login`.

## Ingestion and profiling

### What it does

- Uploads `csv`, `xlsx`, and `json` files
- Validates file type and size
- Persists dataset metadata
- Generates schema, preview, and profile data
- Records a `dataset_ingestion` pipeline run

### Why it matters

The platform does more than store file references. It turns uploaded data into inspectable dataset records that can drive downstream workflows.

### Key routes and APIs

- Web: `/projects/[projectId]/datasets/[datasetId]`
- API: `POST /api/v1/projects/{project_id}/datasets/upload`
- API: `GET /api/v1/projects/{project_id}/datasets/{dataset_id}`
- API: `GET /api/v1/projects/{project_id}/datasets/{dataset_id}/preview`
- API: `GET /api/v1/projects/{project_id}/datasets/{dataset_id}/profile`

## Transformation pipelines

### What it does

- Creates and edits saved transformation pipelines
- Supports preview before persistence
- Runs saved pipelines against base datasets
- Produces derived datasets and tracked run history

### Supported step types

- `rename_columns`
- `cast_column_types`
- `trim_strings`
- `drop_columns`
- `select_columns`
- `fill_nulls`
- `drop_null_rows`
- `remove_duplicates`
- `filter_rows`
- `parse_dates`

### Why it matters

This turns one-off cleanup actions into reusable, inspectable workflow definitions.

### Key routes and APIs

- Web: `/projects/[projectId]/datasets/[datasetId]/pipelines/[pipelineId]`
- API: `POST /api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines`
- API: `POST /api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines/preview`
- API: `PATCH /api/v1/projects/{project_id}/pipelines/{pipeline_id}`
- API: `POST /api/v1/projects/{project_id}/pipelines/{pipeline_id}/run`

## Derived datasets and lineage

### What it does

- Stores parent-child relationships between source and transformed datasets
- Links datasets back to their originating pipeline and run
- Exposes compare-with-parent style workflow paths

### Why it matters

Lineage is part of the real product story here. It helps reviewers see that the project models data evolution, not just file uploads.

### Key routes and APIs

- Web: `/projects/[projectId]/datasets/[datasetId]`
- API: derived dataset data is surfaced through dataset and run endpoints

## Audit and export

### What it does

- Builds read-only audit summaries for datasets and runs
- Supports HTML export for both dataset audit and run audit

### Why it matters

This gives the platform a reviewer-friendly evidence layer for what happened during ingestion, transformation, and publish workflows.

### Important limitation

Audit export is HTML only. PDF generation is not implemented.

### Key routes and APIs

- Web: `/projects/[projectId]/datasets/[datasetId]/audit`
- Web: `/projects/[projectId]/runs/[runId]/audit`
- API: `GET /api/v1/projects/{project_id}/datasets/{dataset_id}/audit`
- API: `GET /api/v1/projects/{project_id}/datasets/{dataset_id}/audit/export?format=html`
- API: `GET /api/v1/projects/{project_id}/runs/{run_id}/audit`
- API: `GET /api/v1/projects/{project_id}/runs/{run_id}/audit/export?format=html`

## Comparisons and Testing Lab

### What it does

- Compares one dataset to another
- Compares run outputs
- Runs statistical tests between datasets
- Saves test definitions and rerun history

### Implemented statistical tests

- Welch t-test
- Two-proportion z-test
- Chi-square distribution test

### Why it matters

This is one of the clearest signals that the project is more than CRUD. It includes validation and review workflows that analysts and engineers would actually use.

### Key routes and APIs

- Web: `/projects/[projectId]/datasets/[datasetId]/compare/[otherDatasetId]`
- Web: `/projects/[projectId]/runs/[runId]/comparison`
- Web: `/projects/[projectId]/tests/saved`
- API: `GET /api/v1/projects/{project_id}/datasets/{left_dataset_id}/compare/{right_dataset_id}`
- API: `POST /api/v1/projects/{project_id}/datasets/{left_dataset_id}/tests/{right_dataset_id}`
- API: `GET /api/v1/projects/{project_id}/runs/{run_id}/comparison`
- API: saved test CRUD and rerun endpoints under `/api/v1/projects/{project_id}/tests/saved`

## Destinations and PostgreSQL publish

### What it does

- Stores and tests destination configs for `postgres`, `s3`, and `local_export`
- Publishes datasets to PostgreSQL with `replace` or `append`
- Tracks publish outcomes as persisted runs

### Why it matters

It shows the platform is designed for delivery, not just internal storage.

### Important limitation

Actual dataset publish is implemented for PostgreSQL only. S3 and local export can be configured and tested, but they are not implemented as dataset publish targets.

### Key routes and APIs

- Web: `/projects/[projectId]/destinations`
- API: `GET|POST /api/v1/projects/{project_id}/destinations`
- API: `POST /api/v1/projects/{project_id}/destinations/{destination_id}/test`
- API: `POST /api/v1/projects/{project_id}/datasets/{dataset_id}/publish/postgres`

## BI connections and publishing

### What it does

- Stores Power BI and Tableau connection records
- Tests connections and fetches metadata
- Publishes datasets to Power BI and Tableau using saved connections

### Why it matters

This expands the project from an internal pipeline demo into a downstream analytics delivery platform.

### Important limitation

These are practical first-path publishing flows. The repo does not implement full BI administration, workbook lifecycle management, or semantic model governance.

### Key routes and APIs

- Web: `/projects/[projectId]/bi-connections`
- API: `GET|POST /api/v1/projects/{project_id}/bi-connections`
- API: `POST /api/v1/projects/{project_id}/bi-connections/{connection_id}/test`
- API: `GET /api/v1/projects/{project_id}/bi-connections/{connection_id}/metadata`
- API: `POST /api/v1/projects/{project_id}/datasets/{dataset_id}/publish/power-bi`
- API: `POST /api/v1/projects/{project_id}/datasets/{dataset_id}/publish/tableau`

## Schedules, retries, and notifications

### What it does

- Stores schedules for transformation runs and PostgreSQL publish
- Supports cron expressions, enable or disable, and manual trigger
- Runs due schedules through an internal API or CLI
- Tracks schedule outcomes and notifications

### Why it matters

Operational workflow is a major differentiator for the project. Users can see how the platform behaves after the initial happy-path button click.

### Important limitation

Schedule coordination is lease-based in Postgres, not a full distributed scheduler. Retry behavior exists, but this repo is not trying to be a full orchestration engine.

### Key routes and APIs

- Web: `/projects/[projectId]/schedules`
- Web: `/projects/[projectId]/notification-targets`
- Web: `/notifications`
- API: `/api/v1/projects/{project_id}/schedules`
- API: `POST /api/v1/projects/{project_id}/schedules/{schedule_id}/trigger-now`
- API: `POST /internal/schedules/run-due-once`
- API: `GET /api/v1/notifications`
- API: notification target CRUD under `/api/v1/projects/{project_id}/notification-targets`

## System status and release tooling

### What it does

- Exposes API liveness and readiness endpoints
- Exposes a platform status endpoint with service rows and scheduler snapshot
- Provides smoke, test, and verify scripts for local and CI use
- Includes CI, Compose, and deployment docs

### Why it matters

It makes the repo easier to review and run, and it reinforces the production-style packaging story.

### Key routes and APIs

- Web: `/system-status`
- API: `GET /api/v1/health/live`
- API: `GET /api/v1/health/ready`
- API: `GET /api/v1/status`
- API: `GET /api/v1/status/services`

## Important truthfulness notes

- Several top-level pages such as `/pipelines`, `/audits`, `/testing`, `/integrations`, and `/settings` are present as planned or placeholder surfaces. The implemented workflow is primarily project-scoped under `/projects/[projectId]/...`.
- Source records are metadata registrations, not full external source connector sync jobs.
- There is no self-service user management flow.
