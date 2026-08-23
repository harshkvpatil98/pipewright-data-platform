"""Finding the same customer written down four different ways.

"Acme Ltd", "ACME Limited", "Acme  Ltd." and "Acme Ltd" are one company and four
rows, and every report that groups by name is wrong until somebody notices. An
exact-match deduplicate cannot see it; that is what this is for.

Two decisions worth stating:

**Nothing is merged automatically.** The output is candidate pairs with a score
and the reason for it. Merging two customers who genuinely are different is not
recoverable from a report, so a person confirms.

**Blocking, then comparison.** Comparing every row against every other row is
quadratic, and on fifty thousand rows that is two and a half billion
comparisons. Candidates are first grouped by a cheap key -- the first letters of
the normalised value -- and only compared within a group. That trades a small
number of missed matches for the feature being usable at all, which is the right
trade and worth being explicit about.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any, Iterable

# Business-entity noise that carries no identity.
_SUFFIXES = (
    "ltd", "limited", "llc", "inc", "incorporated", "plc", "gmbh", "sa", "sas",
    "bv", "nv", "pty", "co", "corp", "corporation", "company", "holdings", "group",
)

# Below this, two strings are different things that happen to share letters.
DEFAULT_THRESHOLD = 0.86
# Above this, they are the same thing with near-certainty.
CONFIDENT_THRESHOLD = 0.95

# How many leading characters form a blocking key. Two is enough to cut the
# comparison count by orders of magnitude while keeping typo'd first letters
# rare enough to accept.
BLOCK_PREFIX = 2

# A ceiling on comparisons within one block, so a block of ten thousand
# identical prefixes cannot hang a request.
MAX_BLOCK_SIZE = 400


def normalise(value: Any) -> str:
    """Strip everything that is formatting rather than identity."""
    text = str(value or "").casefold()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    tokens = [token for token in text.split() if token and token not in _SUFFIXES]
    return " ".join(tokens)


def similarity(left: str, right: str) -> float:
    """How alike two normalised strings are, between 0 and 1.

    Token-sorted before comparison so "Smith John" and "John Smith" match: word
    order is the most common way the same name is written differently.
    """
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0

    left_sorted = " ".join(sorted(left.split()))
    right_sorted = " ".join(sorted(right.split()))
    direct = SequenceMatcher(None, left, right).ratio()
    sorted_ratio = SequenceMatcher(None, left_sorted, right_sorted).ratio()
    return max(direct, sorted_ratio)


@dataclass
class MatchCandidate:
    left_value: str
    right_value: str
    left_rows: list[int]
    right_rows: list[int]
    score: float
    confidence: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "left_value": self.left_value,
            "right_value": self.right_value,
            "left_rows": self.left_rows[:20],
            "right_rows": self.right_rows[:20],
            "row_count": len(self.left_rows) + len(self.right_rows),
            "score": round(self.score, 3),
            "confidence": self.confidence,
            "reason": self.reason,
        }


@dataclass
class MatchReport:
    column: str
    distinct_values: int
    candidates: list[MatchCandidate] = field(default_factory=list)
    comparisons: int = 0
    truncated: bool = False
    summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "column": self.column,
            "distinct_values": self.distinct_values,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "comparisons": self.comparisons,
            "truncated": self.truncated,
            "summary": self.summary,
        }


def blocking_key(value: str) -> str:
    """A cheap key that puts likely matches in the same bucket.

    Built from the *token-sorted* value, not the raw one: "Smith John" and
    "John Smith" are the same person, and a plain prefix puts them in different
    blocks where they are never compared.
    """
    tokens = sorted(value.split())
    return "".join(tokens)[:BLOCK_PREFIX] if tokens else ""


def _blocks(keys: Iterable[str]) -> dict[str, list[str]]:
    """Group values by a cheap key so comparison stays sub-quadratic."""
    blocks: dict[str, list[str]] = {}
    for value in keys:
        blocks.setdefault(blocking_key(value), []).append(value)
    return blocks


def find_duplicates(
    values: Iterable[Any],
    *,
    column: str = "value",
    threshold: float = DEFAULT_THRESHOLD,
    limit: int = 50,
) -> MatchReport:
    """Values in one column that look like the same thing written differently."""
    groups: dict[str, list[int]] = {}
    originals: dict[str, str] = {}
    # Every distinct spelling that produced each key, so the ones that differ
    # only by punctuation or case can be reported rather than silently merged.
    spellings_by_key: dict[str, set[str]] = {}

    for index, raw in enumerate(values):
        key = normalise(raw)
        if not key:
            continue
        groups.setdefault(key, []).append(index)
        originals.setdefault(key, str(raw))
        spellings_by_key.setdefault(key, set()).add(str(raw))

    report = MatchReport(column=column, distinct_values=len(groups))
    candidates: list[MatchCandidate] = []
    comparisons = 0

    # Values that normalise to the same key are already known to be the same
    # thing -- they are the clearest duplicates there are. Comparison would
    # never find them, because grouping has already merged them into one entry.
    for key, spellings in spellings_by_key.items():
        if len(spellings) < 2:
            continue
        canonical = max(spellings, key=len)
        for variant in spellings:
            if variant == canonical:
                continue
            candidates.append(
                MatchCandidate(
                    left_value=canonical,
                    right_value=variant,
                    left_rows=groups[key],
                    right_rows=[],
                    score=1.0,
                    confidence="high",
                    reason="Identical once punctuation, case, and company suffixes are removed.",
                )
            )

    for members in _blocks(groups.keys()).values():
        if len(members) > MAX_BLOCK_SIZE:
            members = members[:MAX_BLOCK_SIZE]
            report.truncated = True

        for position, left in enumerate(members):
            for right in members[position + 1 :]:
                comparisons += 1
                score = similarity(left, right)
                if score < threshold:
                    continue
                candidates.append(
                    MatchCandidate(
                        left_value=originals[left],
                        right_value=originals[right],
                        left_rows=groups[left],
                        right_rows=groups[right],
                        score=score,
                        confidence="high" if score >= CONFIDENT_THRESHOLD else "medium",
                        reason=_reason(originals[left], originals[right], left, right, score),
                    )
                )

    candidates.sort(key=lambda candidate: -candidate.score)
    report.candidates = candidates[:limit]
    report.comparisons = comparisons
    report.summary = _summarise(report, threshold)
    return report


def _reason(
    left_original: str, right_original: str, left: str, right: str, score: float
) -> str:
    if left == right:
        return "Identical once punctuation, case, and company suffixes are removed."
    if sorted(left.split()) == sorted(right.split()):
        return "The same words in a different order."
    return f"{score:.0%} alike after normalising."


def _summarise(report: MatchReport, threshold: float) -> str:
    if not report.candidates:
        return (
            f"No two values in '{report.column}' are more than {threshold:.0%} alike. "
            "Nothing looks like a duplicate."
        )
    affected = sum(candidate.to_dict()["row_count"] for candidate in report.candidates)
    return (
        f"{len(report.candidates)} pair(s) in '{report.column}' look like the same thing "
        f"written differently, covering {affected} row(s). Nothing has been merged."
    )


def merge_plan(candidates: list[MatchCandidate]) -> dict[str, str]:
    """A mapping from each variant to the value it should become.

    The longest spelling wins: it is usually the complete one, and shortening
    "Acme Limited" to "Acme" loses information that a person may need.
    """
    plan: dict[str, str] = {}
    for candidate in candidates:
        canonical = max(candidate.left_value, candidate.right_value, key=len)
        for variant in (candidate.left_value, candidate.right_value):
            if variant != canonical:
                plan[variant] = canonical
    return plan


def build_merge_step(column: str, plan: dict[str, str]) -> dict[str, Any]:
    """The transformation step a confirmed merge becomes."""
    return {
        "step_type": "replace_values",
        "config": {"column": column, "replacements": plan},
    }
