# Operations runbook

Day-two operations: upgrading, backing up and restoring, scaling, sizing, and
watching the platform. For a first deployment see
[`deployment-guide.md`](deployment-guide.md); for identity see
[`enterprise-identity.md`](enterprise-identity.md).

## Upgrading

Schema is migrated *before* new code serves traffic, so an upgrade is safe to
run in place.

- **Helm:** `helm upgrade pipewright deploy/helm/pipewright --set image.tag=vX.Y.Z`.
  A pre-upgrade Job runs `alembic upgrade head`; if it fails the release is
  blocked and the old pods keep serving.
- **Compose:** `PIPEWRIGHT_TAG=vX.Y.Z docker compose -f docker-compose.prod.yml up -d`.
  The gateway container runs `alembic upgrade head` on start before `uvicorn`.

Migrations are additive and ordered (Alembic, single head). Roll back code by
redeploying the previous tag; roll back schema only with a tested down-migration
or a restore (below) — a forward-only fix is usually safer than a down-migration
against live data.

## Backup and restore

A backup nobody has restored is a hope. `scripts/backup.sh` does both halves —
it dumps, and `--verify` restores the dump into a scratch database and counts
the rows.

```sh
# Dump the database and the uploads directory into ./backups.
DATABASE_URL=… scripts/backup.sh

# Dump AND prove it restores. Run this on a schedule, not just once.
DATABASE_URL=… scripts/backup.sh --verify
```

The dump is Postgres custom-format (`pg_dump --format=custom`); restore with:

```sh
pg_restore --no-owner --clean --if-exists --dbname="$DATABASE_URL" backups/<stamp>.dump
```

Uploaded files live under `UPLOAD_ROOT_PATH` (default `data/uploads`) and are
archived alongside the dump; restore them by unpacking the archive into the same
path. With `STORAGE_BACKEND=s3` they live in a bucket instead; back it up with
the provider's tooling (versioning or replication).

**Drill it.** A restore you have never run is not a restore. Schedule
`backup.sh --verify` (it exits non-zero if the restored row counts are empty)
and alert on failure.

## Scaling

