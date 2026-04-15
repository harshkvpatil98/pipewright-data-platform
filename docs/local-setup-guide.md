# Local Setup Guide

This guide is optimized for recruiters, reviewers, and engineers who want the shortest accurate path from clone to a working demo.

## Recommended command order

Run these commands from the repo root in this exact order.

## 1. Copy environment files

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env
cp apps/api-gateway/.env.example apps/api-gateway/.env
```

What this does:

- creates local env files without modifying the example templates

Before moving on, set `APP_SECRET_ENCRYPTION_KEY` in `apps/api-gateway/.env`.

## 2. Install dependencies and bootstrap the repo

```bash
make setup
```

What this does:

- installs JavaScript dependencies
- creates `.venv`
- installs editable Python packages for the gateway and services
- starts Docker Postgres when Docker is reachable
- runs Alembic migrations when the database is up

Expected result:

- `.venv/` exists
- Docker Postgres is up if Docker is running
- the command ends with a message telling you to run `make dev`

## 3. Start PostgreSQL if it is not already running

```bash
docker compose up -d postgres
```

What this does:

- starts only the database container

Expected result:

- `docker compose ps` shows `postgres` as running or healthy

## 4. Apply migrations if needed

```bash
source .venv/bin/activate
alembic -c apps/api-gateway/alembic.ini upgrade head
```

What this does:

- upgrades the local database schema to the latest Alembic revision

Expected result:

- Alembic finishes without error

## 5. Create the local admin user

```bash
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
```

What this does:

- creates the initial login user for the platform

Expected result:

- a success message confirming the created username and role

## 6. Start the app stack

```bash
make dev
```

What this does:

- validates the local env files
- checks Postgres connectivity
- applies migrations again for safety
- starts the API gateway on `localhost:8000`
- starts the Next.js frontend on `localhost:3000`

Expected result:

- the API becomes available on `http://localhost:8000`
- the web app becomes available on `http://localhost:3000`

## URLs to open

- `http://localhost:3000/login`
- `http://localhost:3000/case-study`
- `http://localhost:3000/demo`
- `http://localhost:3000/projects`
- `http://localhost:3000/system-status`
- `http://localhost:8000/docs`
- `http://localhost:8000/api/v1/health/live`
- `http://localhost:8000/api/v1/status`

## How to verify the full stack

### Health check

Open:

- `http://localhost:8000/api/v1/health/live`
- `http://localhost:8000/api/v1/status`

You should get JSON responses from both endpoints.

### App login check

1. Open `http://localhost:3000/login`.
2. Sign in with the bootstrap credentials from root `.env`.
3. Confirm you land on `/projects`.

### Product flow check

1. Open `/case-study`.
2. Open `/demo`.
3. Open `/projects`.
4. Create a project if none exists.
5. Upload `samples/demo-customers.csv`.
6. Open the dataset detail page and confirm preview and profile sections load.

### Release-style check

Run:

```bash
make smoke
```

For the full verification bundle:

```bash
make verify
```

## Recommended reviewer walkthrough

Use this order:

1. `/case-study`
2. `/demo`
3. `/login`
4. `/projects`
5. upload `samples/demo-customers.csv`
6. dataset detail
7. pipeline preview and run
8. audit and compare flows
9. publish flow
10. schedules, notifications, and `/system-status`

## How to use the reviewer-facing pages

### `/demo`

Use this page as the guided product map. It is presentation-oriented and helps reviewers find the main workflows quickly.

### `/case-study`

Use this page as the concise business and technical framing for the project.

### `/system-status`

Use this page to verify the gateway, scheduler snapshot, and service-level status surface without needing to inspect logs first.

## If login does not work

Run the bootstrap command again and make sure you loaded the root `.env` first:

```bash
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
```

## If the web app cannot reach the API

Check:

- `apps/web/.env`
- `apps/api-gateway/.env`
- the API is running on `localhost:8000`

Then restart `make dev`.

For deeper fixes, use `docs/troubleshooting.md`.
