# Disaster recovery

## What this covers

Losing the database, losing the stored files, or losing the machine. It does not
cover losing the source systems Pipewright reads from — those are their owners'
problem, and re-running an extraction is how you recover from that.

## What has to be backed up

Two things, and both are needed:

| What | Where | Why |
| --- | --- | --- |
| The database | `pg_dump` | Every definition, run, policy, and piece of history. |
| Stored dataset files | `UPLOAD_ROOT_PATH` (default `data/uploads`) | The database records *where* a dataset's bytes are, not what they are. A restored database without these is a catalogue of files that are gone. |

`scripts/backup.sh` takes both.

## Running a backup

```bash
./scripts/backup.sh            # dump the database and archive the files
./scripts/backup.sh --verify   # ...and prove the dump restores
```

`--verify` restores the dump into a scratch database, counts the rows, and
fails if the result has fewer than ten tables. **Run it this way.** A backup
nobody has restored is a hope; the verification is the part that makes it a
backup.

## Restoring

```bash
# 1. The database
pg_restore --no-owner --clean --if-exists --dbname="$DATABASE_URL" backups/pipewright-<stamp>.dump

# 2. The stored files
tar -xzf backups/pipewright-files-<stamp>.tar.gz -C /

# 3. Bring the schema to the current version, in case the dump predates a deploy
cd apps/api-gateway && alembic upgrade head
```

## After a restore: what to expect

**Scheduled work does not resume by itself, and that is deliberate.** Cron
schedules skip missed slots rather than firing repeatedly to catch up, so a
workflow that should have run during the outage simply did not. Use a
[backfill](../README.md) to reprocess those dates — that is what backfills are
for, and it is the only way to reprocess with the right logical dates.

**Runs that were in flight are failed, not retried.** A run whose worker died
may already have published data or sent notifications, and there are no
idempotency keys yet, so replaying it would repeat those effects. Look at the
failed runs and decide.

**Incidents stay as they were.** Freshness incidents will resolve themselves on
the next sweep once data starts flowing again.

## Running more than one worker

Workers claim runs with `SELECT ... FOR UPDATE SKIP LOCKED` and hold a lease, so
several can run at once without doing the same work twice. A worker that dies
loses its lease and its run is failed by `release_stalled_runs` on another
worker's next tick.

Set `SCHEDULER_RUNTIME_ID` to something distinct per replica. Leases reduce
duplicate work across concurrent pollers; they are not global distributed
locking, and the platform does not claim to be.

## The drill

Quarterly, on a copy — never on production:

1. `./scripts/backup.sh --verify` — confirms the dump is restorable.
2. Restore into a scratch database and point a gateway at it.
3. Sign in, open a project, open a dataset, and check the preview renders.
4. Run one workflow by hand and confirm it succeeds.
5. Note how long steps 2–4 took. That number is your recovery time, and it is
   the only honest one you have.

## What is not covered

- **Point-in-time recovery.** These are periodic dumps. Recovering to an
  arbitrary moment needs WAL archiving, which is a Postgres configuration
  concern rather than something this platform can do for you.
- **Cross-region replication.** Out of scope for this deployment.
