"""Statistics for tables in connected databases (D2, O1).

A dataset's statistics come from every row when its version is written. A
table that lives in someone's database is not read whole to describe it:

- **PostgreSQL** keeps its own (`pg_class.reltuples` and `pg_stats`, filled
  by ANALYZE): the share of empty values, distinct values (a negative
  `n_distinct` is a share of the rows), the commonest values and how often
  each appears, and equal-count histogram bounds. Nothing in the table is
  read. A table PostgreSQL has never analysed falls back to a sample.
- **Everything else** (MySQL, SQLite and the rest) is described from the
  first `SAMPLE_ROWS` rows it returns, through the same profile datasets get,
  with the row count from the database's own figure where it has one (MySQL's
  `TABLE_ROWS`, itself an estimate) or a count. The first rows are not a
  random sample (a random one would read the whole table), and `method` says
  so.

Each says which (`method`), so a plan built on them can say how sure it is.
Refreshed when an import of the table runs and by the ticker once a day
(`refresh_due`); never changes the database (no ANALYZE is run).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from service_extraction.models import ExtractionConnection, ExtractionJob, TableStatistics
from shared_python.logging import get_logger
from shared_python.statistics import ColumnStats, TableStats, from_profile

logger = get_logger(__name__)

SAMPLE_ROWS = 10_000
#: How old statistics may get before the ticker refreshes them.
STALE_AFTER = timedelta(hours=24)


def _config(connection: ExtractionConnection) -> dict[str, Any]:
    from service_extraction.connector_sources import secret_fields
    from shared_python.security.config_crypto import decrypt_sensitive_fields

    return decrypt_sensitive_fields(dict(connection.config_json or {}), secret_fields(connection.connector_type))


def can_describe(connector_type: str) -> bool:
    from service_extraction.connector_sources import is_sql

    return is_sql(connector_type)


def _pg_array(value: Any) -> list[str | None]:
    """PostgreSQL's text form of an array, `{a,"b c",NULL}`, as a list."""
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [None if item is None else str(item) for item in value]
    body = str(value).strip()
    if not (body.startswith("{") and body.endswith("}")):
        return [body]
    body = body[1:-1]
    items: list[str | None] = []
    current: list[str] = []
    quoted = escaped = False
    was_quoted = False
    for char in body:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == '"':
            quoted = not quoted
            was_quoted = True
        elif char == "," and not quoted:
            word = "".join(current)
            items.append(None if word == "NULL" and not was_quoted else word)
            current, was_quoted = [], False
        else:
            current.append(char)
    if body:
        word = "".join(current)
        items.append(None if word == "NULL" and not was_quoted else word)
    return items


