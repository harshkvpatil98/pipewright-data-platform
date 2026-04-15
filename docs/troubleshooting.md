# Troubleshooting Guide

Use this guide when local setup or demo prep fails. Each section focuses on a concrete issue you are likely to hit while running the repo locally.

## Wrong Node version

### Symptoms

- `npm install` fails
- Next.js commands behave unexpectedly
- CI parity differs from your machine

### What to check

```bash
node -v
npm -v
```

### Expected

- Node `22.x`
- npm `10+`

### Fix

Install or switch to Node `22`, then rerun:

```bash
npm install
make setup
```

## Wrong Python version

### Symptoms

- `make setup` fails during pip install
- virtualenv creation works but package install fails

### What to check

```bash
python3 --version
```

### Expected

- Python `3.11+`

### Fix

Install Python `3.11` or newer, remove the broken venv if needed, then rerun:

```bash
rm -rf .venv
make setup
```

## Docker or PostgreSQL not running

### Symptoms

- `make dev` exits with Postgres not reachable
- migrations fail with connection errors
- API cannot start

### What to check

```bash
docker info
docker compose ps
```

### Fix

Start only the database first:

```bash
docker compose up -d postgres
```

Then rerun migrations:

```bash
source .venv/bin/activate
alembic -c apps/api-gateway/alembic.ini upgrade head
```

## Migration failures

### Symptoms

- Alembic fails during `make setup` or `make dev`
- the API starts but schema-dependent pages fail later

### What to check

```bash
source .venv/bin/activate
alembic -c apps/api-gateway/alembic.ini current
alembic -c apps/api-gateway/alembic.ini upgrade head
```

### Common causes

- Postgres is not running
- `DATABASE_URL` is wrong
- your local database was created with an old schema state

### Fix

Confirm the database is reachable and `DATABASE_URL` matches your Postgres container or instance.

## Env var issues

### Symptoms

- web app cannot call the API
- login fails even though the API is running
- CORS errors appear in the browser

### What to check

Files:

- `.env`
- `apps/web/.env`
- `apps/api-gateway/.env`

Important values:

- `FRONTEND_PORT`
- `BACKEND_PORT`
- `NEXT_PUBLIC_API_BASE_URL`
- `API_INTERNAL_BASE_URL`
- `BACKEND_CORS_ORIGINS`
- `DATABASE_URL`

### Fix

Use the provided examples as your base:

```bash
cp .env.example .env
cp apps/web/.env.example apps/web/.env
cp apps/api-gateway/.env.example apps/api-gateway/.env
```

Then reapply your intended local values.

## Missing or invalid `APP_SECRET_ENCRYPTION_KEY`

### Symptoms

- saving a destination fails
- saving a BI connection fails
- saving a Slack webhook notification target fails
- the API returns a misconfiguration error

### Fix

Generate a Fernet key:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Set it in:

- `apps/api-gateway/.env`

Then restart the API.

## Bootstrap user or login issues

### Symptoms

- you cannot sign in
- login returns unauthorized
- you are unsure whether a user exists locally

### Fix

Recreate the bootstrap admin user:

```bash
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
```

Then sign in at:

- `http://localhost:3000/login`

## Web app cannot reach the API

### Symptoms

- the web UI loads but API-backed pages fail
- `/system-status` or `/projects` errors out

### What to check

- API responds at `http://localhost:8000/api/v1/health/live`
- `apps/web/.env` points to `http://localhost:8000/api/v1`
- `apps/api-gateway/.env` includes `http://localhost:3000` in `BACKEND_CORS_ORIGINS`

### Fix

Restart the stack after correcting env files:

```bash
make dev
```

## Scheduler token or internal API issues

### Symptoms

- internal schedule execution routes return unauthorized or unavailable
- due schedules do not run through the internal API

### What to check

- `SCHEDULER_INTERNAL_TOKEN` is set in `apps/api-gateway/.env`
- requests send the `X-Internal-Token` header

### Notes

If the token is not set, internal schedule routes intentionally return a configuration error.

## BI or destination test issues

### Symptoms

- destination test fails
- BI connection test fails
- publish workflows fail before sending data

### Common causes

- missing `APP_SECRET_ENCRYPTION_KEY`
- invalid external credentials
- target service not reachable from your machine

### Fix

Check:

- local encryption key is configured
- saved credentials are correct
- any required workspace, project, tenant, or server identifiers are valid

For local demo sessions without external access, it is acceptable to show the configuration UI and explain that real credentials are required for live publish success.

## Rush or dependency setup issues

### Symptoms

- workspace installs look inconsistent
- shared packages fail to resolve

### Fix

Run the repo’s intended setup path again:

```bash
make setup
```

If needed, refresh JavaScript dependencies:

```bash
npm install
./scripts/rush.sh install
```

## Local path or filesystem issues

### Symptoms

- uploads fail to persist locally
- file-backed dataset reads fail

### What to check

- `UPLOAD_ROOT_PATH` in `apps/api-gateway/.env`
- whether the configured path is writable on your machine

### Default local value

```text
UPLOAD_ROOT_PATH=data/uploads
```

### Fix

Use the default local path unless you have a reason to change it. If you changed it, point it at a writable directory and restart the API.

## Smoke-check shortcuts

If you only want a quick sanity check:

```bash
make smoke
```

If the app is not running and you only want file and env hints:

```bash
SMOKE_SKIP_NETWORK=1 ./scripts/smoke-test.sh
```

## When in doubt

Use this recovery path:

```bash
docker compose up -d postgres
source .venv/bin/activate
alembic -c apps/api-gateway/alembic.ini upgrade head
make dev
```
