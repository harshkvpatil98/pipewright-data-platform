"""What a run recorded about how it ran -- enough to run it again the same way.

Phase 18 §3: freezing inputs and steps is not enough for a deterministic
replay, because the engine evaluates clock-dependent functions at execution
time. The execution context is the rest: the frozen evaluation instant and its
timezone, the semantic version of the engine that produced the result, the
exact steps that ran (not the pipeline's current steps, which may have been
edited since), and durable pins to the input versions read and the output
version published.

It lives in `pipeline_runs.summary_json["execution_context"]` -- typed here,
stored as JSON, and read back by `context_from_run` for replay and the audit
surface. Bump `SEMANTIC_VERSION` whenever a function's meaning changes in a way
that makes an old result irreproducible; a replay across versions then returns
an explicit incompatibility rather than a claim of equivalence.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

from shared_python.storage import content_digest

#: The semantics of the transformation engine as a whole: step behaviour, the
#: function catalogue, three-valued logic, null handling. Changing any of those
#: in a way that changes results means bumping this, so a replay across the
#: change says "incompatible" rather than "divergent".
SEMANTIC_VERSION = "pipewright-transformations/2026.09"

CONTEXT_SCHEMA = 1

#: The catalogue functions that read the evaluation instant. Recorded so an
#: auditor can see which nondeterministic inputs a run had -- and so a future
#: function that reads the clock has a list to be added to.
CLOCK_FUNCTIONS = ("now", "today", "age_years")


@dataclass
class VersionPin:
    """A durable reference to one version of one dataset."""

    dataset_id: str
    #: Null when the dataset had no recorded version at the time (materialised
    #: before versioning). Such a pin cannot be replayed and says so.
    version_number: int | None
    content_hash: str | None
    #: `base` for the pipeline's base dataset, `step` for a dataset a join or
    #: union step read, `output` for what the run published.
    role: str = "base"
    step_index: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None or key in {"version_number", "content_hash"}}

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "VersionPin":
        return cls(
            dataset_id=str(raw.get("dataset_id")),
            version_number=raw.get("version_number"),
            content_hash=raw.get("content_hash"),
            role=str(raw.get("role") or "base"),
            step_index=raw.get("step_index"),
        )


@dataclass
class ExecutionContext:
    evaluated_at: datetime
    steps: list[dict[str, Any]]
    inputs: list[VersionPin] = field(default_factory=list)
    outputs: list[VersionPin] = field(default_factory=list)
    timezone: str = "UTC"
    semantic_version: str = SEMANTIC_VERSION
    #: The run this one re-executed, when it is a replay.
    replay_of: str | None = None

    @property
    def steps_digest(self) -> str:
        return steps_digest(self.steps)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": CONTEXT_SCHEMA,
            "semantic_version": self.semantic_version,
            "evaluated_at": self.evaluated_at.astimezone(UTC).isoformat(),
            "timezone": self.timezone,
            "clock_functions": list(CLOCK_FUNCTIONS),
            "steps": self.steps,
            "steps_digest": self.steps_digest,
            "inputs": [pin.to_dict() for pin in self.inputs],
            "outputs": [pin.to_dict() for pin in self.outputs],
            "replay_of": self.replay_of,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "ExecutionContext":
        evaluated = raw.get("evaluated_at")
        if not isinstance(evaluated, str):
            raise ValueError("execution context has no evaluated_at")
        instant = datetime.fromisoformat(evaluated)
        if instant.tzinfo is None:
            instant = instant.replace(tzinfo=UTC)
        return cls(
            evaluated_at=instant,
            steps=list(raw.get("steps") or []),
            inputs=[VersionPin.from_dict(pin) for pin in raw.get("inputs") or []],
            outputs=[VersionPin.from_dict(pin) for pin in raw.get("outputs") or []],
            timezone=str(raw.get("timezone") or "UTC"),
            semantic_version=str(raw.get("semantic_version") or ""),
            replay_of=raw.get("replay_of"),
        )


def steps_digest(steps: list[dict[str, Any]]) -> str:
    """A stable fingerprint of a recipe, independent of key order."""
    canonical = json.dumps(steps, sort_keys=True, separators=(",", ":"), default=str)
    return content_digest(canonical.encode("utf-8"))


def context_from_run(summary_json: dict[str, Any] | None) -> ExecutionContext | None:
    """The recorded context, or None for a run recorded before contexts existed."""
    if not isinstance(summary_json, dict):
        return None
    raw = summary_json.get("execution_context")
    if not isinstance(raw, dict):
        return None
    try:
        return ExecutionContext.from_dict(raw)
    except (ValueError, TypeError):
        return None


def head_pin(db, dataset_id: uuid.UUID, *, role: str = "base", step_index: int | None = None) -> VersionPin:
    """Pin the current head version of a dataset -- what a run reading its
    `file_path` right now is actually reading."""
    from sqlalchemy import select

    from service_datasets.models import DatasetVersion

    head = db.scalar(
        select(DatasetVersion)
        .where(DatasetVersion.dataset_id == dataset_id)
        .order_by(DatasetVersion.version_number.desc())
        .limit(1)
    )
    return VersionPin(
        dataset_id=str(dataset_id),
        version_number=head.version_number if head is not None else None,
        content_hash=head.content_hash if head is not None else None,
        role=role,
        step_index=step_index,
    )
