# Installation Guide

This guide is the safest first read if you are new to the repo. It assumes you want to run the full platform locally with the web app on `localhost:3000`, the API on `localhost:8000`, and PostgreSQL in Docker.

## What you need first

Install these tools before running any project commands:

- Node.js `22.x`
- npm `10+`
- Python `3.11+`
- Docker Desktop or Docker Engine with `docker compose`

CI is currently verified on Node `22` and Python `3.11`. The project also runs locally on newer Python versions as long as they satisfy `>=3.11`.

## Step 1: Clone and enter the repo

```bash
git clone <your-repo-url>
cd etl-software
```

If you already have the code locally, just `cd` into the repo root.

## Step 2: Create environment files

Copy the provided templates:

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env
cp apps/api-gateway/.env.example apps/api-gateway/.env
```

These files are for local development and should not be committed with real secrets.

## Step 3: Review the required local settings

### Root `.env`

The root file controls local ports, Postgres defaults, and bootstrap credentials:

- `FRONTEND_PORT`
- `BACKEND_PORT`
- `POSTGRES_PORT`
- `POSTGRES_DB`
- `POSTGRES_USER`
- `POSTGRES_PASSWORD`
- `AUTH_BOOTSTRAP_USERNAME`
- `AUTH_BOOTSTRAP_PASSWORD`

The defaults are good enough for a first local run.

### `apps/web/.env`

The important values are:

- `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000/api/v1`
- `API_INTERNAL_BASE_URL=http://localhost:8000/api/v1`

These defaults are already correct for a local setup where the API runs on port `8000`.

### `apps/api-gateway/.env`

Check these values before starting:

- `DATABASE_URL=postgresql+psycopg://platform:platform@localhost:5432/platform`
- `BACKEND_CORS_ORIGINS=["http://localhost:3000","http://web:3000"]`
- `AUTH_JWT_SECRET`
- `AUTH_JWT_ISSUER`
- `AUTH_JWT_AUDIENCE`
- `APP_SECRET_ENCRYPTION_KEY`

## Step 4: Generate the encryption key

`APP_SECRET_ENCRYPTION_KEY` is required if you want to save or update destinations, BI connections, or Slack webhook notification targets.

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Paste the generated value into:

- `apps/api-gateway/.env`

Example:

```bash
APP_SECRET_ENCRYPTION_KEY=your-generated-key-here
```

If you skip this step, the gateway will refuse those configuration saves with a clear misconfiguration error.

## Step 5: Run the automated setup

From the repo root:

```bash
make setup
```

What this does:

- copies missing env files if needed
- installs root JavaScript dependencies
- runs Rush install for workspace packages
- creates `.venv`
- installs the shared Python package and all service packages in editable mode
- installs the API gateway in editable mode with dev dependencies
- starts Docker Postgres if Docker is available
- runs Alembic migrations automatically when Docker Postgres is reachable

## Step 6: Confirm PostgreSQL is running

If `make setup` could not reach Docker, start Postgres manually:

```bash
docker compose up -d postgres
```

You can check status with:

```bash
docker compose ps
```

You want the `postgres` service to be healthy before starting the API.

## Step 7: Run migrations manually if needed

If setup did not run migrations, apply them yourself:

```bash
source .venv/bin/activate
alembic -c apps/api-gateway/alembic.ini upgrade head
```

Run this from the repo root after the database is available.

## Step 8: Create the bootstrap admin user

Load the root bootstrap credentials and create the first account:

```bash
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
```

If successful, the command prints:

```text
Created user '<username>' with role 'admin'.
```

## Step 9: Start the full stack

Run:

```bash
make dev
```

This script:

- ensures env files exist
- starts Docker Postgres if possible
- checks the database port from root `.env`
- applies Alembic migrations
- starts the FastAPI gateway on `BACKEND_PORT`
- starts the Next.js app on `FRONTEND_PORT`

## Step 10: Open the local URLs

After startup, open:

- Web app: `http://localhost:3000`
- Login page: `http://localhost:3000/login`
- Demo page: `http://localhost:3000/demo`
- Case study page: `http://localhost:3000/case-study`
- System status page: `http://localhost:3000/system-status`
- API docs: `http://localhost:8000/docs`
- API live health: `http://localhost:8000/api/v1/health/live`
- API status: `http://localhost:8000/api/v1/status`

## Step 11: Sign in

Use the same bootstrap credentials you created in Step 8:

- username: value from `AUTH_BOOTSTRAP_USERNAME`
- password: value from `AUTH_BOOTSTRAP_PASSWORD`

There is no self-service signup flow in this repo. Local access starts with the bootstrap CLI.

## Step 12: Verify the platform is healthy

Run:

```bash
make smoke
```

And for a full verification pass:

```bash
make verify
```

## If something fails

Start here:

- `docs/local-setup-guide.md` for the normal local run order
- `docs/troubleshooting.md` for targeted fixes
- `docs/demo-guide.md` if setup succeeds but you want a guided walkthrough

Quick recovery commands:

```bash
docker compose up -d postgres
source .venv/bin/activate
alembic -c apps/api-gateway/alembic.ini upgrade head
make dev
```
