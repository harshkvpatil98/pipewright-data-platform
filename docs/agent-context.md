# Agent Context

This file is a high-signal snapshot for future contributors and coding agents. It should stay aligned with the implemented product surface and docs set.

## Current repo story

The project is a modular internal ETL and data operations platform. The strongest implemented workflow is project-scoped:

1. sign in
2. open a project
3. upload a dataset
4. inspect schema, preview, and profile
5. create or preview a transformation pipeline
6. run the pipeline to produce a derived dataset
7. review audits, comparisons, or saved tests
8. publish downstream
9. schedule recurring work
10. inspect notifications and system status

## Architecture snapshot

- `apps/web`: Next.js frontend
- `apps/api-gateway`: FastAPI gateway and Alembic entry point
- `services/service-*`: bounded domain packages
- `packages/shared-python`: shared backend infrastructure
- `packages/shared-types`: shared frontend/backend contracts
- `packages/shared-ui`: shared UI primitives

The backend is intentionally a modular monolith: one deployable gateway, many domain packages.

## Implemented domains

- auth and bootstrap user flow
- projects and owned workspace resources
- dataset ingestion for `csv`, `xlsx`, and `json`
- persisted preview, schema, profile, and run history
- transformation preview and saved pipeline run execution
- derived datasets and lineage
- dataset audit and run audit with HTML export
- dataset comparison, run comparison, statistical tests, and saved tests
- destination configs plus PostgreSQL publish
- Power BI and Tableau connection and publish flows
- schedules, due execution hooks, and notifications
- system status, health endpoints, smoke checks, and CI-parity verification

## Routes worth steering people toward

### Best reviewer routes

- `/case-study`
- `/demo`
- `/login`
- `/projects`
- `/system-status`

### Best implemented product routes

- `/projects/[projectId]`
- `/projects/[projectId]/datasets/[datasetId]`
- `/projects/[projectId]/datasets/[datasetId]/audit`
- `/projects/[projectId]/runs/[runId]/audit`
- `/projects/[projectId]/tests/saved`
- `/projects/[projectId]/destinations`
- `/projects/[projectId]/bi-connections`
- `/projects/[projectId]/schedules`
- `/projects/[projectId]/notification-targets`
- `/notifications`

## Routes that need careful wording

Top-level navigation includes some planned or placeholder pages such as:

- `/pipelines`
- `/audits`
- `/testing`
- `/integrations`
- `/settings`

Do not describe those as the primary implemented workflow surface. Most real functionality is project-scoped.

## Environment facts

- root `.env` controls local ports and bootstrap credentials
- `apps/web/.env` controls browser and server-side API base URLs
- `apps/api-gateway/.env` controls DB, JWT, CORS, storage, scheduler, and encryption settings
- `APP_SECRET_ENCRYPTION_KEY` is required to save or update destinations, BI connections, and Slack webhook targets

## Operational facts

- `make setup` bootstraps dependencies and usually migrations
- `make dev` starts the local stack
- `make test` runs pytest plus web tests
- `make verify` is the CI-parity verification command
- `make smoke` is the lightweight release-readiness check
- GitHub Actions mirrors `make verify`

## Guardrails for future edits

- do not collapse service boundaries into the gateway
- do not invent features in docs that are not implemented
- do not present placeholder top-level pages as completed modules
- do not claim S3 or local export are implemented dataset publish targets
- do not claim a full distributed scheduler
- keep docs aligned with env templates and scripts when changing setup behavior

## Best supporting docs

- `README.md`
- `docs/installation-guide.md`
- `docs/local-setup-guide.md`
- `docs/features-guide.md`
- `docs/architecture.md`
- `docs/demo-guide.md`
- `docs/deployment-guide.md`
- `docs/troubleshooting.md`
- `docs/reviewer-quick-summary.md`
