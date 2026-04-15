# Deployment Guide

This guide explains how to package and run the platform outside day-to-day local development. It is intentionally practical and honest: the repo includes a strong single-host or demo deployment story, but it is not pretending to ship a full multi-cloud platform stack.

## Deployment models supported by the repo

### Local or demo deployment

Best for:

- local evaluation
- recruiter demos
- reviewer walkthroughs
- single-machine testing

Main files:

- `docker-compose.yml`
- `apps/api-gateway/.env.example`
- `apps/web/.env.example`

### Production-oriented single-host reference deployment

Best for:

- polished portfolio packaging
- single-host server deployment
- demonstration of production-minded repo readiness

Main files:

- `docker-compose.prod.yml`
- `apps/api-gateway/.env.production.example`
- `apps/web/.env.production.example`
- `apps/web/Dockerfile.prod`

## Runtime architecture

The deployed flow is:

1. browser requests hit the Next.js app
2. the Next.js app calls the FastAPI gateway
3. the gateway uses PostgreSQL and local filesystem storage
4. domain logic is executed by the imported service packages inside the gateway process

This keeps the runtime simple while preserving modular code boundaries.

## Environment files

### Web

For production-style web deployment, copy:

```bash
cp apps/web/.env.production.example apps/web/.env
```

Important values:

- `NEXT_PUBLIC_API_BASE_URL`
- `API_INTERNAL_BASE_URL`
- optional `NEXT_PUBLIC_APP_VERSION`
- optional `NEXT_PUBLIC_GIT_SHA`
- optional `NEXT_PUBLIC_BUILD_DATE`

### API gateway

Copy:

```bash
cp apps/api-gateway/.env.production.example apps/api-gateway/.env
```

Important values:

- `DATABASE_URL`
- `AUTH_JWT_SECRET`
- `AUTH_JWT_ISSUER`
- `AUTH_JWT_AUDIENCE`
- `BACKEND_CORS_ORIGINS`
- `APP_SECRET_ENCRYPTION_KEY`
- `STORAGE_BACKEND`
- `UPLOAD_ROOT_PATH`
- optional `SCHEDULER_INTERNAL_TOKEN`
- optional `SCHEDULER_RUNTIME_ID`
- optional `SCHEDULER_CLAIM_TTL_SECONDS`

### Root `.env`

If you are using Docker Compose with port and Postgres defaults, copy:

```bash
cp .env.example .env
```

## Required secrets and sensitive config

Do not deploy with the example secrets unchanged.

Set strong values for:

- `AUTH_JWT_SECRET`
- database credentials
- `APP_SECRET_ENCRYPTION_KEY`
- optional `SCHEDULER_INTERNAL_TOKEN`

`APP_SECRET_ENCRYPTION_KEY` is required for encrypted storage of sensitive destination, BI, and Slack webhook fields. Rotating it without re-saving stored configs will invalidate previously encrypted values.

## Database and migrations

PostgreSQL is required.

Run migrations before serving traffic:

```bash
source .venv/bin/activate
alembic -c apps/api-gateway/alembic.ini upgrade head
```

The documented Compose flows already run `upgrade head` before starting Uvicorn.

## Production-oriented Docker Compose flow

Prepare env files:

```bash
cp .env.example .env
cp apps/api-gateway/.env.production.example apps/api-gateway/.env
cp apps/web/.env.production.example apps/web/.env
```

Set real values, then run:

```bash
docker compose -f docker-compose.prod.yml up --build
```

## Startup order

The healthy order is:

1. PostgreSQL
2. API gateway migrations
3. API gateway process
4. web app process

This matches the repo’s Compose setup.

## What to verify after deployment

### API checks

Open:

- `/api/v1/health/live`
- `/api/v1/health/ready`
- `/api/v1/status`

### Web checks

Open:

- `/login`
- `/case-study`
- `/demo`
- `/projects`
- `/system-status`

### Workflow checks

Confirm:

- login works
- project pages load
- sample upload works if demo data is available
- system status loads

### Release checks

From a checked-out repo, run:

```bash
make smoke
make verify
```

Use `SMOKE_API_ROOT` if the API is not exposed on `http://localhost:8000`.

## Scheduler deployment notes

The platform supports automatic due schedule execution, but the implementation is intentionally modest.

If you use automatic schedule execution:

- set `SCHEDULER_INTERNAL_TOKEN`
- give each poller a stable `SCHEDULER_RUNTIME_ID`
- tune `SCHEDULER_CLAIM_TTL_SECONDS` to fit your longest expected schedule run

Important limitation:

- schedule coordination is lease-based in Postgres, not a full distributed job system with leader election or Redis locks

## CI summary

GitHub Actions runs:

1. `npm ci`
2. `scripts/ci-bootstrap-python-venv.sh`
3. `scripts/verify-release.sh`

That means local `make verify` is the main CI-parity command.

## Honest limitations

- The deployment docs support single-host and repo-contained packaging well.
- The repo does not include cloud IaC, secret-manager integration, bundled APM, or distributed scheduler infrastructure.
- Ingestion is synchronous.
- Default storage is local filesystem storage unless you extend the storage backend story.

## Recommended docs to keep nearby

- `docs/release-checklist.md`
- `docs/troubleshooting.md`
- `docs/local-setup-guide.md`