def _number(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _edges(raw: list[str]) -> tuple[str, list[float]]:
    """Histogram bounds as numbers, or dates as milliseconds since 1970; text bounds measure nothing."""
    numbers = [_number(item) for item in raw]
    if raw and all(item is not None for item in numbers):
        return "number", [float(item) for item in numbers if item is not None]
    try:
        stamps = [datetime.fromisoformat(item) for item in raw]
    except ValueError:
        return "text", []
    if not stamps:
        return "text", []
    return "datetime", [(s if s.tzinfo else s.replace(tzinfo=UTC)).timestamp() * 1000.0 for s in stamps]


def _postgres(engine, schema: str | None, table: str) -> TableStats | None:
    schema = schema or "public"
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT c.reltuples FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = :s AND c.relname = :t"), {"s": schema, "t": table}).scalar()
        if rows is None or float(rows) < 0:
            return None  # never analysed: a sample says more than nothing
        found = conn.execute(text(
            "SELECT attname, null_frac, n_distinct, most_common_vals::text, most_common_freqs::text, "
            "histogram_bounds::text FROM pg_stats WHERE schemaname = :s AND tablename = :t"),
            {"s": schema, "t": table}).all()
    if not found:
        return None
    total = float(rows)
    columns: dict[str, ColumnStats] = {}
    for name, null_frac, n_distinct, mcv, freqs, bounds in found:
        distinct = None
        if n_distinct is not None:
            distinct = int(round(-float(n_distinct) * total)) if float(n_distinct) < 0 else int(n_distinct)
        common_values = _pg_array(mcv)
        common_freqs = [_number(item) or 0.0 for item in _pg_array(freqs)]
        common = [(str(v), int(round(f * total))) for v, f in zip(common_values, common_freqs, strict=False) if v is not None]
        raw_edges = [item for item in _pg_array(bounds) if item is not None]
        kind, edges = _edges(raw_edges)
        histogram_rows: list[int] = []
        if len(edges) >= 2:
            # PostgreSQL's histogram leaves out the commonest values; its buckets share what is left.
            spread = total * max(0.0, 1.0 - float(null_frac or 0.0) - sum(common_freqs))
            histogram_rows = [int(round(spread / (len(edges) - 1)))] * (len(edges) - 1)
        else:
            edges = []
        columns[name] = ColumnStats(
            name=name, kind=kind, empty_share=float(null_frac or 0.0), distinct=distinct,
            lowest=edges[0] if edges else None, highest=edges[-1] if edges else None,
            bounds=edges, bucket_rows=histogram_rows, common=common, histogram_excludes_common=True,
        )
    return TableStats(rows=int(total), columns=columns, method="PostgreSQL's own statistics",
                      collected_at=datetime.now(UTC))


def _sampled(connection: ExtractionConnection, config: dict[str, Any], schema: str | None, table: str) -> TableStats:
    from service_extraction.connectors import sql_database
    from service_ingestion.profiling import build_profile

    # PostgreSQL, MySQL and SQLite (every database here) all take LIMIT.
    query = f"{sql_database.build_table_query(connection.connector_type, table=table, schema=schema)} LIMIT {int(SAMPLE_ROWS)}"
    sample = sql_database.read_dataframe(connection.connector_type, config, sql=query, max_rows=SAMPLE_ROWS).dataframe
    rows = len(sample)
    if rows >= SAMPLE_ROWS:
        rows = _row_count(connection, config, schema, table) or rows
    stats = from_profile(build_profile(dataframe=sample, sample_limit=5, file_size_bytes=0))
    assert stats is not None
    scale = rows / len(sample) if len(sample) else 1.0
    for column in stats.columns.values():
        # A column nearly every sampled row of differs in grows with the table;
        # one with few values has them all already.
        if column.distinct is not None and len(sample) and column.distinct > 0.9 * len(sample):
            column.distinct = int(column.distinct * scale)
        column.bucket_rows = [int(count * scale) for count in column.bucket_rows]
        column.common = [(value, int(count * scale)) for value, count in column.common]
    stats.rows = rows
    stats.method = f"the first {len(sample):,} rows" if scale > 1 else "every row"
    stats.collected_at = datetime.now(UTC)
    return stats


def _row_count(connection: ExtractionConnection, config: dict[str, Any], schema: str | None, table: str) -> int | None:
    from service_extraction.connectors import sql_database

    engine = sql_database.get_engine(connection.connector_type, config)
    with engine.connect() as conn:
        if connection.connector_type == "mysql":
            found = conn.execute(text(
                "SELECT TABLE_ROWS FROM information_schema.TABLES WHERE TABLE_SCHEMA = COALESCE(:s, DATABASE()) "
                "AND TABLE_NAME = :t"), {"s": schema, "t": table}).scalar()
            if found is not None:
                return int(found)
        relation = sql_database.build_table_query(connection.connector_type, table=table, schema=schema)
        relation = relation.removeprefix("SELECT * FROM ")
        return int(conn.execute(text(f"SELECT COUNT(*) FROM {relation}")).scalar() or 0)


def collect(connection: ExtractionConnection, schema: str | None, table: str) -> TableStats:
    """Describe one table, the cheapest honest way its database allows."""
    config = _config(connection)
    if connection.connector_type == "postgresql":
        from service_extraction.connectors import sql_database

        stats = _postgres(sql_database.get_engine("postgresql", config), schema, table)
        if stats is not None:
            return stats
    return _sampled(connection, config, schema, table)


def stored(db: Session, connection_id: uuid.UUID, schema: str | None, table: str) -> TableStatistics | None:
    return db.scalar(select(TableStatistics).where(
        TableStatistics.connection_id == connection_id, TableStatistics.table_name == table,
        TableStatistics.schema_name == (schema or "")))


def refresh(db: Session, connection: ExtractionConnection, schema: str | None, table: str) -> TableStatistics:
    stats = collect(connection, schema, table)
    row = stored(db, connection.id, schema, table)
    if row is None:
        row = TableStatistics(connection_id=connection.id, schema_name=schema or "", table_name=table)
        db.add(row)
    row.stats_json = stats.to_json()
    row.method = stats.method
    row.row_count = stats.rows
    row.collected_at = stats.collected_at
    db.commit()
    db.refresh(row)
    return row


def for_table(db: Session, connection: ExtractionConnection, schema: str | None, table: str, *,
              max_age: timedelta = STALE_AFTER) -> TableStats | None:
    """Stored statistics while they are fresh, collected again when not; None if they cannot be had."""
    row = stored(db, connection.id, schema, table)
    if row is not None and row.collected_at and datetime.now(UTC) - _aware(row.collected_at) < max_age:
        return TableStats.from_json(row.stats_json)
    try:
        return TableStats.from_json(refresh(db, connection, schema, table).stats_json)
    except Exception:  # noqa: BLE001 - statistics improve a plan; their absence must not break one
        db.rollback()
        logger.warning("table_statistics_failed connection_id=%s table=%s", connection.id, table, exc_info=True)
        return TableStats.from_json(row.stats_json) if row is not None else None


def read_model(db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, *, table: str,
               schema: str | None, current_user, fresh: bool = False):
    """The API's view: stored statistics, collected first when missing, old, or asked for."""
    from service_extraction.schemas import ColumnStatisticsRead, TableStatisticsRead
    from service_extraction.service import get_connection_for_project
    from service_projects.contracts import ensure_owned_project
    from shared_python.errors import BadRequestError

    ensure_owned_project(db, project_id, current_user.id)
    connection = get_connection_for_project(db, project_id, connection_id)
    if not can_describe(connection.connector_type):
        raise BadRequestError("Statistics are kept for database tables; this source is not a database.")
    schema = schema or None
    row = stored(db, connection.id, schema, table)
    stale = row is None or datetime.now(UTC) - _aware(row.collected_at) >= STALE_AFTER
    if fresh or stale:
        row = refresh(db, connection, schema, table)
    stats = TableStats.from_json(row.stats_json)
    assert stats is not None
    return TableStatisticsRead(
        connection_id=connection.id, table=table, schema_name=schema, rows=int(row.row_count), method=row.method,
        collected_at=_aware(row.collected_at),
        columns=[ColumnStatisticsRead(name=c.name, kind=c.kind, empty_share=c.empty_share, distinct=c.distinct,
                                      lowest=c.lowest, highest=c.highest, bounds=c.bounds, bucket_rows=c.bucket_rows,
                                      common=c.common) for c in stats.columns.values()],
    )


def refresh_after_import(db: Session, connection: ExtractionConnection, job: ExtractionJob) -> None:
    """An import read the table, so what is known about it may have changed. Never fails the import."""
    if job.source_kind != "table" or not job.source_table or not can_describe(connection.connector_type):
        return
    try:
        refresh(db, connection, job.source_schema or None, job.source_table)
    except Exception:  # noqa: BLE001 - statistics are a nicety next to the rows themselves
        db.rollback()
        logger.warning("table_statistics_after_import_failed job_id=%s", job.id, exc_info=True)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def refresh_due(db: Session, *, limit: int = 5) -> int:
    """The ticker's daily pass: every table an import reads, when its statistics are old."""
    done = 0
    seen: set[tuple[uuid.UUID, str | None, str]] = set()
    jobs = db.scalars(select(ExtractionJob).where(
        ExtractionJob.source_kind == "table", ExtractionJob.source_table.is_not(None),
        ExtractionJob.enabled.is_(True))).all()
    for job in jobs:
        key = (job.connection_id, job.source_schema or None, str(job.source_table))
        if key in seen or done >= limit:
            continue
        seen.add(key)
        row = stored(db, *key)
        if row is not None and row.collected_at and datetime.now(UTC) - _aware(row.collected_at) < STALE_AFTER:
            continue
        connection = db.get(ExtractionConnection, job.connection_id)
        if connection is None or not can_describe(connection.connector_type):
            continue
        try:
            refresh(db, connection, *key[1:])
            done += 1
        except Exception:  # noqa: BLE001 - one unreachable database must not stop the rest
            db.rollback()
            logger.warning("table_statistics_refresh_failed job_id=%s", job.id, exc_info=True)
    return done
