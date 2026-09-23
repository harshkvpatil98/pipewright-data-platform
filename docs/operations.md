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
path. Object-storage deployments back the bucket up with the provider's tooling
instead.

**Drill it.** A restore you have never run is not a restore. Schedule
`backup.sh --verify` (it exits non-zero if the restored row counts are empty)
and alert on failure.

## Scaling

| Component | Scale by | Notes |
| --- | --- | --- |
| Gateway | replicas / HPA | Stateless; scale on CPU. `gateway.autoscaling.enabled=true`. |
| Web | replicas / HPA | Stateless; scale on CPU. |
| Workflow worker | replicas | The queue claim is leased, so many workers share load safely. |
| Schedule ticker | **one**, usually | The lease reduces but does not eliminate double-execution across pollers. Run one replica, or give each a distinct `SCHEDULER_RUNTIME_ID`. |
| Postgres | vertical + read replicas | The single stateful tier; size it first (below). |

Uploads are durable across a gateway restart (P3: the resumable session lives in
`upload_sessions`, chunks in storage), so a chunked upload can resume on any
gateway replica — no sticky sessions required.

## Sizing

Starting points; measure with the perf baseline (below) and adjust.

| Scale | Gateway | Web | Worker | Postgres |
| --- | --- | --- | --- | --- |
| Trial / single team | 1 × 0.5 vCPU / 512Mi | 1 × 0.5 vCPU / 512Mi | 1 | 1 vCPU / 2Gi |
| Small (≤50 users) | 2 × 1 vCPU / 512Mi | 2 × 0.5 vCPU / 512Mi | 1–2 | 2 vCPU / 4Gi, SSD |
| Medium (≤500 users) | 3–6 (HPA) × 1 vCPU | 3–6 (HPA) | 2–4 | 4–8 vCPU / 16Gi, read replica for reporting |

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
- **Request tracing:** every request carries a correlation id (in the response
  header and in every log line it produces), so one request's logs group across
  services.
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

| Date | Commit | Endpoint (p50 / p95 ms) | Notes |
| --- | --- | --- | --- |
| _record after your first run_ | | | local baseline |
