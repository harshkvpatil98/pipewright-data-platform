"""Numbers an operator can point a dashboard at.

Prometheus text format rather than a client library: the format is a dozen lines
to produce, and a scrape endpoint that depends on nothing cannot break the
service it is meant to be watching.

What is deliberately *not* here: request-level metrics. Those come from the
gateway's own middleware, which already times every request; duplicating them
here would produce two numbers for one thing and an argument about which is
right.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

# Prometheus names: letters, digits, and underscores, starting with a letter.
_NAME_PATTERN = re.compile(r"[^a-zA-Z0-9_]")
_LABEL_ESCAPES = str.maketrans({"\\": "\\\\", '"': '\\"', "\n": "\\n"})

PREFIX = "pipewright"


@dataclass(frozen=True)
class Metric:
    name: str
    value: float
    help: str
    kind: str = "gauge"
    labels: tuple[tuple[str, str], ...] = ()

    @property
    def full_name(self) -> str:
        return f"{PREFIX}_{_NAME_PATTERN.sub('_', self.name)}"


def _render_labels(labels: tuple[tuple[str, str], ...]) -> str:
    if not labels:
        return ""
    rendered = ",".join(
        f'{_NAME_PATTERN.sub("_", key)}="{str(value).translate(_LABEL_ESCAPES)}"'
        for key, value in labels
    )
    return "{" + rendered + "}"


def render(metrics: Iterable[Metric]) -> str:
    """The Prometheus exposition format.

    HELP and TYPE are emitted once per metric name even when the same name
    appears with several label sets -- repeating them is a parse error, and a
    scrape that fails is worse than one metric missing.
    """
    lines: list[str] = []
    described: set[str] = set()

    for metric in metrics:
        if metric.full_name not in described:
            lines.append(f"# HELP {metric.full_name} {metric.help}")
            lines.append(f"# TYPE {metric.full_name} {metric.kind}")
            described.add(metric.full_name)
        value = int(metric.value) if float(metric.value).is_integer() else metric.value
        lines.append(f"{metric.full_name}{_render_labels(metric.labels)} {value}")

    return "\n".join(lines) + "\n"


def collect(db: Any) -> list[Metric]:
    """Everything worth watching, counted at scrape time.

    Counted on demand rather than tracked in memory: a counter held in a process
    resets on every deploy and disagrees between replicas, and these are all
    cheap aggregate queries.
    """
    from sqlalchemy import func, select

    metrics: list[Metric] = []

    def _count(model, name: str, help_text: str, **filters: Any) -> None:
        statement = select(func.count(model.id))
        for column, value in filters.items():
            statement = statement.where(getattr(model, column) == value)
        metrics.append(Metric(name=name, value=db.scalar(statement) or 0, help=help_text))

    from service_datasets.models import Dataset
    from service_projects.models import Project

    _count(Project, "projects_total", "Projects that exist.")
    _count(Dataset, "datasets_total", "Datasets that exist.")

    try:
        from service_workflows.models import Workflow, WorkflowRun

        _count(Workflow, "workflows_total", "Workflows defined.")
        for status in ("queued", "running", "succeeded", "failed"):
            metrics.append(
                Metric(
                    name="workflow_runs_total",
                    value=db.scalar(
                        select(func.count(WorkflowRun.id)).where(WorkflowRun.status == status)
                    )
                    or 0,
                    help="Workflow runs by status.",
                    kind="counter",
                    labels=(("status", status),),
                )
            )
    except ImportError:  # pragma: no cover - workflows is optional
        pass

    try:
        from service_observability.models import DatasetMetric, Incident

        for severity in ("critical", "high", "medium", "low"):
            metrics.append(
                Metric(
                    name="incidents_open",
                    value=db.scalar(
                        select(func.count(Incident.id)).where(
                            Incident.status.in_(("open", "acknowledged")),
                            Incident.severity == severity,
                        )
                    )
                    or 0,
                    help="Open incidents by severity.",
                    labels=(("severity", severity),),
                )
            )
        _count(DatasetMetric, "dataset_metrics_total", "Metric samples recorded.")
    except ImportError:  # pragma: no cover
        pass

    try:
        from service_enterprise.models import Organisation, UsageRecord

        _count(Organisation, "organisations_total", "Tenants on this deployment.")
        totals = db.execute(
            select(
                func.coalesce(func.sum(UsageRecord.rows_processed), 0),
                func.coalesce(func.sum(UsageRecord.compute_ms), 0.0),
            )
        ).one()
        metrics.append(
            Metric("rows_processed_total", float(totals[0]), "Rows processed, all time.", "counter")
        )
        metrics.append(
            Metric(
                "compute_seconds_total",
                round(float(totals[1]) / 1000, 3),
                "Compute seconds spent, all time.",
                "counter",
            )
        )
    except ImportError:  # pragma: no cover
        pass

    return metrics
