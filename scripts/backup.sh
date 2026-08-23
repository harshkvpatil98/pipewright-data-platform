#!/usr/bin/env bash
# Take a backup, and prove it can be restored.
#
# A backup nobody has restored is a hope, not a backup. This script does both
# halves: it dumps, and then --verify restores that dump into a scratch database
# and counts the rows. The verification is the point; the dump is the easy part.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

BACKUP_DIR="${BACKUP_DIR:-./backups}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
VERIFY=0
UPLOADS="${UPLOAD_ROOT_PATH:-data/uploads}"

for argument in "$@"; do
  case "$argument" in
    --verify) VERIFY=1 ;;
    --help)
      echo "usage: scripts/backup.sh [--verify]"
      echo "  --verify   restore the dump into a scratch database and count rows"
      exit 0
      ;;
    *) echo "unknown option: $argument" >&2; exit 2 ;;
  esac
done

if [[ -z "${DATABASE_URL:-}" ]]; then
  if [[ -f apps/api-gateway/.env ]]; then
    DATABASE_URL="$(grep -E '^DATABASE_URL=' apps/api-gateway/.env | head -1 | cut -d= -f2-)"
  fi
fi
if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "error: DATABASE_URL is not set and could not be read from apps/api-gateway/.env" >&2
  exit 1
fi

# SQLAlchemy URLs carry a driver suffix that libpq does not understand.
PG_URL="${DATABASE_URL/+psycopg/}"
PG_URL="${PG_URL/+psycopg2/}"

# The Postgres client tools may not be on this host -- a common case when the
# database runs in a container. Falling back to the container is not a
# convenience: a backup script that only works if somebody happened to install
# libpq is a backup script that fails on the day it is needed.
PG_CONTAINER="${PG_CONTAINER:-}"
if ! command -v pg_dump >/dev/null 2>&1; then
  if [[ -z "$PG_CONTAINER" ]] && command -v docker >/dev/null 2>&1; then
    PG_CONTAINER="$(docker ps --filter "ancestor=postgres:16-alpine" --format '{{.Names}}' | head -1)"
    [[ -z "$PG_CONTAINER" ]] && PG_CONTAINER="$(docker ps --format '{{.Names}}' | grep -m1 postgres || true)"
  fi
  if [[ -z "$PG_CONTAINER" ]]; then
    echo "error: pg_dump is not installed and no Postgres container was found." >&2
    echo "       Install the Postgres client tools, or set PG_CONTAINER to the container name." >&2
    exit 1
  fi
  echo "==> using the Postgres tools inside container '$PG_CONTAINER'"
fi

# Inside the container the database is reachable on localhost, whatever host
# the URL names from out here.
container_url() {
  python3 - "$1" <<'PYURL'
import re, sys
url = sys.argv[1]
print(re.sub(r"@[^/:]+(:\d+)?/", "@localhost:5432/", url))
PYURL
}

run_pg() {
  local tool="$1"; shift
  if [[ -n "$PG_CONTAINER" ]]; then
    docker exec -i "$PG_CONTAINER" "$tool" "$@"
  else
    "$tool" "$@"
  fi
}

if [[ -n "$PG_CONTAINER" ]]; then
  PG_URL="$(container_url "$PG_URL")"
fi

mkdir -p "$BACKUP_DIR"
DUMP="$BACKUP_DIR/pipewright-$STAMP.dump"

echo "==> dumping the database"
# Custom format: compressed, and restorable table-by-table if only part is lost.
# Written to stdout so it lands here rather than inside the container.
run_pg pg_dump --format=custom --no-owner --no-privileges "$PG_URL" > "$DUMP"
echo "    $DUMP ($(du -h "$DUMP" | cut -f1))"

if [[ -d "$UPLOADS" ]]; then
  echo "==> archiving stored files"
  # The database records where every dataset's bytes live; without them a
  # restored database is a catalogue of files that are gone.
  FILES="$BACKUP_DIR/pipewright-files-$STAMP.tar.gz"
  tar -czf "$FILES" "$UPLOADS"
  echo "    $FILES ($(du -h "$FILES" | cut -f1))"
else
  echo "==> no upload directory at $UPLOADS; skipping file archive"
fi

if [[ "$VERIFY" -eq 1 ]]; then
  SCRATCH="pipewright_restore_check_$$"
  echo "==> verifying by restoring into $SCRATCH"
  ADMIN_URL="${PG_URL%/*}/postgres"

  cleanup() {
    run_pg psql "$ADMIN_URL" -q -c "DROP DATABASE IF EXISTS $SCRATCH" >/dev/null 2>&1 || true
  }
  trap cleanup EXIT

  run_pg psql "$ADMIN_URL" -q -c "CREATE DATABASE $SCRATCH"
  run_pg pg_restore --no-owner --no-privileges --dbname="${PG_URL%/*}/$SCRATCH" < "$DUMP" >/dev/null

  echo "    row counts in the restored copy:"
  run_pg psql "${PG_URL%/*}/$SCRATCH" -t -A -F' ' -c "
    SELECT relname, n_live_tup
    FROM pg_stat_user_tables
    WHERE n_live_tup > 0
    ORDER BY n_live_tup DESC
    LIMIT 12;" | sed 's/^/      /'

  TABLES="$(run_pg psql "${PG_URL%/*}/$SCRATCH" -t -A -c \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" | tr -d '[:space:]')"
  echo "    $TABLES table(s) restored"

  if [[ "$TABLES" -lt 10 ]]; then
    echo "error: the restored database has only $TABLES tables; this dump is not usable" >&2
    exit 1
  fi
  echo "==> restore verified"
fi

echo
echo "Backup complete."
echo "To restore for real:"
echo "  pg_restore --no-owner --clean --if-exists --dbname=\"\$DATABASE_URL\" $DUMP"
