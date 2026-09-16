"""Watching a connector's schema for the day the vendor changes it.

SaaS APIs change without telling anybody. A pipeline built against a field
called `attributes.created` keeps working until the morning it is
`attributes.created_at`, and the first sign is a run failing at three in the
morning with a column that no longer exists.

So the schema is re-read on a schedule and compared with the last one seen. The
comparison is Phase 02's `detect_schema_drift`, unchanged: the same three grades
a dataset's drift uses, because "a column disappeared" means the same thing
whether it disappeared from a CSV or from Klaviyo. Reusing it also means the
incident, the grading and the UI that shows them already exist.

What this does *not* do is guess. A connector that cannot describe its schema
without a live credential is reported as unwatchable rather than assumed fine --
which, at two hundred connectors, is most of them, and saying so is the point.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from shared_python.logging import get_logger

from service_connectors.registry import get, specs

logger = get_logger(__name__)


@dataclass
class WatchResult:
    """What one connector's check found."""

    connector_type: str
    label: str
    checked: bool
    severity: str = "none"
    summary: str = ""
    added_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    type_changes: list[dict[str, str]] = field(default_factory=list)
    #: Why it was not checked, when it was not.
    skipped_reason: str = ""
    stream: str | None = None

    @property
    def has_drift(self) -> bool:
        return bool(self.added_columns or self.removed_columns or self.type_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "connector_type": self.connector_type,
            "label": self.label,
            "checked": self.checked,
            "severity": self.severity,
            "summary": self.summary,
            "added_columns": list(self.added_columns),
            "removed_columns": list(self.removed_columns),
            "type_changes": list(self.type_changes),
            "skipped_reason": self.skipped_reason,
            "stream": self.stream,
        }


@dataclass
class WatchReport:
    checked_at: str
    results: list[WatchResult] = field(default_factory=list)

    @property
    def drifted(self) -> list[WatchResult]:
        return [result for result in self.results if result.has_drift]

    @property
    def breaking(self) -> list[WatchResult]:
        return [result for result in self.results if result.severity == "breaking"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "checked_at": self.checked_at,
            "checked": sum(1 for result in self.results if result.checked),
            "skipped": sum(1 for result in self.results if not result.checked),
            "drifted": len(self.drifted),
            "breaking": len(self.breaking),
            "results": [result.to_dict() for result in self.results],
        }


def describable() -> list[str]:
    """Connectors whose schema can be read without a live credential.

    A manifest that declares its columns can be checked from the file alone,
    which is exactly the case that matters: a vendor changing their API is
    caught by the manifest going stale relative to reality, and a manifest
    with no declared schema has nothing to go stale.
    """
    found: list[str] = []
    for spec in specs():
        if spec.origin != "manifest":
            continue
        connector = get(spec.type)
        manifest = getattr(connector, "manifest", None)
        if manifest is None:
            continue
        if any(stream.schema_fields for stream in manifest.streams):
            found.append(spec.type)
    return found


def declared_schema(connector_type: str, stream_name: str | None = None) -> dict[str, str] | None:
    """The columns a manifest says a stream has, in drift-comparison shape."""
    connector = get(connector_type)
    manifest = getattr(connector, "manifest", None)
    if manifest is None:
        return None
    for stream in manifest.streams:
        if stream_name is not None and stream.name != stream_name:
            continue
        if not stream.schema_fields:
            continue
        return {
            (spec.rename or path.split(".")[-1]): _drift_type(spec.type)
            for path, spec in stream.schema_fields.items()
        }
    return None


#: The manifest vocabulary, in the words `detect_schema_drift` grades by.
_DRIFT_TYPES = {
    "STRING": "string", "INTEGER": "int", "BIGINT": "int", "FLOAT": "float",
    "DECIMAL": "float", "BOOLEAN": "boolean", "DATE": "datetime",
    "TIME": "string", "TIMESTAMP": "datetime", "JSON": "string",
    "ARRAY": "string", "UUID": "string", "BYTES": "string",
}


def _drift_type(declared: str) -> str:
    return _DRIFT_TYPES.get(declared.upper(), "string")


def check(
    connector_type: str,
    *,
    previous: dict[str, str] | None,
    config: dict[str, Any] | None = None,
    stream_name: str | None = None,
) -> WatchResult:
    """Compare a connector's current schema with the last one seen."""
    from service_quality.drift import detect_schema_drift

    spec = get(connector_type).spec
    result = WatchResult(connector_type=connector_type, label=spec.label, checked=False)

    current = _live_schema(connector_type, config, stream_name) if config else None
    if current is None:
        current = declared_schema(connector_type, stream_name)
    if current is None:
        result.skipped_reason = (
            f"{spec.label} does not describe its columns without a live "
            "connection, so there is nothing to compare."
        )
        return result

    result.checked = True
    result.stream = stream_name
    if previous is None:
        result.summary = "First look; nothing to compare against yet."
        return result

    report = detect_schema_drift(previous, current)
    result.severity = report.severity
    result.summary = report.summary
    result.added_columns = list(report.added_columns)
    result.removed_columns = list(report.removed_columns)
    result.type_changes = [change.to_dict() for change in report.type_changes]

    if report.severity == "breaking":
        logger.warning(
            "connector_schema_drift",
            extra={
                "connector_type": connector_type,
                "severity": report.severity,
                "removed": result.removed_columns,
            },
        )
    return result


def _live_schema(
    connector_type: str, config: dict[str, Any], stream_name: str | None
) -> dict[str, str] | None:
    """Ask the source itself, where a credential makes that possible."""
    connector = get(connector_type)
    spec = connector.spec
    if not spec.supports("schema") or not spec.available:
        return None
    try:
        streams = connector.discover(config)  # type: ignore[attr-defined]
        chosen = next(
            (stream for stream in streams if stream_name is None or stream.name == stream_name),
            None,
        )
        if chosen is None:
            return None
        return {
            column.name: normalise_type(column.data_type)
            for column in connector.columns(config, chosen)  # type: ignore[attr-defined]
        }
    except Exception as exc:  # noqa: BLE001 - a source that will not answer is a skip
        logger.info(
            "connector_schema_unavailable",
            extra={"connector_type": connector_type, "error": str(exc)[:200]},
        )
        return None


def normalise_type(data_type: str) -> str:
    lowered = str(data_type).lower()
    if any(token in lowered for token in ("int", "serial")):
        return "int"
    if any(token in lowered for token in ("float", "double", "numeric", "decimal", "real")):
        return "float"
    if "bool" in lowered:
        return "boolean"
    if any(token in lowered for token in ("date", "time")):
        return "datetime"
    return "string"


def sweep(
    seen: dict[str, dict[str, str]] | None = None,
    *,
    connector_types: list[str] | None = None,
) -> WatchReport:
    """Check every watchable connector against the last schema recorded.

    **This is the catalogue-level sweep, and it is not the nightly job.** It
    compares what each *manifest* declares against a caller-supplied previous
    state, needs no database and no credential, and answers "have the shipped
    declarations moved". The nightly job is `sweep.sweep_project`: it walks a
    project's configured connections, reads the schema from the source itself,
    stores what it saw and files incidents.

    `seen` maps a connector type to the columns last observed. Callers keep it;
    this module does not, because where it is stored is a decision about the
    schedule, not about drift.
    """
    previous = seen or {}
    targets = connector_types if connector_types is not None else describable()
    return WatchReport(
        checked_at=datetime.now(timezone.utc).isoformat(),
        results=[check(name, previous=previous.get(name)) for name in targets],
    )
