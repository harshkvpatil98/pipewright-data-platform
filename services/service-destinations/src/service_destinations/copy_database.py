"""Copying tables from one database to another ("Copy a database").

From a connected database (PostgreSQL, MySQL, SQLite) to a PostgreSQL or MySQL
destination. Honest scope, said wherever it is offered: the data and the basic
shape of each table -- its columns with their types, the primary key, which
columns may be empty. Nothing else is carried, and the report says what was
left behind for each table: foreign keys, other indexes and unique
constraints, defaults and auto-increment, check constraints; views are not
copied at all; triggers and procedures are never read.

Types go through the platform's canonical type lattice: each column's type is
read into it from the source's mapping and written out by the destination's,
and the conversion is checked for loss (precision, range, time zone, length),
so a plan says before anything is written which columns will not come across
exactly.

Rows stream from the source in batches and are written as they arrive, with
the drivers' own types (a pandas round trip would turn an integer column with
blanks into floats).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import column as sql_column
from sqlalchemy import inspect, table as sql_table, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_destinations.at_rest_config import destination_config_for_internal_use
from service_destinations.copy_schemas import (
    CopyColumnPlan,
    CopyPlan,
    CopyRequest,
    CopyTablePlan,
    CopyTableReport,
    CopyReport,
)
from service_destinations.service import get_destination_model
from service_destinations.sql_writer import ENGINES, engine_for, validate_table_name
from service_pipeline_runs.service import (
    create_pipeline_run,
    mark_pipeline_run_failed,
    mark_pipeline_run_running,
    mark_pipeline_run_succeeded,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError
from shared_python.types.coercion import cast_loss
from shared_python.types.lattice import UNKNOWN, Kind
from shared_python.types.mappings import get as type_mapping

RUN_TYPE = "database_copy"
SOURCE_ENGINES = {"postgresql": "PostgreSQL", "mysql": "MySQL", "sqlite": "SQLite"}
TARGET_MAPPING = {"postgres": "postgresql", "mysql": "mysql"}
BATCH = 1000
#: A copy runs inside one request, so it stops here and says so.
MAX_ROWS_PER_TABLE = 2_000_000
_JSON_KINDS = {Kind.JSON, Kind.ARRAY, Kind.STRUCT, Kind.MAP}

NEVER_COPIED = (
    "Views are not copied; they hold no data of their own.",
    "Triggers, stored procedures and functions are never read.",
    "Users, roles and permissions are not copied.",
)


@dataclass
class _Source:
    connector_type: str
    config: dict[str, Any]
    engine: Engine


def _source(db: Session, project_id: uuid.UUID, connection_id: uuid.UUID) -> _Source:
    from service_extraction.connector_sources import secret_fields
    from service_extraction.connectors import sql_database
    from service_extraction.service import get_connection_for_project
    from shared_python.security.config_crypto import decrypt_sensitive_fields

    connection = get_connection_for_project(db, project_id, connection_id)
    if connection.connector_type not in SOURCE_ENGINES:
        raise BadRequestError("A database can be copied from PostgreSQL, MySQL or SQLite.")
    config = decrypt_sensitive_fields(dict(connection.config_json or {}), secret_fields(connection.connector_type))
    return _Source(connection.connector_type, config, sql_database.get_engine(connection.connector_type, config))


def _split(qualified: str) -> tuple[str | None, str]:
    if "." in qualified:
        schema, name = qualified.split(".", 1)
        return schema, name
    return None, qualified


def _column_plan(source_type: str, data_type: str, target_type: str, *, name: str, nullable: bool, key: bool) -> CopyColumnPlan:
    source_map, target_map = type_mapping(source_type), type_mapping(TARGET_MAPPING[target_type])
    canonical = source_map.to_pw(data_type)
    if canonical == UNKNOWN or canonical.kind is Kind.UNKNOWN:
        written = "text" if target_type == "postgres" else "longtext"
        return CopyColumnPlan(
            name=name, source_type=data_type, target_type=written, nullable=nullable, primary_key=key,
            lossy=True, note=f"“{data_type}” is not a type the platform knows, so it is copied as text.",
        )
    written = target_map.from_pw(canonical)
    extra: list[str] = []
    if target_type == "mysql" and canonical.kind is Kind.TIMESTAMP:
        # MySQL's TIMESTAMP stops in 2038 and reads values in the session's
        # time zone, so a copy writes DATETIME at the source's precision (up
        # to microseconds) and converts zoned times to UTC on the way.
        precision = min(int(canonical.time_precision or 0), 6)
        written = f"datetime({precision})" if precision else "datetime"
        if canonical.tz_aware:
            extra.append("MySQL keeps no time zone, so these times are written in UTC.")
    if key and target_type == "mysql" and written in ("longtext", "longblob"):
        # MySQL cannot index an unbounded column, so a text key gets a length.
        written = "varchar(255)" if written == "longtext" else "varbinary(255)"
    back = target_map.to_pw(written)
    losses = [
        loss for loss in cast_loss(canonical, back)
        # A UUID always fits char(36) exactly; a length warning would be noise.
        if not (canonical.kind is Kind.UUID and loss.kind == "truncation")
        and not (extra and loss.kind == "timezone")
    ]
    notes = extra + [loss.detail for loss in losses]
    if not target_map.supports(canonical):
        # Not a loss: every value comes across, in a different kind of column.
        notes.insert(0, f"{ENGINES[target_type]} has no {canonical.kind.value} type, so it is stored as {written}.")
    return CopyColumnPlan(
        name=name, source_type=data_type, target_type=written, nullable=nullable, primary_key=key,
        lossy=bool(losses or extra), note=" ".join(notes) or None,
    )


def _not_carried(engine: Engine, schema: str | None, name: str) -> list[str]:
    """What this table has that the copy leaves behind, counted where the source says."""
    left: list[str] = []
    try:
        inspector = inspect(engine)
        foreign = inspector.get_foreign_keys(name, schema=schema)
        indexes = inspector.get_indexes(name, schema=schema)
        uniques = inspector.get_unique_constraints(name, schema=schema)
        columns = inspector.get_columns(name, schema=schema)
        try:
            checks = inspector.get_check_constraints(name, schema=schema)
        except NotImplementedError:
            checks = []
    except (SQLAlchemyError, NotImplementedError):
        return ["Its foreign keys, indexes, defaults and constraints were not checked."]
    defaults = [c["name"] for c in columns if c.get("default") is not None or c.get("autoincrement") is True]
    # A unique constraint brings its own index; count it once, as the constraint.
    unique_names = {u.get("name") for u in uniques}
    indexes = [ix for ix in indexes if not ix.get("duplicates_constraint") and ix.get("name") not in unique_names]

    def counted(count: int, noun: str, plural: str | None = None) -> str:
        return f"{count} {noun if count == 1 else (plural or noun + 's')}"

    if foreign:
        left.append(f"{counted(len(foreign), 'foreign key')} (relationships to other tables)")
    if indexes:
        left.append(f"{counted(len(indexes), 'index', 'indexes')} besides the primary key")
    if uniques:
        left.append(counted(len(uniques), "unique constraint"))
    if checks:
        left.append(counted(len(checks), "check constraint"))
    if defaults:
        left.append(f"defaults or auto-increment on {', '.join(defaults[:4])}{' and more' if len(defaults) > 4 else ''}")
    return left


def plan_copy(db: Session, project_id: uuid.UUID, payload: CopyRequest, current_user: UserRead) -> CopyPlan:
    from service_extraction.connectors import sql_database

    ensure_owned_project(db, project_id, current_user.id)
    source = _source(db, project_id, payload.connection_id)
    destination = get_destination_model(db, project_id, payload.destination_id)
    if destination.destination_type not in TARGET_MAPPING:
        raise BadRequestError("A database can be copied into a PostgreSQL or MySQL destination.")

    refs = sql_database.list_tables(source.connector_type, source.config)
    views = [ref for ref in refs if ref.kind != "table"]
    tables = [ref for ref in refs if ref.kind == "table"]
    if payload.tables:
        wanted = set(payload.tables)
        tables = [ref for ref in tables if ref.qualified_name in wanted or ref.name in wanted]
        if not tables:
            raise BadRequestError("None of the chosen tables were found in the source.")

    planned: list[CopyTablePlan] = []
    for ref in tables:
        columns = sql_database.list_columns(source.connector_type, source.config, table=ref.name, schema=ref.schema)
        plans = [
            _column_plan(source.connector_type, col.data_type, destination.destination_type,
                         name=col.name, nullable=col.nullable, key=col.primary_key)
            for col in columns
        ]
        try:
            target = validate_table_name(ref.name, destination.destination_type)
            problem = None
        except BadRequestError as exc:
            target, problem = ref.name, str(exc.detail)
        planned.append(
            CopyTablePlan(
                source=ref.qualified_name, target=target, columns=plans,
                primary_key=[c.name for c in plans if c.primary_key],
                not_carried=_not_carried(source.engine, ref.schema, ref.name),
                problem=problem,
            )
        )

    notes = list(NEVER_COPIED)
    if views:
        notes[0] = f"{len(views)} view{'' if len(views) == 1 else 's'} not copied; views hold no data of their own."
    return CopyPlan(
        source_label=SOURCE_ENGINES[source.connector_type],
        destination_label=ENGINES[destination.destination_type],
        tables=planned,
        never_copied=notes,
    )


def _ddl(engine: Engine, plan: CopyTablePlan) -> str:
    quote = engine.dialect.identifier_preparer.quote
    lines = [
        f"{quote(c.name)} {c.target_type}{'' if c.nullable and not c.primary_key else ' NOT NULL'}"
        for c in plan.columns
    ]
    if plan.primary_key:
        lines.append(f"PRIMARY KEY ({', '.join(quote(name) for name in plan.primary_key)})")
    return f"CREATE TABLE {quote(plan.target)} (\n  " + ",\n  ".join(lines) + "\n)"


def _converter(target_type: str, column: CopyColumnPlan):
    """How one value is handed to the destination's driver."""
    kind = type_mapping(TARGET_MAPPING[target_type]).to_pw(column.target_type).kind

    def convert(value: Any) -> Any:
        if value is None:
            return None
        if kind in _JSON_KINDS or column.target_type in ("json", "jsonb"):
            if isinstance(value, (bytes, bytearray)):
                value = value.decode("utf-8")
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    return value if target_type == "mysql" else json.dumps(value)
            if target_type == "postgres":
                from psycopg.types.json import Jsonb

                return Jsonb(value)
            return json.dumps(value, default=str)
        if isinstance(value, uuid.UUID):
            return str(value) if target_type == "mysql" else value
        if isinstance(value, datetime) and target_type == "mysql" and value.tzinfo is not None:
            return value.astimezone(UTC).replace(tzinfo=None)
        if isinstance(value, (list, dict)):
            return json.dumps(value, default=str)
        return value

    return convert


