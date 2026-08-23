"""Schema drift detection.

Compares two schema snapshots and classifies what changed. Drift is graded by
how much downstream damage it can do:

``breaking``
    A column disappeared or changed to an incompatible type. Anything selecting
    or computing on that column breaks.
``risky``
    A type widened or narrowed in a way that usually still works but can
    silently change results (int -> float, string -> datetime).
``compatible``
    New columns only. Existing consumers are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Type changes that usually keep working but can change comparison or rounding
# behaviour. Anything not listed here is treated as breaking.
_TOLERABLE_TYPE_CHANGES: frozenset[tuple[str, str]] = frozenset(
    {
        ("int", "float"),
        ("int", "string"),
        ("float", "string"),
        ("boolean", "string"),
        ("datetime", "string"),
        ("empty", "string"),
        ("empty", "int"),
        ("empty", "float"),
        ("empty", "boolean"),
        ("empty", "datetime"),
    }
)

SEVERITY_ORDER = {"none": 0, "compatible": 1, "risky": 2, "breaking": 3}


@dataclass
class ColumnTypeChange:
    column: str
    previous_type: str
    current_type: str
    severity: str

    def to_dict(self) -> dict[str, str]:
        return {
            "column": self.column,
            "previous_type": self.previous_type,
            "current_type": self.current_type,
            "severity": self.severity,
        }


@dataclass
class DriftReport:
    severity: str
    added_columns: list[str] = field(default_factory=list)
    removed_columns: list[str] = field(default_factory=list)
    type_changes: list[ColumnTypeChange] = field(default_factory=list)
    reordered: bool = False
    summary: str = ""

    @property
    def has_drift(self) -> bool:
        return bool(self.added_columns or self.removed_columns or self.type_changes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "has_drift": self.has_drift,
            "added_columns": self.added_columns,
            "removed_columns": self.removed_columns,
            "type_changes": [change.to_dict() for change in self.type_changes],
            "reordered": self.reordered,
            "summary": self.summary,
        }


def _columns_from_schema(schema: dict[str, Any] | None) -> dict[str, str]:
    """Normalise a stored schema_json into {column: inferred_type}.

    Handles both the `{"columns": [{"name", "inferred_type"}]}` shape written by
    profiling and a plain `{column: type}` mapping.
    """
    if not schema:
        return {}

    columns = schema.get("columns") if isinstance(schema, dict) else None
    if isinstance(columns, list):
        resolved: dict[str, str] = {}
        for entry in columns:
            if isinstance(entry, dict) and entry.get("name"):
                resolved[str(entry["name"])] = str(
                    entry.get("inferred_type") or entry.get("type") or "unknown"
                )
        return resolved

    if isinstance(schema, dict) and all(isinstance(value, str) for value in schema.values()):
        return {str(key): str(value) for key, value in schema.items()}

    return {}


def _ordered_columns(schema: dict[str, Any] | None) -> list[str]:
    if not schema:
        return []
    ordered = schema.get("ordered_columns")
    if isinstance(ordered, list):
        return [str(column) for column in ordered]
    return list(_columns_from_schema(schema))


def detect_schema_drift(
    previous_schema: dict[str, Any] | None, current_schema: dict[str, Any] | None
) -> DriftReport:
    previous = _columns_from_schema(previous_schema)
    current = _columns_from_schema(current_schema)

    if not previous:
        return DriftReport(severity="none", summary="No previous schema to compare against.")

    added = sorted(set(current) - set(previous))
    removed = sorted(set(previous) - set(current))

    type_changes: list[ColumnTypeChange] = []
    for column in sorted(set(previous) & set(current)):
        before, after = previous[column], current[column]
        if before == after:
            continue
        tolerable = (before, after) in _TOLERABLE_TYPE_CHANGES
        type_changes.append(
            ColumnTypeChange(
                column=column,
                previous_type=before,
                current_type=after,
                severity="risky" if tolerable else "breaking",
            )
        )

    shared_before = [c for c in _ordered_columns(previous_schema) if c in current]
    shared_after = [c for c in _ordered_columns(current_schema) if c in previous]
    reordered = bool(shared_before and shared_after and shared_before != shared_after)

    if removed or any(change.severity == "breaking" for change in type_changes):
        severity = "breaking"
    elif any(change.severity == "risky" for change in type_changes):
        severity = "risky"
    elif added:
        severity = "compatible"
    else:
        severity = "none"

    parts: list[str] = []
    if added:
        parts.append(f"{len(added)} column(s) added")
    if removed:
        parts.append(f"{len(removed)} column(s) removed")
    if type_changes:
        parts.append(f"{len(type_changes)} type change(s)")
    if reordered and not parts:
        parts.append("column order changed")

    summary = ", ".join(parts).capitalize() if parts else "Schema is unchanged."

    return DriftReport(
        severity=severity,
        added_columns=added,
        removed_columns=removed,
        type_changes=type_changes,
        reordered=reordered,
        summary=summary,
    )
