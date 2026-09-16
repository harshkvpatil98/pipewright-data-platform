"""What every stage of the sniffing pipeline hands back.

The rule for this whole package: **never a silent guess**. A detector returns
what it decided, how sure it is, and the evidence it decided from -- so a
person disagreeing with it can see why it thought that, and a person agreeing
with it can see whether the agreement is worth anything.

That shape is not decoration. File ingestion goes wrong quietly: the delimiter
that was a semicolon, the header that was on line five, the date that was
April the third in London and March the fourth in New York. Each produces a
table that loads without error and means something other than what the file
said. A confidence next to the answer is the difference between "it just
worked" and finding out in a quarterly report.

`Finding.certain` is the only state that needs no review. `ambiguous` is the
one that matters most: it means the file genuinely does not say, and the
pipeline must ask rather than pick.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

#: Below this, a decision is offered rather than applied.
REVIEW_THRESHOLD = 0.75


class Certainty(str, Enum):
    """How much the file itself settled the question."""

    #: The file states it outright -- a BOM, an embedded schema, a declared type.
    CERTAIN = "certain"
    #: Strong statistical evidence, consistent across the sample.
    LIKELY = "likely"
    #: The best of several readings, none of them compelling.
    UNCERTAIN = "uncertain"
    #: Two or more readings fit equally well. The file does not say, so asking
    #: is the only honest move -- this is never resolved by picking a default.
    AMBIGUOUS = "ambiguous"

    @property
    def needs_review(self) -> bool:
        return self in (Certainty.UNCERTAIN, Certainty.AMBIGUOUS)


@dataclass(frozen=True)
class Candidate:
    """One reading of the file that was considered, and how well it did."""

    value: Any
    score: float
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "score": round(self.score, 4), "reason": self.reason}


@dataclass
class Finding:
    """One decision, with its confidence and the evidence behind it."""

    #: What the stage is deciding: "encoding", "delimiter", "header_row"...
    stage: str
    value: Any
    certainty: Certainty
    #: 0..1. Kept beside `certainty` because a number sorts and a word reads.
    confidence: float
    #: One sentence a person can act on.
    reason: str
    #: The other readings considered, best first. An empty list means there was
    #: only ever one reading -- which is itself worth being able to see.
    candidates: list[Candidate] = field(default_factory=list)
    #: The actual bytes, lines or values that decided it. Truncated for display,
    #: never omitted: "low confidence" with nothing to look at is not evidence.
    evidence: list[str] = field(default_factory=list)
    #: True when the pipeline must ask rather than proceed on this alone.
    blocking: bool = False

    def __post_init__(self) -> None:
        self.confidence = max(0.0, min(1.0, float(self.confidence)))
        if self.certainty is Certainty.AMBIGUOUS and not self.candidates:
            raise ValueError(
                f"{self.stage} is ambiguous but names no alternatives. Ambiguity "
                "means several readings fit; say which."
            )

    @property
    def needs_review(self) -> bool:
        return self.certainty.needs_review or self.confidence < REVIEW_THRESHOLD

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "value": self.value,
            "certainty": self.certainty.value,
            "confidence": round(self.confidence, 4),
            "reason": self.reason,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
            "evidence": list(self.evidence),
            "needs_review": self.needs_review,
            "blocking": self.blocking,
        }


def certain(stage: str, value: Any, reason: str, *, evidence: list[str] | None = None) -> Finding:
    """The file said so. Used for BOMs, embedded schemas, declared types."""
    return Finding(
        stage=stage,
        value=value,
        certainty=Certainty.CERTAIN,
        confidence=1.0,
        reason=reason,
        evidence=evidence or [],
    )


def from_candidates(
    stage: str,
    candidates: list[Candidate],
    *,
    reason: str,
    evidence: list[str] | None = None,
    fallback: Any = None,
    #: How close the runner-up has to be before this is called ambiguous.
    tie_ratio: float = 0.92,
    blocking_when_ambiguous: bool = False,
) -> Finding:
    """Grade a ranked list of readings into a decision.

    The tie test is a *ratio*, not a difference: two delimiters scoring 0.9 and
    0.88 are a genuine tie, while 0.2 and 0.18 are both bad and their gap says
    nothing. A difference test calls the first pair decided and the second
    ambiguous, which is backwards.
    """
    ranked = sorted(candidates, key=lambda candidate: candidate.score, reverse=True)
    if not ranked:
        return Finding(
            stage=stage,
            value=fallback,
            certainty=Certainty.UNCERTAIN,
            confidence=0.0,
            reason=reason,
            evidence=evidence or [],
        )

    best = ranked[0]
    runner_up = ranked[1] if len(ranked) > 1 else None
    tied = (
        runner_up is not None
        and best.score > 0
        and runner_up.score / best.score >= tie_ratio
    )

    if tied:
        certainty = Certainty.AMBIGUOUS
    elif best.score >= 0.85:
        certainty = Certainty.LIKELY
    else:
        certainty = Certainty.UNCERTAIN

    return Finding(
        stage=stage,
        value=best.value,
        certainty=certainty,
        confidence=best.score,
        reason=reason,
        candidates=ranked[:5],
        evidence=evidence or [],
        blocking=blocking_when_ambiguous and certainty is Certainty.AMBIGUOUS,
    )


def preview_bytes(payload: bytes, *, limit: int = 60) -> str:
    """Bytes a person can look at, with the unprintable ones named.

    `b'caf\\xe9'` is what actually made an encoding ambiguous, and showing it as
    `caf?` hides exactly the byte in question.
    """
    shown = payload[:limit]
    rendered = "".join(
        chr(byte) if 32 <= byte < 127 else f"\\x{byte:02x}" for byte in shown
    )
    return rendered + ("…" if len(payload) > limit else "")
