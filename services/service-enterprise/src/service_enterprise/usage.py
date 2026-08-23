"""What the platform's work costs, attributed to what did it.

"The warehouse bill went up" is a question nobody can answer without knowing
which pipeline processes the most rows. This records three things per unit of
work -- rows, compute time, bytes written -- and attributes them to the pipeline,
workflow, or report responsible.

Deliberately not priced. A currency figure would need per-deployment rates for
compute and storage that this platform has no way to know, and an invented one
would be quoted in a meeting. Rows and seconds are facts; money is not.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

SUBJECT_TYPES = ("pipeline", "workflow", "extraction_job", "report", "dataset")

# Periods a usage question is usually asked about.
PERIODS = {"day": 1, "week": 7, "month": 30, "quarter": 90}


@dataclass
class UsageTotal:
    subject_type: str
    subject_id: str | None
    subject_name: str
    runs: int
    rows_processed: int
    compute_ms: float
    bytes_written: int

    @property
    def compute_seconds(self) -> float:
        return round(self.compute_ms / 1000, 2)

    @property
    def average_rows_per_run(self) -> float:
        return round(self.rows_processed / self.runs, 1) if self.runs else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject_type": self.subject_type,
            "subject_id": self.subject_id,
            "subject_name": self.subject_name,
            "runs": self.runs,
            "rows_processed": self.rows_processed,
            "compute_seconds": self.compute_seconds,
            "bytes_written": self.bytes_written,
            "average_rows_per_run": self.average_rows_per_run,
        }


@dataclass
class UsageReport:
    period_days: int
    since: datetime
    totals: list[UsageTotal] = field(default_factory=list)
    rows_processed: int = 0
    compute_seconds: float = 0.0
    bytes_written: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "period_days": self.period_days,
            "since": self.since.isoformat(),
            "totals": [total.to_dict() for total in self.totals],
            "rows_processed": self.rows_processed,
            "compute_seconds": self.compute_seconds,
            "bytes_written": self.bytes_written,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        if not self.totals:
            return f"Nothing has run in the last {self.period_days} day(s)."

        biggest = self.totals[0]
        share = (
            biggest.rows_processed / self.rows_processed * 100 if self.rows_processed else 0
        )
        return (
            f"{self.rows_processed:,} rows and {self.compute_seconds:,.0f} compute seconds "
            f"in {self.period_days} day(s). '{biggest.subject_name}' accounts for "
            f"{share:.0f}% of the rows."
        )


def record(
    db: Any,
    *,
    project_id: uuid.UUID,
    subject_type: str,
    subject_id: uuid.UUID | None,
    subject_name: str | None,
    rows_processed: int = 0,
    compute_ms: float = 0.0,
    bytes_written: int = 0,
    organisation_id: uuid.UUID | None = None,
    now: datetime | None = None,
) -> None:
    """Note what one piece of work cost.

    Called from run paths, so it never raises: an accounting record that failed
    to write is a gap in a report, and a run that failed because of one is an
    outage.
    """
    from shared_python.logging import get_logger

    from service_enterprise.models import UsageRecord

    try:
        db.add(
            UsageRecord(
                organisation_id=organisation_id,
                project_id=project_id,
                subject_type=subject_type,
                subject_id=subject_id,
                subject_name=(subject_name or "")[:200] or None,
                rows_processed=max(int(rows_processed), 0),
                compute_ms=max(float(compute_ms), 0.0),
                bytes_written=max(int(bytes_written), 0),
                recorded_at=now or datetime.now(UTC),
            )
        )
        db.flush()
    except Exception:  # noqa: BLE001 - see docstring
        get_logger(__name__).exception("usage_record_failed project_id=%s", project_id)


def summarise(
    db: Any,
    *,
    project_id: uuid.UUID | None = None,
    organisation_id: uuid.UUID | None = None,
    period_days: int = 30,
    now: datetime | None = None,
    limit: int = 20,
) -> UsageReport:
    """Where the work went, biggest first."""
    from sqlalchemy import func, select

    from service_enterprise.models import UsageRecord

    since = (now or datetime.now(UTC)) - timedelta(days=period_days)
    statement = (
        select(
            UsageRecord.subject_type,
            UsageRecord.subject_id,
            func.max(UsageRecord.subject_name),
            func.count(UsageRecord.id),
            func.coalesce(func.sum(UsageRecord.rows_processed), 0),
            func.coalesce(func.sum(UsageRecord.compute_ms), 0.0),
            func.coalesce(func.sum(UsageRecord.bytes_written), 0),
        )
        .where(UsageRecord.recorded_at >= since)
        .group_by(UsageRecord.subject_type, UsageRecord.subject_id)
    )
    if project_id is not None:
        statement = statement.where(UsageRecord.project_id == project_id)
    if organisation_id is not None:
        statement = statement.where(UsageRecord.organisation_id == organisation_id)

    totals = [
        UsageTotal(
            subject_type=row[0],
            subject_id=str(row[1]) if row[1] else None,
            subject_name=row[2] or row[0].replace("_", " "),
            runs=int(row[3]),
            rows_processed=int(row[4]),
            compute_ms=float(row[5]),
            bytes_written=int(row[6]),
        )
        for row in db.execute(statement).all()
    ]
    totals.sort(key=lambda total: -total.rows_processed)

    report = UsageReport(period_days=period_days, since=since, totals=totals[:limit])
    report.rows_processed = sum(total.rows_processed for total in totals)
    report.compute_seconds = round(sum(total.compute_ms for total in totals) / 1000, 2)
    report.bytes_written = sum(total.bytes_written for total in totals)
    return report
