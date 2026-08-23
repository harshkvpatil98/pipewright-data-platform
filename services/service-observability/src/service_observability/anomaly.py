"""Auto-baselining: is this run's number normal for this dataset?

Every alternative to a baseline is a person guessing a threshold. Thresholds
guessed in advance are either so loose they never fire or so tight they fire
constantly, and either way they get muted. So the baseline is learned from the
metric's own history.

The statistic is the **median absolute deviation**, not the standard deviation.
A mean and a standard deviation are both dragged around by the very outliers
this is meant to catch: one run with ten times the usual rows inflates the
spread enough to hide the next one. The median and MAD do not move.

Two cases need care rather than a formula:

* Too little history. Three points cannot establish what normal looks like, so
  this reports "no baseline" instead of pretending.
* A perfectly stable metric. MAD of zero makes the score infinite, which would
  flag a row count moving from 1000 to 1001 as an emergency. Stability is
  handled separately, with a relative tolerance.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median
from typing import Any, Sequence

from service_observability.metrics import describe, format_value

# Below this, "normal" is not yet a thing that exists.
MIN_HISTORY = 5

# Modified z-score thresholds. 3.5 is the conventional cutoff; the other two
# exist because some datasets are noisier than others and one number cannot fit.
SENSITIVITY_THRESHOLDS: dict[str, float] = {
    "low": 5.0,
    "medium": 3.5,
    "high": 2.5,
}
DEFAULT_SENSITIVITY = "medium"

# Consistency factor making MAD comparable to a standard deviation for normally
# distributed data.
_MAD_SCALE = 0.6745

# When a metric has never moved, this is how far it may move before it counts.
_FLAT_RELATIVE_TOLERANCE = 0.02
_FLAT_ABSOLUTE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class AnomalyVerdict:
    metric_key: str
    column_name: str | None
    value: float
    baseline: float | None
    score: float | None
    status: str  # "ok" | "anomalous" | "no_baseline"
    direction: str  # "above" | "below" | "flat"
    sample_size: int
    explanation: str

    @property
    def is_anomalous(self) -> bool:
        return self.status == "anomalous"

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric_key": self.metric_key,
            "column_name": self.column_name,
            "value": self.value,
            "baseline": self.baseline,
            "score": self.score,
            "status": self.status,
            "direction": self.direction,
            "sample_size": self.sample_size,
            "explanation": self.explanation,
        }


def _direction(value: float, baseline: float) -> str:
    if value > baseline:
        return "above"
    if value < baseline:
        return "below"
    return "flat"


def _percentage_change(value: float, baseline: float) -> str:
    if baseline == 0:
        return "from zero"
    change = (value - baseline) / abs(baseline) * 100
    return f"{abs(change):.0f}% {'above' if change > 0 else 'below'}"


def detect_anomaly(
    *,
    metric_key: str,
    value: float,
    history: Sequence[float],
    column_name: str | None = None,
    sensitivity: str = DEFAULT_SENSITIVITY,
) -> AnomalyVerdict:
    """Judge one measurement against what this metric has done before.

    ``history`` is prior values only; passing the current value in would let it
    pull its own baseline toward itself.
    """
    threshold = SENSITIVITY_THRESHOLDS.get(sensitivity, SENSITIVITY_THRESHOLDS[DEFAULT_SENSITIVITY])
    usable = [float(item) for item in history if isinstance(item, (int, float)) and not isinstance(item, bool)]
    label = describe(metric_key, column_name)

    if len(usable) < MIN_HISTORY:
        return AnomalyVerdict(
            metric_key=metric_key,
            column_name=column_name,
            value=value,
            baseline=None,
            score=None,
            status="no_baseline",
            direction="flat",
            sample_size=len(usable),
            explanation=(
                f"{len(usable)} of the {MIN_HISTORY} runs needed to establish what a normal "
                f"{label} looks like."
            ),
        )

    baseline = median(usable)
    deviations = [abs(item - baseline) for item in usable]
    mad = median(deviations)
    direction = _direction(value, baseline)

    if mad <= _FLAT_ABSOLUTE_TOLERANCE:
        # The metric has never moved. Judge by relative change instead, so a
        # trivially different number does not read as a crisis.
        allowed = max(abs(baseline) * _FLAT_RELATIVE_TOLERANCE, _FLAT_ABSOLUTE_TOLERANCE)
        drift = abs(value - baseline)
        if drift <= allowed:
            return AnomalyVerdict(
                metric_key=metric_key,
                column_name=column_name,
                value=value,
                baseline=baseline,
                score=0.0,
                status="ok",
                direction=direction,
                sample_size=len(usable),
                explanation=(
                    f"{label} has been {format_value(metric_key, baseline)} for the last "
                    f"{len(usable)} runs and still is."
                ),
            )
        return AnomalyVerdict(
            metric_key=metric_key,
            column_name=column_name,
            value=value,
            baseline=baseline,
            score=None,
            status="anomalous",
            direction=direction,
            sample_size=len(usable),
            explanation=(
                f"{label} was exactly {format_value(metric_key, baseline)} for "
                f"{len(usable)} runs and is now {format_value(metric_key, value)}."
            ),
        )

    score = _MAD_SCALE * (value - baseline) / mad
    status = "anomalous" if abs(score) >= threshold else "ok"

    if status == "anomalous":
        explanation = (
            f"{label} is {format_value(metric_key, value)}, "
            f"{_percentage_change(value, baseline)} the usual "
            f"{format_value(metric_key, baseline)} across the last {len(usable)} runs."
        )
    else:
        explanation = (
            f"{label} is {format_value(metric_key, value)}, in line with the usual "
            f"{format_value(metric_key, baseline)}."
        )

    return AnomalyVerdict(
        metric_key=metric_key,
        column_name=column_name,
        value=value,
        baseline=baseline,
        score=round(score, 3),
        status=status,
        direction=direction,
        sample_size=len(usable),
        explanation=explanation,
    )


# How far a value has to move to be worth waking someone for, expressed as a
# ratio rather than a percentage. A percentage cannot describe a collapse: a
# row count falling to zero is only "100% below", the same headline number as
# a metric that merely halved twice over, when losing every row is the single
# worst thing that can happen to a dataset. A ratio is symmetric -- ten times
# as many rows and a tenth as many both read as 10.
_CRITICAL_RATIO = 3.0
_HIGH_RATIO = 1.5


def severity_for(verdict: AnomalyVerdict) -> str:
    """How loudly an anomaly should be raised.

    The score decides *whether* something is unusual; the size of the move
    decides *how much it matters*. Keeping those separate is what stops a
    metric that never varies from reporting every small change as an emergency.
    """
    if not verdict.is_anomalous:
        return "low"
    if verdict.baseline is None:
        return "medium"

    value, baseline = verdict.value, verdict.baseline

    if baseline == 0:
        # Something that was always zero is now not. Notable, rarely critical.
        return "high"
    if value == 0:
        # The measurement vanished: no rows, no distinct values, nothing.
        return "critical"
    if (value > 0) != (baseline > 0):
        # A sign flip is never a small change.
        return "critical"

    magnitudes = (abs(value), abs(baseline))
    ratio = max(magnitudes) / min(magnitudes)
    if ratio >= _CRITICAL_RATIO:
        return "critical"
    if ratio >= _HIGH_RATIO:
        return "high"
    return "medium"
