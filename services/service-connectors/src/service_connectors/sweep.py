"""The nightly schema watch, with somewhere to put what it found.

`watch.py` knows how to compare two schemas. This module is the part that has a
database: it walks a project's configured connections, remembers what each
stream looked like, and turns a change into a Phase 02 incident — the same
object a failing quality rule or a stale dataset produces, on the same list,
with the same timeline and the same owner.

Three decisions worth stating:

**It files incidents rather than sending alerts.** A vendor changing an API at
three in the morning is exactly the case incidents were built for: it recurs
nightly until somebody fixes it, and twenty notifications for one problem is
how an alert list gets muted. `incidents.report` collapses recurrences by
fingerprint, and the fingerprint here is the connection and the stream — never
the run, or every night would open a new one.

**A schema that goes back to normal closes its own incident.** Otherwise the
list fills with problems that stopped being problems, and a list nobody trusts
is worse than no list.

**A connection that cannot be read is not drift.** A credential that expired, a
host that is down, a connector with no `schema` capability — each is reported as
skipped, with the reason. Treating "we could not look" as "the columns are
gone" would file a breaking incident every time a VPN dropped.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from shared_python.logging import get_logger
from shared_python.security.config_crypto import decrypt_sensitive_fields

from service_connectors.models import ConnectorSchemaSnapshot
from service_connectors.registry import get, known_types
from service_connectors.watch import declared_schema, normalise_type

logger = get_logger(__name__)

#: How many streams one connection contributes to a sweep. A source with two
#: thousand tables would otherwise turn a nightly job into an outage -- every
#: stream costs an introspection round trip, and a SaaS API charges for each.
#:
#: Whenever it bites, it is said in the summary line as well as in the report,
#: because the summary is what becomes the schedule's last-run message: "checked
#: 25 streams; no schema changes" reads as complete coverage of a database with
#: fifty-two tables, and the twenty-seven nobody looked at are exactly where the
#: unnoticed drift would be.
MAX_STREAMS_PER_CONNECTION = 200


@dataclass
class StreamOutcome:
    """What the sweep found for one stream of one connection."""

    connection_id: str
    connection_name: str
    connector_type: str
    stream: str
    checked: bool
    severity: str = "none"
    summary: str = ""
    added_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    type_changes: list[dict[str, str]] = field(default_factory=list)
    skipped_reason: str = ""
    first_look: bool = False
    incident_id: str | None = None
    source: str = "live"

    @property
    def has_drift(self) -> bool:
        return bool(self.added_columns or self.removed_columns or self.type_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connection_id": self.connection_id,
            "connection_name": self.connection_name,
            "connector_type": self.connector_type,
            "stream": self.stream,
            "checked": self.checked,
            "severity": self.severity,
            "summary": self.summary,
            "added_columns": list(self.added_columns),
            "removed_columns": list(self.removed_columns),
            "type_changes": list(self.type_changes),
            "skipped_reason": self.skipped_reason,
            "first_look": self.first_look,
            "incident_id": self.incident_id,
            "source": self.source,
        }


@dataclass
class SweepReport:
    checked_at: str
    results: list[StreamOutcome] = field(default_factory=list)
    connections: int = 0
    skipped_connections: list[dict[str, str]] = field(default_factory=list)
    #: Connections whose stream list was longer than the cap, and by how much.
    truncated: list[dict[str, int | str]] = field(default_factory=list)

    @property
    def drifted(self) -> list[StreamOutcome]:
        return [result for result in self.results if result.has_drift]

    @property
    def breaking(self) -> list[StreamOutcome]:
        return [result for result in self.results if result.severity == "breaking"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "connections": self.connections,
            "streams_checked": sum(1 for result in self.results if result.checked),
            "streams_skipped": sum(1 for result in self.results if not result.checked),
            "drifted": len(self.drifted),
            "breaking": len(self.breaking),
            "incidents": sorted({r.incident_id for r in self.results if r.incident_id}),
            "skipped_connections": list(self.skipped_connections),
            "truncated": list(self.truncated),
            "results": [result.to_dict() for result in self.results],
        }

    def summary_line(self) -> str:
        """One sentence, which becomes the schedule's last-run message.

        It has to carry the truncation. Saying "checked 25 streams" about a
        database with fifty-two tables is true and reads as complete, and the
        twenty-seven nobody looked at are where the unnoticed drift would be.
        """
        if not self.results and not self.connections:
            return "Nothing configured to watch."

        unwatched = sum(int(entry["unwatched"]) for entry in self.truncated)
        tail = (
            f" {unwatched} further stream(s) were past the per-connection limit "
            f"of {MAX_STREAMS_PER_CONNECTION} and were not looked at."
            if unwatched
            else ""
        )
        if not self.drifted:
            return (
                f"Checked {sum(1 for r in self.results if r.checked)} stream(s) across "
                f"{self.connections} connection(s); no schema changes." + tail
            )
        breaking = len(self.breaking)
        return (
            f"{len(self.drifted)} stream(s) changed"
            + (f", {breaking} breaking" if breaking else "")
            + f", across {self.connections} connection(s)." + tail
        )


def fingerprint(connection_id: uuid.UUID | str, stream: str) -> str:
    """The identity of "this stream's schema keeps moving".

    Excludes anything time-varying, so tonight's drift lands on the incident
    last night's opened instead of starting a new one.
    """
    from service_observability.incidents import fingerprint_for

    return fingerprint_for("drift", "connector", str(connection_id), stream)


def _usable_config(connection: Any) -> dict[str, Any]:
    """The connection's settings, decrypted and with references resolved."""
    spec = get(connection.connector_type).spec
    return decrypt_sensitive_fields(dict(connection.config_json or {}), spec.secret_fields)