def _copy_table(source: _Source, target: Engine, target_type: str, plan: CopyTablePlan, *, replace: bool) -> CopyTableReport:
    from service_extraction.connectors import sql_database

    schema, name = _split(plan.source)
    if plan.problem:
        return CopyTableReport(source=plan.source, target=plan.target, status="skipped", message=plan.problem)
    quote_target = target.dialect.identifier_preparer.quote
    try:
        with target.begin() as conn:
            if inspect(conn).has_table(plan.target):
                if not replace:
                    return CopyTableReport(
                        source=plan.source, target=plan.target, status="skipped",
                        message="A table with this name is already there. Choose to replace tables to copy it again.",
                    )
                conn.execute(text(f"DROP TABLE {quote_target(plan.target)}"))
            conn.execute(text(_ddl(target, plan)))
    except SQLAlchemyError as exc:
        return CopyTableReport(source=plan.source, target=plan.target, status="failed",
                               message=f"Could not create the table: {str(getattr(exc, 'orig', exc)).splitlines()[0][:300]}")

    converters = [_converter(target_type, column) for column in plan.columns]
    names = [column.name for column in plan.columns]
    insert = sql_table(plan.target, *[sql_column(n) for n in names]).insert()
    select_sql = sql_database.build_table_query(source.connector_type, table=name, schema=schema)
    copied = 0
    truncated = False
    try:
        with source.engine.connect() as reader, target.begin() as writer:
            result = reader.execution_options(stream_results=True).execute(text(select_sql))
            while True:
                rows = result.fetchmany(BATCH)
                if not rows:
                    break
                batch = [{n: convert(v) for n, convert, v in zip(names, converters, row)} for row in rows]
                writer.execute(insert, batch)
                copied += len(batch)
                if copied >= MAX_ROWS_PER_TABLE:
                    truncated = True
                    break
    except SQLAlchemyError as exc:
        return CopyTableReport(source=plan.source, target=plan.target, status="failed", rows_copied=copied,
                               message=f"Stopped while copying rows: {str(getattr(exc, 'orig', exc)).splitlines()[0][:300]}")

    carried = []
    if plan.primary_key:
        carried.append(f"primary key ({', '.join(plan.primary_key)})")
    not_null = [c.name for c in plan.columns if not c.nullable and not c.primary_key]
    if not_null:
        carried.append(f"not empty: {', '.join(not_null[:5])}{' and more' if len(not_null) > 5 else ''}")
    message = (
        f"Stopped at {MAX_ROWS_PER_TABLE:,} rows, the most one copy takes; copy the rest with an import."
        if truncated else None
    )
    return CopyTableReport(source=plan.source, target=plan.target, status="succeeded", rows_copied=copied,
                           carried=carried, not_carried=plan.not_carried, message=message)


