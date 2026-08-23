"""Row and column rules, applied per role.

Project membership answers "may you open this dataset". It cannot answer "may
you see the salary column" or "may you see rows outside your own region", and
those are the questions that decide whether a platform can hold HR or customer
data at all.

Three properties this is built around:

**Deny wins.** When several policies apply to one person, the most restrictive
answer is the one taken. Any other rule means adding a policy can *widen*
access, which is the opposite of what a policy is for.

**Masking is not filtering.** A masked column keeps its rows -- counts and joins
still work -- while a filtered row is gone entirely. Conflating them either
leaks the value or silently changes every aggregate.

**No policy means no restriction.** A platform where every dataset needs a
policy before anyone can read it is a platform nobody finishes configuring. The
default is open, and restriction is deliberate.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Sequence

import pandas as pd

# How a column is hidden, when it is.
COLUMN_ACTIONS = ("allow", "mask", "hash", "redact", "deny")

# Ordered least to most restrictive; a conflict resolves to the highest.
_ACTION_RANK = {action: rank for rank, action in enumerate(COLUMN_ACTIONS)}

ROW_OPERATORS = (
    "equals",
    "not_equals",
    "in",
    "not_in",
    "greater_than",
    "less_than",
    "contains",
    "is_null",
    "not_null",
)


@dataclass(frozen=True)
class RowRule:
    """Which rows a role may see."""

    column: str
    operator: str
    value: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "operator": self.operator, "value": self.value}


@dataclass(frozen=True)
class ColumnRule:
    """What happens to a column for a role."""

    column: str
    action: str = "mask"

    def to_dict(self) -> dict[str, Any]:
        return {"column": self.column, "action": self.action}


@dataclass
class Policy:
    """One rule set, applying to one role on one dataset."""

    name: str
    role: str
    row_rules: list[RowRule] = field(default_factory=list)
    column_rules: list[ColumnRule] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "row_rules": [rule.to_dict() for rule in self.row_rules],
            "column_rules": [rule.to_dict() for rule in self.column_rules],
            "enabled": self.enabled,
        }


@dataclass
class AppliedPolicy:
    """What actually happened to a frame, so it can be explained."""

    rows_before: int
    rows_after: int
    columns_masked: list[str]
    columns_removed: list[str]
    policies_applied: list[str]

    @property
    def rows_hidden(self) -> int:
        return self.rows_before - self.rows_after

    @property
    def restricted(self) -> bool:
        return bool(self.rows_hidden or self.columns_masked or self.columns_removed)

    def to_dict(self) -> dict[str, Any]:
        return {
            "rows_before": self.rows_before,
            "rows_after": self.rows_after,
            "rows_hidden": self.rows_hidden,
            "columns_masked": self.columns_masked,
            "columns_removed": self.columns_removed,
            "policies_applied": self.policies_applied,
            "restricted": self.restricted,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        if not self.restricted:
            return "You are seeing everything in this dataset."
        parts: list[str] = []
        if self.rows_hidden:
            parts.append(f"{self.rows_hidden:,} row(s) hidden")
        if self.columns_masked:
            parts.append(f"{len(self.columns_masked)} column(s) masked")
        if self.columns_removed:
            parts.append(f"{len(self.columns_removed)} column(s) removed")
        joined = ", ".join(parts[:-1]) + (" and " + parts[-1] if len(parts) > 1 else parts[0])
        return f"{joined[0].upper()}{joined[1:]} by {', '.join(self.policies_applied)}."


def effective_column_action(policies: Sequence[Policy], column: str) -> str:
    """The strictest thing any applicable policy says about a column.

    Deny wins. If one policy masks a column and another denies it, the answer is
    deny -- otherwise adding a policy could widen access.
    """
    action = "allow"
    for policy in policies:
        if not policy.enabled:
            continue
        for rule in policy.column_rules:
            if rule.column == column and _ACTION_RANK.get(rule.action, 0) > _ACTION_RANK[action]:
                action = rule.action
    return action


def _row_mask(frame: pd.DataFrame, rule: RowRule) -> pd.Series:
    """Which rows this rule permits.

    A rule naming a column the dataset does not have permits nothing. Skipping
    it instead would turn a typo in a policy into an open door.
    """
    if rule.column not in frame.columns:
        return pd.Series(False, index=frame.index)

    series = frame[rule.column]
    if rule.operator == "is_null":
        return series.isna()
    if rule.operator == "not_null":
        return series.notna()
    if rule.operator == "equals":
        return series == rule.value
    if rule.operator == "not_equals":
        return series != rule.value
    if rule.operator == "in":
        values = rule.value if isinstance(rule.value, list) else [rule.value]
        return series.isin(values)
    if rule.operator == "not_in":
        values = rule.value if isinstance(rule.value, list) else [rule.value]
        return ~series.isin(values)
    if rule.operator == "contains":
        return series.astype("string").str.contains(str(rule.value), case=False, na=False)

    numeric = pd.to_numeric(series, errors="coerce")
    threshold = pd.to_numeric(pd.Series([rule.value]), errors="coerce").iloc[0]
    if pd.isna(threshold):
        return pd.Series(False, index=frame.index)
    comparison = numeric > threshold if rule.operator == "greater_than" else numeric < threshold
    return comparison.fillna(False)


def _mask_value(value: Any, action: str) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return value
    if action == "redact":
        return "[redacted]"
    if action == "hash":
        # Stable across rows, so masked values still group and join. Not a
        # security boundary on its own -- a small value space is guessable --
        # and that is why `redact` exists alongside it.
        return hashlib.sha256(str(value).encode()).hexdigest()[:16]

    text = str(value)
    if "@" in text:
        local, _, domain = text.partition("@")
        return f"{local[:1]}***@{domain}"
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:2]}{'*' * (len(text) - 4)}{text[-2:]}"


def apply_policies(
    frame: pd.DataFrame, policies: Sequence[Policy], *, role: str
) -> tuple[pd.DataFrame, AppliedPolicy]:
    """Narrow a frame to what this role may see."""
    applicable = [
        policy for policy in policies if policy.enabled and policy.role == role
    ]
    result = AppliedPolicy(
        rows_before=len(frame),
        rows_after=len(frame),
        columns_masked=[],
        columns_removed=[],
        policies_applied=[policy.name for policy in applicable],
    )
    if not applicable:
        return frame, result

    working = frame
    for policy in applicable:
        for rule in policy.row_rules:
            working = working[_row_mask(working, rule)]

    for column in list(working.columns):
        action = effective_column_action(applicable, str(column))
        if action == "allow":
            continue
        if action == "deny":
            working = working.drop(columns=[column])
            result.columns_removed.append(str(column))
        else:
            # `action` is bound as a default rather than captured. It is
            # correct either way today because `.map` runs immediately, but this
            # decides which columns get masked -- a late binding here would
            # apply the last column's rule to every column, and that is a leak.
            working = working.assign(
                **{
                    column: working[column].map(
                        lambda value, _action=action: _mask_value(value, _action)
                    )
                }
            )
            result.columns_masked.append(str(column))

    result.rows_after = len(working)
    return working.reset_index(drop=True), result


def validate_policy(policy: Policy, columns: Sequence[str]) -> list[str]:
    """Problems worth telling somebody about before the policy is saved."""
    problems: list[str] = []
    known = set(columns)

    for rule in policy.row_rules:
        if rule.operator not in ROW_OPERATORS:
            problems.append(f"'{rule.operator}' is not a row condition.")
        if columns and rule.column not in known:
            problems.append(
                f"Row rule names '{rule.column}', which this dataset does not have. "
                "It would hide every row."
            )
    for rule in policy.column_rules:
        if rule.action not in COLUMN_ACTIONS:
            problems.append(f"'{rule.action}' is not something that can be done to a column.")
        if columns and rule.column not in known:
            problems.append(f"Column rule names '{rule.column}', which does not exist.")
    return problems