def _live_schema(connector: Any, config: dict[str, Any], stream: Any) -> dict[str, str]:
    return {
        column.name: normalise_type(column.data_type)
        for column in connector.columns(config, stream)
    }


def _snapshot(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, stream: str
) -> ConnectorSchemaSnapshot | None:
    return db.scalars(
        select(ConnectorSchemaSnapshot).where(
            ConnectorSchemaSnapshot.project_id == project_id,
            ConnectorSchemaSnapshot.connection_id == connection_id,
            ConnectorSchemaSnapshot.stream_name == stream,
        )
    ).first()


def sweep_project(
    db: Session,
    *,
    project_id: uuid.UUID,
    connection_id: uuid.UUID | None = None,
    open_incidents: bool = True,
    now: datetime | None = None,
) -> SweepReport:
    """Re-read every watchable stream in a project and record what changed."""
    from service_extraction.models import ExtractionConnection
    from service_observability import incidents
    from service_quality.drift import detect_schema_drift

    moment = now or datetime.now(UTC)
    report = SweepReport(checked_at=moment.isoformat())

    query = select(ExtractionConnection).where(ExtractionConnection.project_id == project_id)
    if connection_id is not None:
        query = query.where(ExtractionConnection.id == connection_id)
    connections = list(db.scalars(query.order_by(ExtractionConnection.name)).all())
    report.connections = len(connections)

    for connection in connections:
        if connection.connector_type not in known_types():
            report.skipped_connections.append(
                {
                    "connection_id": str(connection.id),
                    "name": connection.name,
                    "reason": (
                        f"'{connection.connector_type}' is not a connector this "
                        "deployment knows about."
                    ),
                }
            )
            continue

        connector = get(connection.connector_type)
        spec = connector.spec
        if not spec.available:
            report.skipped_connections.append(
                {
                    "connection_id": str(connection.id),
                    "name": connection.name,
                    "reason": spec.unavailable_reason or f"{spec.label} is not available here.",
                }
            )
            continue

        try:
            config = _usable_config(connection)
        except Exception as exc:  # noqa: BLE001 - an unreadable secret is a skip
            report.skipped_connections.append(
                {
                    "connection_id": str(connection.id),
                    "name": connection.name,
                    "reason": f"Could not read this connection's settings: {exc}",
                }
            )
            continue

        streams = _streams_for(connector, config, connection, report)
        for stream in streams[:MAX_STREAMS_PER_CONNECTION]:
            outcome = _check_stream(
                db,
                project_id=project_id,
                connection=connection,
                connector=connector,
                config=config,
                stream=stream,
                moment=moment,
                open_incidents=open_incidents,
                detect=detect_schema_drift,
                incidents=incidents,
            )
            report.results.append(outcome)

        if len(streams) > MAX_STREAMS_PER_CONNECTION:
            unwatched = len(streams) - MAX_STREAMS_PER_CONNECTION
            report.truncated.append(
                {
                    "connection_id": str(connection.id),
                    "name": connection.name,
                    "watched": MAX_STREAMS_PER_CONNECTION,
                    "total": len(streams),
                    "unwatched": unwatched,
                }
            )
            report.skipped_connections.append(
                {
                    "connection_id": str(connection.id),
                    "name": connection.name,
                    "reason": (
                        f"Watched the first {MAX_STREAMS_PER_CONNECTION} of "
                        f"{len(streams)} streams; {unwatched} were not looked at. "
                        "Narrow the connection's schema setting to cover the rest."
                    ),
                }
            )

    db.flush()
    return report


def _streams_for(connector: Any, config: dict[str, Any], connection: Any, report: SweepReport):
    """What this connection has to watch, or nothing with a reason."""
    spec = connector.spec
    if not spec.supports("discover"):
        report.skipped_connections.append(
            {
                "connection_id": str(connection.id),
                "name": connection.name,
                "reason": (
                    f"{spec.label} cannot list what it holds, so there is nothing "
                    "to walk."
                ),
            }
        )
        return []
    try:
        return list(connector.discover(config))
    except Exception as exc:  # noqa: BLE001 - a source that will not answer is a skip
        logger.info(
            "connector_watch_discover_failed",
            extra={"connector_type": spec.type, "error": str(exc)[:200]},
        )
        report.skipped_connections.append(
            {
                "connection_id": str(connection.id),
                "name": connection.name,
                "reason": f"Could not reach {spec.label}: {str(exc)[:200]}",
            }
        )
        return []


