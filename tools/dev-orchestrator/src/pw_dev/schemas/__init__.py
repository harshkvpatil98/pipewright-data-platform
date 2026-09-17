"""Versioned artifact schemas and the validator that enforces them.

The same JSON Schema documents are handed to `codex exec --output-schema` and
`claude -p --json-schema`, so they are authored in the strict subset both
providers accept: every property required, `additionalProperties: false`, and
optionality expressed as a null union rather than an absent key.
"""

from __future__ import annotations

import functools
import json
from pathlib import Path

SCHEMA_DIR = Path(__file__).resolve().parent

SCHEMA_IDS = {
    "phase_spec/v1": "phase_spec.v1.json",
    "task_assignment/v1": "task_assignment.v1.json",
    "worker_report/v1": "worker_report.v1.json",
    "verification_evidence/v1": "verification_evidence.v1.json",
    "review_findings/v1": "review_findings.v1.json",
    "publication_receipt/v1": "publication_receipt.v1.json",
}


@functools.lru_cache(maxsize=None)
def load_schema(schema_id: str) -> dict:
    """Return the parsed schema for a `name/version` identifier."""
    try:
        filename = SCHEMA_IDS[schema_id]
    except KeyError:
        raise KeyError(
            f"unknown schema id {schema_id!r}; known: {sorted(SCHEMA_IDS)}"
        ) from None
    return json.loads((SCHEMA_DIR / filename).read_text(encoding="utf-8"))


def schema_path(schema_id: str) -> Path:
    """Path to the on-disk schema, for passing to a provider CLI."""
    return SCHEMA_DIR / SCHEMA_IDS[schema_id]


__all__ = ["SCHEMA_DIR", "SCHEMA_IDS", "load_schema", "schema_path"]
