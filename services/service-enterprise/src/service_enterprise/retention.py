"""Deleting things on purpose, and proving a person was removed.

Two different obligations that share machinery:

**Retention** is a schedule. Runs, metrics, and audit entries accumulate
forever otherwise, and "forever" is both a cost and a liability. A policy says
how long, and the sweep enforces it.

**Erasure** is a request from a person about themselves. It has to find every
place their data sits and either remove or redact it, and -- the part that is
usually forgotten -- produce evidence of what was done, because the obligation
is to be able to answer afterwards.

Both default to reporting rather than deleting. A retention policy that starts
deleting the moment it is saved is a policy nobody dares create.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pandas as pd

# What can have a retention policy, and what deleting it means.
RETAINABLE = {
    "workflow_runs": "Completed workflow runs and their node history",
    "pipeline_runs": "Pipeline run records",
    "dataset_metrics": "Recorded metric history",
    "audit_entries": "Audit log entries",
    "report_deliveries": "Generated report records",
    "incidents": "Resolved incidents",
    # Superseded dataset versions: never the current one, never one something
    # is holding open. Removal follows a grace period (see
    # `service_datasets.version_lifecycle`), so "deleted" here means "marked";
    # the bytes go on a later sweep.
    "dataset_versions": "Superseded dataset versions (never the current or a pinned one)",
}

MIN_RETAIN_DAYS = 1
# Ten years. Beyond this a retention policy is not expressing a decision.
MAX_RETAIN_DAYS = 3650

ERASURE_KINDS = ("email", "phone", "id", "name")

# Columns worth searching for a subject, by kind.
_KIND_HINTS: dict[str, tuple[str, ...]] = {
    "email": ("email", "e_mail", "mail", "contact"),
    "phone": ("phone", "mobile", "cell", "telephone"),
    "id": ("id", "customer_id", "user_id", "subject_id", "account"),
    "name": ("name", "customer_name", "full_name", "surname"),
}


@dataclass
class DeletionPlan:
    resource_type: str
    cutoff: datetime
    matched: int
    dry_run: bool
    deleted: int = 0
    #: Resource types whose deletion is staged (dataset versions) report the
    #: stage they reached here; the summary reads it.
    detail: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        payload = {
            "resource_type": resource_type_label(self.resource_type),
            "cutoff": self.cutoff.isoformat(),
            "matched": self.matched,
            "deleted": self.deleted,
            "dry_run": self.dry_run,
            "summary": self.summary(),
        }
        if self.detail is not None:
            payload["detail"] = dict(self.detail)
        return payload

    def summary(self) -> str:
        if self.resource_type == "dataset_versions" and self.detail is not None:
            return self._versions_summary()
        if self.matched == 0:
            return f"Nothing older than {self.cutoff.date()} to remove."
        if self.dry_run:
            return (
                f"{self.matched:,} {resource_type_label(self.resource_type).lower()} are older "
                f"than {self.cutoff.date()}. Nothing was deleted -- this policy is in "
                "report-only mode."
            )
        return f"Deleted {self.deleted:,} record(s) older than {self.cutoff.date()}."

    def _versions_summary(self) -> str:
        detail = self.detail or {}
        if self.dry_run:
            would = int(detail.get("would_schedule", 0))
            if would == 0:
                return f"No superseded version older than {self.cutoff.date()} to remove."
            return (
                f"{would:,} superseded version(s) are older than {self.cutoff.date()}. Nothing "
                "was scheduled -- this policy is in report-only mode."
            )
        parts: list[str] = []
        scheduled = int(detail.get("scheduled", 0))
        pruned = int(detail.get("pruned", 0))
        rescued = int(detail.get("rescued", 0))
        if scheduled:
            parts.append(f"scheduled {scheduled:,} superseded version(s) for removal after the grace period")
        if pruned:
            parts.append(f"removed {pruned:,} version(s) whose grace period had ended")
        if rescued:
            parts.append(f"kept {rescued:,} that were pinned or current again by then")
        if not parts:
            return f"No superseded version older than {self.cutoff.date()} to remove."
        return ("; ".join(parts)).capitalize() + "."


def resource_type_label(resource_type: str) -> str:
    return RETAINABLE.get(resource_type, resource_type.replace("_", " "))


def cutoff_for(retain_days: int, *, now: datetime | None = None) -> datetime:
    return (now or datetime.now(UTC)) - timedelta(days=retain_days)


@dataclass
class ColumnHit:
    dataset_name: str
    column: str
    rows: int

    def to_dict(self) -> dict[str, Any]:
        return {"dataset": self.dataset_name, "column": self.column, "rows": self.rows}


@dataclass
class ErasureReport:
    subject_value: str
    subject_kind: str
    datasets_searched: int
    hits: list[ColumnHit] = field(default_factory=list)
    unsearchable: list[str] = field(default_factory=list)
    #: "correction" (forward-moving; live data cleared, history retained) or
    #: "destructive" (also removed from historical artifacts -- see P7).
    mode: str = "correction"
    #: Datasets whose live file was redacted.
    erased: list[str] = field(default_factory=list)
    #: Datasets that could NOT be erased, each with a reason. Their presence is
    #: what turns a claimed erasure into "partial" rather than "completed" --
    #: the whole point is never to report success while data remains.
    blocked: list[dict[str, str]] = field(default_factory=list)

    @property
    def rows_affected(self) -> int:
        return sum(hit.rows for hit in self.hits)

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_value": _partial(self.subject_value),
            "subject_kind": self.subject_kind,
            "datasets_searched": self.datasets_searched,
            "hits": [hit.to_dict() for hit in self.hits],
            "unsearchable": self.unsearchable,
            "rows_affected": self.rows_affected,
            "mode": self.mode,
            "erased": self.erased,
            "blocked": self.blocked,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        if not self.hits and not self.unsearchable:
            return (
                f"Searched {self.datasets_searched} dataset(s). This person does not appear "
                "in any of them."
            )
        parts = []
        if self.hits:
            places = ", ".join(f"{hit.dataset_name}.{hit.column}" for hit in self.hits[:4])
            parts.append(
                f"Found in {len(self.hits)} place(s) across {self.rows_affected} row(s): {places}"
            )
        if self.unsearchable:
            parts.append(
                f"{len(self.unsearchable)} dataset(s) could not be searched and were skipped"
            )
        return ". ".join(parts) + "."


def _partial(value: str) -> str:
    """Never echo the whole subject value back in a stored report."""
    if "@" in value:
        local, _, domain = value.partition("@")
        return f"{local[:1]}***@{domain}"
    return f"{value[:2]}***" if len(value) > 2 else "***"


def candidate_columns(columns: list[str], kind: str) -> list[str]:
    """Columns worth searching for a subject of this kind.

    Searching every column of every dataset would be correct and unusable; this
    narrows to the ones that plausibly hold the value, and the ones it skips are
    reported so the narrowing is visible.
    """
    hints = _KIND_HINTS.get(kind, ())
    matched = [
        column
        for column in columns
        if any(hint in re.sub(r"[^a-z0-9]", "_", column.lower()) for hint in hints)
    ]
    return matched or list(columns)


def find_subject(frame: pd.DataFrame, value: str, columns: list[str]) -> list[tuple[str, int]]:
    """Where a subject appears, and in how many rows."""
    needle = value.strip().casefold()
    hits: list[tuple[str, int]] = []

    for column in columns:
        if column not in frame.columns:
            continue
        matches = frame[column].astype("string").str.strip().str.casefold() == needle
        count = int(matches.sum())
        if count:
            hits.append((column, count))
    return hits


def redact_subject(
    frame: pd.DataFrame, value: str, columns: list[str], *, replacement: str = "[erased]"
) -> tuple[pd.DataFrame, int]:
    """Replace a subject's values in place.

    Redaction rather than row deletion, deliberately: deleting the rows changes
    every historical total computed from this dataset, and an erasure obligation
    is about the person's data, not about rewriting the past.
    """
    needle = value.strip().casefold()
    working = frame.copy()
    affected = 0

    for column in columns:
        if column not in working.columns:
            continue
        matches = working[column].astype("string").str.strip().str.casefold() == needle
        count = int(matches.sum())
        if count:
            working.loc[matches, column] = replacement
            affected += count
    return working, affected
