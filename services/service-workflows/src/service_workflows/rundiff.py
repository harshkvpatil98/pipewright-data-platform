"""Comparing two runs of the same workflow.

"It worked yesterday" is the start of every debugging session, and answering it
by opening two run pages in two tabs is how the afternoon disappears. This puts
the two side by side and says what actually differs: which node changed status,
which got slower, and which produced a different number of rows.

Pure functions over plain dictionaries, so the comparison is testable without
staging two real runs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Numeric outputs worth comparing, in the order a person would read them.
COMPARED_OUTPUTS: tuple[str, ...] = (
    "row_count",
    "total_rows",
    "rows_extracted",
    "rows_in",
    "rows_passing",
    "rows_quarantined",
    "rules_evaluated",
    "rules_failed",
    "column_count",
)

OUTPUT_LABELS: dict[str, str] = {
    "row_count": "rows",
    "total_rows": "total rows",
    "rows_extracted": "rows extracted",
    "rows_in": "rows checked",
    "rows_passing": "rows passing",
    "rows_quarantined": "rows quarantined",
    "rules_evaluated": "rules evaluated",
    "rules_failed": "rules failed",
    "column_count": "columns",
}

# A node has to be meaningfully slower before it is worth mentioning; a 30%
# swing on a 40ms step is noise.
SLOWER_RATIO = 1.25
FASTER_RATIO = 0.75
MIN_DURATION_DELTA_MS = 250


@dataclass
class NodeDiff:
    node_key: str
    node_name: str
    node_type: str
    left_status: str | None
    right_status: str | None
    left_duration_ms: int | None
    right_duration_ms: int | None
    duration_change_percentage: float | None
    verdict: str
    changes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "node_key": self.node_key,
            "node_name": self.node_name,
            "node_type": self.node_type,
            "left_status": self.left_status,
            "right_status": self.right_status,
            "left_duration_ms": self.left_duration_ms,
            "right_duration_ms": self.right_duration_ms,
            "duration_change_percentage": self.duration_change_percentage,
            "verdict": self.verdict,
            "changes": self.changes,
        }


@dataclass
class RunDiff:
    nodes: list[NodeDiff]
    summary: str
    identical: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [node.to_dict() for node in self.nodes],
            "summary": self.summary,
            "identical": self.identical,
        }


def _numeric(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


def _format(value: float) -> str:
    if abs(value - round(value)) < 1e-9:
        return f"{int(round(value)):,}"
    return f"{value:,.2f}"


def _output_changes(left: dict[str, Any] | None, right: dict[str, Any] | None) -> list[str]:
    left = left if isinstance(left, dict) else {}
    right = right if isinstance(right, dict) else {}
    changes: list[str] = []

    for key in COMPARED_OUTPUTS:
        before, after = _numeric(left.get(key)), _numeric(right.get(key))
        if before is None or after is None or before == after:
            continue
        label = OUTPUT_LABELS.get(key, key.replace("_", " "))
        direction = "up" if after > before else "down"
        if before == 0:
            changes.append(f"{label} went from 0 to {_format(after)}")
        else:
            percentage = abs(after - before) / abs(before) * 100
            changes.append(
                f"{label} {direction} {percentage:.0f}% ({_format(before)} to {_format(after)})"
            )

    for key in ("quality_status", "drift_severity", "load_mode", "table_name"):
        before, after = left.get(key), right.get(key)
        if before != after and (before is not None or after is not None):
            changes.append(f"{key.replace('_', ' ')} changed from '{before}' to '{after}'")

    return changes


def _duration_change(left: int | None, right: int | None) -> float | None:
    if left in (None, 0) or right is None:
        return None
    return round((right - left) / left * 100, 1)


def _verdict(
    left: dict[str, Any] | None,
    right: dict[str, Any] | None,
    changes: list[str],
    left_ms: int | None,
    right_ms: int | None,
) -> str:
    if left is None:
        return "added"
    if right is None:
        return "removed"
    if left.get("status") != right.get("status"):
        return "status_changed"
    if changes:
        return "output_changed"

    if left_ms and right_ms and abs(right_ms - left_ms) >= MIN_DURATION_DELTA_MS:
        ratio = right_ms / left_ms
        if ratio >= SLOWER_RATIO:
            return "slower"
        if ratio <= FASTER_RATIO:
            return "faster"
    return "same"


def diff_node_runs(
    left_nodes: list[dict[str, Any]], right_nodes: list[dict[str, Any]]
) -> RunDiff:
    """Compare two runs' node results, keyed by node.

    Keyed by ``node_key`` rather than position, because a workflow edited
    between the two runs would otherwise line up unrelated nodes and report
    nonsense.
    """
    left_by_key = {str(node.get("node_key")): node for node in left_nodes}
    right_by_key = {str(node.get("node_key")): node for node in right_nodes}

    # Right-hand order first: the newer run is the one being explained.
    ordered_keys = [str(node.get("node_key")) for node in right_nodes]
    ordered_keys += [key for key in left_by_key if key not in right_by_key]

    diffs: list[NodeDiff] = []
    for key in ordered_keys:
        left = left_by_key.get(key)
        right = right_by_key.get(key)
        source = right or left or {}

        left_ms = left.get("duration_ms") if left else None
        right_ms = right.get("duration_ms") if right else None
        changes = _output_changes(
            left.get("output_json") if left else None,
            right.get("output_json") if right else None,
        )
        diffs.append(
            NodeDiff(
                node_key=key,
                node_name=str(source.get("node_name") or key),
                node_type=str(source.get("node_type") or "unknown"),
                left_status=left.get("status") if left else None,
                right_status=right.get("status") if right else None,
                left_duration_ms=left_ms,
                right_duration_ms=right_ms,
                duration_change_percentage=_duration_change(left_ms, right_ms),
                verdict=_verdict(left, right, changes, left_ms, right_ms),
                changes=changes,
            )
        )

    return RunDiff(nodes=diffs, summary=_summarise(diffs), identical=_is_identical(diffs))


def _is_identical(diffs: list[NodeDiff]) -> bool:
    return all(diff.verdict == "same" for diff in diffs)


def _summarise(diffs: list[NodeDiff]) -> str:
    if not diffs:
        return "Neither run recorded any nodes."

    status_changed = [diff for diff in diffs if diff.verdict == "status_changed"]
    output_changed = [diff for diff in diffs if diff.verdict == "output_changed"]
    structure = [diff for diff in diffs if diff.verdict in {"added", "removed"}]
    slower = [diff for diff in diffs if diff.verdict == "slower"]

    if status_changed:
        first = status_changed[0]
        return (
            f"'{first.node_name}' went from {first.left_status} to {first.right_status}"
            + (f", and {len(status_changed) - 1} other node(s) changed status." if len(status_changed) > 1 else ".")
        )
    if output_changed:
        first = output_changed[0]
        return f"Same statuses, different data: '{first.node_name}' {first.changes[0]}."
    if structure:
        return f"The workflow itself changed between these runs: {len(structure)} node(s) added or removed."
    if slower:
        first = slower[0]
        return f"Same results, but '{first.node_name}' took {first.duration_change_percentage:.0f}% longer."
    return "The two runs did the same work and produced the same numbers."
