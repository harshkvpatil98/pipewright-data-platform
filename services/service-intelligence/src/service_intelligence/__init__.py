"""Suggestions, detection, and explanation.

Everything here is deterministic: patterns, checksums, set overlap, string
similarity, and time correlation. There are no model calls, and each response
says which method produced it -- a suggestion that sounds authoritative and is
wrong is worse than one that shows its working.
"""

from service_intelligence.documenting import describe_column, describe_dataset
from service_intelligence.explanation import explain
from service_intelligence.joins import suggest_join_keys
from service_intelligence.matching import find_duplicates
from service_intelligence.phrasing import parse
from service_intelligence.pii import scan_dataset
from service_intelligence.router import build_router
from service_intelligence.rules import suggest_rules
from service_intelligence.status import get_service_status

__all__ = [
    "build_router",
    "describe_column",
    "describe_dataset",
    "explain",
    "find_duplicates",
    "get_service_status",
    "parse",
    "scan_dataset",
    "suggest_join_keys",
    "suggest_rules",
]
