"""Explaining why a number moved.

Phase 02 can say "the row count fell 40%". That is the easy half. The half that
saves an afternoon is "...because the filter on step 3 changed on the 14th",
and that has to be inferred from what else happened around the same time.

The method is correlation, stated as correlation. Nothing here proves cause: it
lines a metric's change up against every recorded event near it -- a pipeline
edit, a schema change, a quality failure, a run that behaved differently -- and
ranks them by how well they line up. A confident-sounding explanation that is
wrong is worse than a list of candidates, so the output says "this changed at
the same time", never "this caused it".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

# How far either side of the change to look. Wider than this and everything
# correlates with everything.
DEFAULT_WINDOW = timedelta(days=2)

# What each kind of event is worth as an explanation, before timing is applied.
KIND_WEIGHT: dict[str, float] = {
    "pipeline_edit": 1.0,
    "workflow_edit": 1.0,
    "schema_drift": 0.95,
    "quality_failure": 0.7,
    "upstream_change": 0.85,
    "run_status_change": 0.6,
    "config_change": 0.9,
}

EVENT_LABELS: dict[str, str] = {
    "pipeline_edit": "the pipeline was edited",
    "workflow_edit": "the workflow was edited",
    "schema_drift": "the source schema changed",
    "quality_failure": "a quality rule started failing",
    "upstream_change": "an upstream dataset changed",
    "run_status_change": "a run changed status",
    "config_change": "a setting changed",
}


@dataclass
class TimelineEvent:
    """Something that happened, which might explain something else."""

    kind: str
    at: datetime
    summary: str
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Explanation:
    kind: str
    at: datetime
    summary: str
    hours_apart: float
    score: float
    sentence: str
    detail: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "at": self.at.isoformat(),
            "summary": self.summary,
            "hours_apart": round(self.hours_apart, 2),
            "score": round(self.score, 3),
            "sentence": self.sentence,
            "detail": self.detail,
        }


@dataclass
class ExplanationReport:
    metric: str
    change_description: str
    candidates: list[Explanation]
    summary: str
    searched_events: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "change_description": self.change_description,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "summary": self.summary,
            "searched_events": self.searched_events,
        }


def _as_utc(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.replace(tzinfo=UTC)


def describe_change(metric: str, before: float | None, after: float) -> str:
    """The change itself, in a sentence, before anything explains it."""
    label = metric.replace("_", " ")
    if before is None:
        return f"{label} was first recorded at {_number(after)}."
    if before == 0:
        return f"{label} went from zero to {_number(after)}."

    ratio = (after - before) / abs(before)
    direction = "rose" if after > before else "fell"
    return f"{label} {direction} {abs(ratio):.0%}, from {_number(before)} to {_number(after)}."


def _number(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def explain(
    *,
    metric: str,
    changed_at: datetime,
    before: float | None,
    after: float,
    events: list[TimelineEvent],
    window: timedelta = DEFAULT_WINDOW,
    limit: int = 5,
) -> ExplanationReport:
    """Rank what happened near a change by how well it lines up with it."""
    moment = _as_utc(changed_at)
    change_description = describe_change(metric, before, after)

    candidates: list[Explanation] = []
    for event in events:
        at = _as_utc(event.at)
        gap = abs((moment - at).total_seconds())
        if gap > window.total_seconds():
            continue

        hours = gap / 3600
        # Closeness in time is the only evidence there is, so it dominates.
        # An event at the moment of the change scores 1; one at the edge of
        # the window scores near 0.
        proximity = max(0.0, 1 - gap / window.total_seconds())
        score = proximity * KIND_WEIGHT.get(event.kind, 0.5)

        candidates.append(
            Explanation(
                kind=event.kind,
                at=at,
                summary=event.summary,
                hours_apart=hours,
                score=score,
                sentence=_sentence(event, hours, at <= moment),
                detail=dict(event.detail),
            )
        )

    candidates.sort(key=lambda candidate: -candidate.score)
    trimmed = candidates[:limit]

    return ExplanationReport(
        metric=metric,
        change_description=change_description,
        candidates=trimmed,
        summary=_summarise(change_description, trimmed, window),
        searched_events=len(events),
    )


def _sentence(event: TimelineEvent, hours: float, before_change: bool) -> str:
    label = EVENT_LABELS.get(event.kind, event.kind.replace("_", " "))
    when = (
        "at the same time"
        if hours < 1
        else f"{hours:.0f} hours {'earlier' if before_change else 'later'}"
    )
    return f"{label.capitalize()} {when}: {event.summary}."


def _summarise(
    change_description: str, candidates: list[Explanation], window: timedelta
) -> str:
    if not candidates:
        days = int(window.total_seconds() // 86400) or 1
        return (
            f"{change_description} Nothing else was recorded within {days} day(s), "
            "so the cause is upstream of anything this platform can see."
        )

    best = candidates[0]
    tail = (
        f" {len(candidates) - 1} other change(s) happened nearby."
        if len(candidates) > 1
        else ""
    )
    # Deliberately "at the same time", not "because of": this is correlation.
    return f"{change_description} {best.sentence}{tail}"
