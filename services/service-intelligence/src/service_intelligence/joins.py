"""Working out which columns two datasets join on.

The step this removes: opening both datasets, scrolling for something that looks
like a key, guessing, running the join, and discovering it matched eleven rows.

The proposal is made from three things that are actually measurable:

**Value overlap.** What share of the left column's distinct values appear in the
right's. This is the only signal that really matters -- two columns that share no
values do not join, whatever they are called.

**Cardinality.** Whether either side is unique, which decides whether the join is
one-to-one, one-to-many, or the many-to-many that silently multiplies rows.

**Name similarity.** `customer_id` to `id` on a `customers` dataset is a good
guess, but only as a tie-breaker: name agreement with no value overlap is a
coincidence, and treating it as evidence is how a join produces nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

# Below this share, a join would drop most of the left side -- worth proposing
# with a warning, not worth proposing quietly.
USABLE_OVERLAP = 0.5
STRONG_OVERLAP = 0.9

# Sampling keeps this cheap on wide datasets; the overlap estimate is stable
# well before this many distinct values.
MAX_DISTINCT_SAMPLED = 20_000

JOIN_KINDS = ("one_to_one", "one_to_many", "many_to_one", "many_to_many")


@dataclass
class ColumnProfile:
    """What has to be known about a column to judge it as a join key."""

    name: str
    values: list[Any]

    @property
    def distinct(self) -> set[str]:
        return {
            _normalise(value)
            for value in self.values[:MAX_DISTINCT_SAMPLED]
            if value is not None and str(value).strip()
        }

    @property
    def non_null_count(self) -> int:
        return sum(1 for value in self.values if value is not None and str(value).strip())

    @property
    def is_unique(self) -> bool:
        return self.non_null_count > 0 and len(self.distinct) == self.non_null_count


def _normalise(value: Any) -> str:
    """Compare keys the way a database would, minus the type mismatch.

    A key stored as 1 on one side and "1" on the other is the single most common
    reason a join that should work returns nothing, so both become "1" here.
    """
    text = str(value).strip()
    # A whole number written as a float -- 1.0 from a CSV read -- is the same key.
    if re.fullmatch(r"-?\d+\.0+", text):
        text = text.split(".")[0]
    return text.casefold()


def name_similarity(left: str, right: str) -> float:
    """How much two column names agree, ignoring conventions.

    `customer_id` and `customerId` and `CUSTOMER_ID` are the same name; so, for
    this purpose, are `customer_id` and `id` on a customers table.
    """
    left_tokens = _tokens(left)
    right_tokens = _tokens(right)
    if not left_tokens or not right_tokens:
        return 0.0
    shared = left_tokens & right_tokens
    return len(shared) / max(len(left_tokens), len(right_tokens))


def _tokens(name: str) -> set[str]:
    spaced = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    return {token for token in re.split(r"[^a-zA-Z0-9]+", spaced.lower()) if token}


@dataclass
class JoinCandidate:
    left_column: str
    right_column: str
    overlap: float
    reverse_overlap: float
    left_unique: bool
    right_unique: bool
    name_score: float
    score: float
    kind: str
    confidence: str
    explanation: str
    warnings: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_column": self.left_column,
            "right_column": self.right_column,
            "overlap": round(self.overlap, 3),
            "reverse_overlap": round(self.reverse_overlap, 3),
            "left_unique": self.left_unique,
            "right_unique": self.right_unique,
            "name_score": round(self.name_score, 3),
            "score": round(self.score, 3),
            "kind": self.kind,
            "confidence": self.confidence,
            "explanation": self.explanation,
            "warnings": self.warnings,
        }


def _kind(left_unique: bool, right_unique: bool) -> str:
    if left_unique and right_unique:
        return "one_to_one"
    if right_unique:
        return "many_to_one"
    if left_unique:
        return "one_to_many"
    return "many_to_many"


def evaluate_pair(left: ColumnProfile, right: ColumnProfile) -> JoinCandidate | None:
    """Judge one pair of columns as a possible join key."""
    left_values, right_values = left.distinct, right.distinct
    if not left_values or not right_values:
        return None

    shared = left_values & right_values
    if not shared:
        return None

    overlap = len(shared) / len(left_values)
    reverse = len(shared) / len(right_values)
    name_score = name_similarity(left.name, right.name)
    kind = _kind(left.is_unique, right.is_unique)

    # Overlap dominates; the name only separates otherwise-equal candidates.
    score = overlap * 0.6 + reverse * 0.25 + name_score * 0.15

    warnings: list[str] = []
    if kind == "many_to_many":
        warnings.append(
            "Neither side is unique, so matching rows multiply. Aggregate or "
            "deduplicate one side first."
        )
    if overlap < USABLE_OVERLAP:
        warnings.append(
            f"Only {overlap:.0%} of the left column's values appear on the right, "
            "so an inner join would drop most rows."
        )

    if overlap >= STRONG_OVERLAP and kind != "many_to_many":
        confidence = "high"
    elif overlap >= USABLE_OVERLAP:
        confidence = "medium"
    else:
        confidence = "low"

    explanation = (
        f"{overlap:.0%} of '{left.name}' values are found in '{right.name}'"
        + (", and the names agree" if name_score >= 0.5 else "")
        + f". This is a {kind.replace('_', '-')} join."
    )

    return JoinCandidate(
        left_column=left.name,
        right_column=right.name,
        overlap=overlap,
        reverse_overlap=reverse,
        left_unique=left.is_unique,
        right_unique=right.is_unique,
        name_score=name_score,
        score=score,
        kind=kind,
        confidence=confidence,
        explanation=explanation,
        warnings=warnings,
    )


def suggest_join_keys(
    left_columns: Sequence[ColumnProfile],
    right_columns: Sequence[ColumnProfile],
    *,
    limit: int = 5,
    minimum_overlap: float = 0.1,
) -> list[JoinCandidate]:
    """Every plausible way to join two datasets, best first.

    Candidates below `minimum_overlap` are dropped rather than ranked last: a
    list where the tenth entry shares 2% of its values is a list nobody trusts.
    """
    candidates = [
        candidate
        for candidate in (
            evaluate_pair(left, right) for left in left_columns for right in right_columns
        )
        if candidate is not None and candidate.overlap >= minimum_overlap
    ]
    candidates.sort(key=lambda candidate: (-candidate.score, candidate.left_column))
    return candidates[:limit]


def build_join_step(
    candidate: JoinCandidate, *, right_dataset_id: str, how: str = "inner"
) -> dict[str, Any]:
    """The transformation step this proposal becomes when somebody accepts it."""
    return {
        "step_type": "join_datasets",
        "config": {
            "right_dataset_id": right_dataset_id,
            "left_on": [candidate.left_column],
            "right_on": [candidate.right_column],
            "how": how,
        },
    }