def run_copy(db: Session, project_id: uuid.UUID, payload: CopyRequest, current_user: UserRead) -> CopyReport:
    plan = plan_copy(db, project_id, payload, current_user)
    source = _source(db, project_id, payload.connection_id)
    destination = get_destination_model(db, project_id, payload.destination_id)
    config = destination_config_for_internal_use(destination.destination_type, dict(destination.config_json or {}))

    run = create_pipeline_run(db, project_id=project_id, current_user=current_user, run_type=RUN_TYPE,
                              logs_json={"events": []})
    mark_pipeline_run_running(db, run=run, logs_json={"events": []})
    target = engine_for(destination.destination_type, config)
    reports: list[CopyTableReport] = []
    try:
        for table_plan in plan.tables:
            reports.append(_copy_table(source, target, destination.destination_type, table_plan, replace=payload.replace_existing))
    finally:
        target.dispose()

    copied = [report for report in reports if report.status == "succeeded"]
    failed = [report for report in reports if report.status == "failed"]
    summary: dict[str, Any] = {
        "source": plan.source_label, "destination": {"id": str(destination.id), "name": destination.name,
                                                      "label": plan.destination_label},
        "tables_copied": len(copied), "tables_failed": len(failed),
        "tables_skipped": len(reports) - len(copied) - len(failed),
        "rows_copied": sum(report.rows_copied for report in reports),
        "tables": [report.model_dump() for report in reports],
        "never_copied": plan.never_copied,
    }
    events = [{"stage": "finished", "message": f"Copied {len(copied)} of {len(reports)} tables.",
               "recorded_at": datetime.now(UTC).isoformat()}]
    if failed:
        mark_pipeline_run_failed(db, run=run, summary_json=summary, logs_json={"events": events})
    else:
        mark_pipeline_run_succeeded(db, run=run, summary_json=summary, logs_json={"events": events})
    db.commit()
    return CopyReport(
        run_id=run.id, status="failed" if failed else "succeeded",
        tables=reports, rows_copied=summary["rows_copied"], never_copied=plan.never_copied,
    )