def _stream_key(stream: Any) -> str:
    """The name a snapshot is filed under.

    Qualified, not bare. A PostgreSQL database with `public.orders` and
    `analytics.orders` produces two streams called `orders`, and filing both
    under that name means the second is compared against the first's columns --
    drift reported between two unrelated tables -- and then collides on the
    unique index. `qualified_name` falls back to the bare name where a source
    has no namespaces, so nothing else changes.
    """
    return getattr(stream, "qualified_name", None) or stream.name


def _check_stream(
    db: Session,
    *,
    project_id: uuid.UUID,
    connection: Any,
    connector: Any,
    config: dict[str, Any],
    stream: Any,
    moment: datetime,
    open_incidents: bool,
    detect: Any,
    incidents: Any,
) -> StreamOutcome:
    spec = connector.spec
    key = _stream_key(stream)
    outcome = StreamOutcome(
        connection_id=str(connection.id),
        connection_name=connection.name,
        connector_type=spec.type,
        stream=key,
        checked=False,
    )

    current: dict[str, str] | None = None
    if spec.supports("schema"):
        try:
            current = _live_schema(connector, config, stream)
        except Exception as exc:  # noqa: BLE001 - "we could not look" is not drift
            outcome.skipped_reason = f"Could not read the columns: {str(exc)[:200]}"
    if not current:
        declared = declared_schema(spec.type, stream.name)
        if declared:
            current = declared
            outcome.source = "declared"
    if not current:
        outcome.skipped_reason = outcome.skipped_reason or (
            f"{spec.label} does not describe the columns of '{stream.name}' "
            "without reading it."
        )
        return outcome

    outcome.checked = True
    stored = _snapshot(db, project_id, connection.id, key)
    previous = dict(stored.columns_json or {}) if stored else None

    if previous is None:
        outcome.first_look = True
        outcome.summary = "First look; nothing to compare against yet."
    else:
        drift = detect(previous, current)
        outcome.severity = drift.severity
        outcome.summary = drift.summary
        outcome.added_columns = list(drift.added_columns)
        outcome.removed_columns = list(drift.removed_columns)
        outcome.type_changes = [change.to_dict() for change in drift.type_changes]

    if stored is None:
        stored = ConnectorSchemaSnapshot(
            project_id=project_id,
            connection_id=connection.id,
            connector_type=spec.type,
            stream_name=key,
        )
        db.add(stored)
    stored.columns_json = current
    stored.source = outcome.source
    stored.observed_at = moment
    stored.last_severity = outcome.severity
    stored.last_summary = outcome.summary or None
    if outcome.has_drift:
        stored.drift_count += 1

    if open_incidents:
        _record(
            db,
            incidents=incidents,
            project_id=project_id,
            connection=connection,
            outcome=outcome,
            moment=moment,
        )
    return outcome


def _record(
    db: Session,
    *,
    incidents: Any,
    project_id: uuid.UUID,
    connection: Any,
    outcome: StreamOutcome,
    moment: datetime,
) -> None:
    """File, escalate or close the incident for this stream."""
    mark = fingerprint(connection.id, outcome.stream)

    if not outcome.has_drift:
        closed = incidents.auto_resolve(
            db,
            project_id=project_id,
            fingerprint=mark,
            message=f"The schema of '{outcome.stream}' matches the last one seen.",
            now=moment,
        )
        if closed is not None:
            outcome.incident_id = str(closed.id)
        return

    severity = {"breaking": "critical", "risky": "high"}.get(outcome.severity, "medium")
    incident = incidents.report(
        db,
        project_id=project_id,
        fingerprint=mark,
        title=f"{connection.name}: '{outcome.stream}' changed shape",
        summary=outcome.summary,
        source_kind="drift",
        source_id=str(connection.id),
        severity=severity,
        context={
            "connector_type": outcome.connector_type,
            "connection_id": str(connection.id),
            "stream": outcome.stream,
            "added_columns": outcome.added_columns,
            "removed_columns": outcome.removed_columns,
            "type_changes": outcome.type_changes,
            "source": outcome.source,
        },
        now=moment,
    )
    outcome.incident_id = str(incident.id)
    logger.warning(
        "connector_schema_drift",
        extra={
            "connector_type": outcome.connector_type,
            "stream": outcome.stream,
            "severity": outcome.severity,
            "removed": outcome.removed_columns,
        },
    )


def watched_streams(db: Session, *, project_id: uuid.UUID) -> list[dict[str, Any]]:
    """Everything the watch is currently remembering, for the status view."""
    rows = db.scalars(
        select(ConnectorSchemaSnapshot)
        .where(ConnectorSchemaSnapshot.project_id == project_id)
        .order_by(ConnectorSchemaSnapshot.connector_type, ConnectorSchemaSnapshot.stream_name)
    ).all()
    return [
        {
            "connection_id": str(row.connection_id),
            "connector_type": row.connector_type,
            "stream": row.stream_name,
            "columns": len(row.columns_json or {}),
            "source": row.source,
            "observed_at": row.observed_at.isoformat() if row.observed_at else None,
            "last_severity": row.last_severity,
            "last_summary": row.last_summary,
            "drift_count": row.drift_count,
        }
        for row in rows
    ]
