"""Working out what a file actually is, and saying how sure we are.

Read `evidence.py` first: every stage returns a `Finding` carrying the answer,
a confidence and the evidence behind it, and a stage that genuinely cannot
decide returns `AMBIGUOUS` and blocks rather than picking a default.
"""

from service_ingestion.sniff.evidence import (
    Candidate,
    Certainty,
    Finding,
    certain,
    from_candidates,
)
from service_ingestion.sniff.pipeline import AnalysisResult, analyse

__all__ = [
    "AnalysisResult",
    "Candidate",
    "Certainty",
    "Finding",
    "analyse",
    "certain",
    "from_candidates",
]
