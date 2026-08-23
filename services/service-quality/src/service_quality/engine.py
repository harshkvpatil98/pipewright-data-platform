"""Evaluate a set of rules against a dataset and split out failing rows.

Severity drives behaviour:

``error``
    Failures quarantine their rows and mark the overall verdict as failed, which
    is what a pipeline gate acts on.
``warning``
    Failures are recorded and surfaced, but rows stay in the dataset and the
    verdict is unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from service_quality.rules.base import DATASET_LEVEL_RULES, RuleEvaluation
from service_quality.rules.evaluators import RULE_EVALUATORS
from shared_python.errors import BadRequestError


@dataclass
class EvaluatedRule:
    rule_id: str | None
    name: str
    rule_type: str
    severity: str
    evaluation: RuleEvaluation

    def to_summary(self) -> dict[str, Any]:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "rule_type": self.rule_type,
            "severity": self.severity,
            "status": self.evaluation.status,
            "evaluated_rows": self.evaluation.evaluated_rows,
            "failed_rows": self.evaluation.failed_rows,
            "failure_rate": self.evaluation.failure_rate,
            "message": self.evaluation.message,
            "details": self.evaluation.details,
        }


@dataclass
class RulesetResult:
    status: str  # "passed" | "failed" | "warning"
    results: list[EvaluatedRule]
    passing_frame: pd.DataFrame
    quarantined_frame: pd.DataFrame
    warnings: list[str] = field(default_factory=list)

    @property
    def error_failures(self) -> list[EvaluatedRule]:
        return [r for r in self.results if r.severity == "error" and r.evaluation.status == "failed"]

    @property
    def warning_failures(self) -> list[EvaluatedRule]:
        return [r for r in self.results if r.severity == "warning" and r.evaluation.status == "failed"]

    def to_summary(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "rules_evaluated": len(self.results),
            "rules_failed": len([r for r in self.results if r.evaluation.status == "failed"]),
            "error_failures": len(self.error_failures),
            "warning_failures": len(self.warning_failures),
            "rows_in": int(len(self.passing_frame)) + int(len(self.quarantined_frame)),
            "rows_passing": int(len(self.passing_frame)),
            "rows_quarantined": int(len(self.quarantined_frame)),
            "results": [r.to_summary() for r in self.results],
            "warnings": self.warnings,
        }


def evaluate_rule(dataframe: pd.DataFrame, *, rule_type: str, config: dict[str, Any]) -> RuleEvaluation:
    evaluator = RULE_EVALUATORS.get(rule_type)
    if evaluator is None:
        raise BadRequestError(
            f"Unsupported rule type '{rule_type}'. Supported: {', '.join(sorted(RULE_EVALUATORS))}."
        )
    return evaluator(dataframe, config or {})


def evaluate_ruleset(
    dataframe: pd.DataFrame,
    rules: list[dict[str, Any]],
    *,
    quarantine: bool = False,
) -> RulesetResult:
    """Run every rule, then optionally split failing rows into a quarantine frame."""
    results: list[EvaluatedRule] = []
    warnings: list[str] = []

    # Rows failing any error-severity, row-level rule.
    quarantine_mask = pd.Series(False, index=dataframe.index)

    for rule in rules:
        rule_type = str(rule.get("rule_type", ""))
        severity = str(rule.get("severity", "error")).lower()
        name = str(rule.get("name") or rule_type or "unnamed rule")

        try:
            evaluation = evaluate_rule(dataframe, rule_type=rule_type, config=rule.get("config") or {})
        except BadRequestError as exc:
            # A misconfigured rule must not abort the whole run; record it as a
            # failure of that rule so the operator can see and fix it.
            evaluation = RuleEvaluation(
                status="failed",
                evaluated_rows=int(len(dataframe)),
                failed_rows=0,
                message=f"Rule could not be evaluated: {exc.detail}",
                details={"configuration_error": True},
            )
            warnings.append(f"Rule '{name}' is misconfigured: {exc.detail}")

        results.append(
            EvaluatedRule(
                rule_id=str(rule["id"]) if rule.get("id") else None,
                name=name,
                rule_type=rule_type,
                severity=severity,
                evaluation=evaluation,
            )
        )

        if (
            quarantine
            and severity == "error"
            and evaluation.status == "failed"
            and evaluation.failure_mask is not None
        ):
            quarantine_mask |= evaluation.failure_mask.reindex(dataframe.index, fill_value=False)

    for result in results:
        if (
            result.severity == "error"
            and result.evaluation.status == "failed"
            and result.rule_type in DATASET_LEVEL_RULES
        ):
            warnings.append(
                f"'{result.name}' is a dataset-level rule, so its failure cannot be quarantined by row."
            )

    if quarantine and bool(quarantine_mask.any()):
        quarantined = dataframe.loc[quarantine_mask].reset_index(drop=True)
        passing = dataframe.loc[~quarantine_mask].reset_index(drop=True)
    else:
        quarantined = dataframe.iloc[0:0].reset_index(drop=True)
        passing = dataframe.reset_index(drop=True)

    error_failed = any(r.severity == "error" and r.evaluation.status == "failed" for r in results)
    warning_failed = any(r.severity == "warning" and r.evaluation.status == "failed" for r in results)

    if error_failed:
        status = "failed"
    elif warning_failed:
        status = "warning"
    else:
        status = "passed"

    return RulesetResult(
        status=status,
        results=results,
        passing_frame=passing,
        quarantined_frame=quarantined,
        warnings=warnings,
    )