| Component | Scale by | Notes |
| --- | --- | --- |
| Gateway | replicas / HPA | Stateless once stored files are shared: `STORAGE_BACKEND=s3` (a bucket), or one `ReadWriteMany` volume (`storage.persistence`). Scale on CPU. `gateway.autoscaling.enabled=true`. |
| Web | replicas / HPA | Stateless; scale on CPU. |
| Workflow worker | replicas | The queue claim is leased, so many workers share load safely. It also does the long work the pages hand over: uploads over 25MB, deliveries over 50,000 rows and database copies. A project has at most `PROJECT_RUNS_AT_ONCE` runs going at once (4, all kinds together; a project can set its own); the worker takes a person's runs before scheduled ones and backfills, and skips a project at its limit. On Linux it caps its own address space at twice `RUN_MEMORY_LIMIT_MB` plus 2GB, so a run that tries to take more fails with the reason instead of the worker dying (`WORKER_ADDRESS_SPACE_CAP=false` turns that off). |
| Schedule ticker | **one**, usually | The lease reduces but does not eliminate double-execution across pollers. Run one replica, or give each a distinct `SCHEDULER_RUNTIME_ID`. A due schedule in a project at its runs-at-once limit waits for a later pass. Once a day it also collects again the statistics of database tables imports read (a few tables a pass; PostgreSQL's own, or the first 10,000 rows). |
| Live runner | replicas | Reads every live feed when it is due (`platform-live-runner`, D1). Each feed is read under a lease, so replicas share feeds and never read one twice at once. A batch is at most 5,000 events; saving a table kept current reads its whole current version, so give it the memory the largest followed table needs (Helm `liveRunner.resources`, 2Gi by default). |
| Postgres | vertical + read replicas | The single stateful tier; size it first (below). |

Uploads are durable across a gateway restart (P3: the resumable session lives in
`upload_sessions`, chunks in storage), so a chunked upload can resume on any
gateway replica — no sticky sessions required.

## Sizing

Starting points; measure with the perf baseline (below) and adjust.

Each gateway keeps what recent recipe previews and runs made, in memory, so changing a later step does not run the earlier ones again: up to `RECIPE_CACHE_MB` (512MB) for `RECIPE_CACHE_MINUTES` (30). Count it in a gateway's memory, or set 0 to keep nothing. One run's data may take `RUN_MEMORY_LIMIT_MB` (2GB); a step that would grow it past that stops the run with the step and the size.

| Scale | Gateway | Web | Worker | Postgres |
| --- | --- | --- | --- | --- |
| Trial / single team | 1 × 0.5 vCPU / 1.5Gi | 1 × 0.5 vCPU / 512Mi | 1 × 1 vCPU / 4Gi | 1 vCPU / 2Gi |
| Small (≤50 users) | 2 × 1 vCPU / 1.5Gi | 2 × 0.5 vCPU / 512Mi | 1–2 × 2 vCPU / 4Gi | 2 vCPU / 4Gi, SSD |
| Medium (≤500 users) | 3–6 (HPA) × 1 vCPU / 1.5Gi | 3–6 (HPA) | 2–4 × 2 vCPU / 4Gi | 4–8 vCPU / 16Gi, read replica for reporting |

**Memory follows the largest file.** Reading a CSV takes about nine times its
size on the worker (measured: 1.86GB for a 199MB CSV of 3,957,935 rows, read
in 37 s; it was twenty times before A8), and the gateway about three times
while it saves the upload (714MB for the same file). Files of many short text
values take more. Give the worker about twenty times the upload limit (4GB for
the default 200MB) and the gateway 1.5GB, or lower `MAX_UPLOAD_SIZE_BYTES` to
fit what you have; System status shows the limit in force.

Tune the connection pool (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`) so
`gateway_replicas × (pool + overflow)` stays under Postgres `max_connections`.

## Observability

- **Metrics:** the gateway serves Prometheus text at `GET /metrics` (outside
  auth — it exposes counts, never rows): `pipewright_projects_total`,
  `pipewright_datasets_total`, `pipewright_workflow_runs_total{status=…}`,
  `pipewright_rows_processed_total`, `pipewright_compute_seconds_total`, and
  more. Scrape it and alert on, e.g., a rising `workflow_runs_total{status=failed}`.
- **Runtime health:** `GET /api/v1/status` carries per-component heartbeats
  (workflow worker, schedule ticker) and queue depths; the System-status page
  and Home card render them. A stalled queue also opens an incident (P3).
- **Request tracing:** every request carries a correlation id (the
  `X-Request-ID` response header, every log line it produces, and its audit
  entry), so one request's logs group across services.
- **Traces:** set `OTEL_ENABLED=true` and `OTEL_EXPORTER_OTLP_ENDPOINT` (an
  OpenTelemetry Collector, Jaeger, Tempo, Honeycomb...) and each gateway
  request becomes a trace with a span per database statement, carrying the
  same correlation id. Health checks and `/metrics` are left out. The standard
  `OTEL_*` variables configure the exporter; off, nothing is loaded.
- **Rate limits:** sign-in (per account and per address), one-time codes,
  public dashboards and inbound webhooks are limited, shared between gateways
  through the database; a refused request gets 429 with `Retry-After`. The
  limits are listed on System status. `RATE_LIMITS_ENABLED=false` turns them
  off for a load test.
- **Slow queries:** set `DB_SLOW_QUERY_MS` (e.g. `500`) to log any SQL statement
  over that many milliseconds, with its correlation id. It is off by default;
  turn it on to diagnose a slow page, then turn it back off — it is not an
  echo-everything switch.
- **Liveness / readiness:** `GET /api/v1/health/live` and `…/health/ready`.

## Performance baseline

`scripts/perf-baseline.py` hits the hot read endpoints and reports p50/p95 and
requests/second — dependency-free (standard-library only). Run it against a
deployment and record the numbers here after a material change:

```sh
PERF_BASE_URL=http://localhost:8000 PERF_USERNAME=… PERF_PASSWORD=… \
  python scripts/perf-baseline.py --requests 200 --concurrency 8
```

First baseline (120 req × 8 concurrency, single-process dev uvicorn on a laptop
with the workers running alongside — a floor, not a production number):

| Endpoint | p50 ms | p95 ms | req/s | fail |
| --- | --- | --- | --- | --- |
| health | 3 | 71 | 991 | 0 |
| status | 77 | 1517 | 46 | 0 |
| metrics | 26 | 34 | 299 | 0 |
| auth/me | 14 | 21 | 532 | 0 |
| sso/status | 8 | 11 | 932 | 0 |
| projects | 125 | 208 | 61 | 0 |
| runs | 33 | 107 | 205 | 0 |
| datasets | 42 | 103 | 157 | 0 |
| notifications | 24 | 317 | 169 | 0 |
| people | 12 | 21 | 619 | 0 |

`/status` is the outlier: it fans out to every service plus the scheduler and
runtime snapshots, so it is the one endpoint to cache or scrape sparingly.
Re-run after a material change and add a dated row.

**Budgets in CI (A7).** `--budgets` fails the run when an endpoint's p95 passes
its budget in `BUDGETS_MS` (health 150ms, status 2,500ms, projects 1,000ms and
so on). The CI `performance` job starts a fresh gateway, seeds five demo
projects with `--seed 5` and runs 100 requests at concurrency 4 against those
budgets on every push.
