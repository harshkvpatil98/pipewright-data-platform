"""Diffing two snapshots of the same resource.

A version list that only shows timestamps tells you a change happened, which
you already knew. What makes history useful is the sentence next to each entry:
"renamed two steps and added a quality gate". That sentence has to be generated,
because nobody writes commit messages for a UI.

Pure and structural: it walks two JSON documents and reports what moved. It has
no idea what a pipeline is, which is what lets it serve pipelines, workflows,
and rules alike.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Keys that change on every save and mean nothing to a reader.
IGNORED_KEYS = frozenset({"updated_at", "created_at", "last_run_at", "execution_count"})

# Lists whose entries have one of these are matched by identity, not position;
# otherwise inserting a step at the top reads as "every step changed".
IDENTITY_KEYS = ("node_key", "id", "name", "step_type")

MAX_REPORTED_CHANGES = 40


@dataclass
class Change:
    path: str
    kind: str  # "added" | "removed" | "changed"
    before: Any = None
    after: Any = None

    def to_dict(self) -> dict[str, Any]:
        return {"path": self.path, "kind": self.kind, "before": self.before, "after": self.after}


@dataclass
class SnapshotDiff:
    changes: list[Change] = field(default_factory=list)
    truncated: bool = False

    @property
    def identical(self) -> bool:
        return not self.changes

    def to_dict(self) -> dict[str, Any]:
        return {
            "changes": [change.to_dict() for change in self.changes],
            "truncated": self.truncated,
            "identical": self.identical,
            "summary": self.summary(),
        }

    def summary(self) -> str:
        return summarise(self.changes, truncated=self.truncated)


def _identity(entry: Any) -> str | None:
    if not isinstance(entry, dict):
        return None
    for key in IDENTITY_KEYS:
        value = entry.get(key)
        if isinstance(value, (str, int)) and str(value):
            return f"{key}={value}"
    return None


def _join(prefix: str, key: str) -> str:
    return f"{prefix}.{key}" if prefix else key


def diff_snapshots(before: Any, after: Any, *, prefix: str = "") -> SnapshotDiff:
    """What changed between two snapshots."""
    result = SnapshotDiff()
    _walk(before, after, prefix, result)
    if len(result.changes) > MAX_REPORTED_CHANGES:
        result.changes = result.changes[:MAX_REPORTED_CHANGES]
        result.truncated = True
    return result


def _walk(before: Any, after: Any, prefix: str, result: SnapshotDiff) -> None:
    if isinstance(before, dict) and isinstance(after, dict):
        for key in sorted(set(before) | set(after)):
            if key in IGNORED_KEYS:
                continue
            path = _join(prefix, key)
            if key not in before:
                result.changes.append(Change(path=path, kind="added", after=after[key]))
            elif key not in after:
                result.changes.append(Change(path=path, kind="removed", before=before[key]))
            else:
                _walk(before[key], after[key], path, result)
        return

    if isinstance(before, list) and isinstance(after, list):
        _walk_lists(before, after, prefix, result)
        return

    if before != after:
        result.changes.append(Change(path=prefix, kind="changed", before=before, after=after))


def _walk_lists(before: list, after: list, prefix: str, result: SnapshotDiff) -> None:
    before_ids = [_identity(entry) for entry in before]
    after_ids = [_identity(entry) for entry in after]

    # Fall back to positional comparison when the entries carry no identity --
    # a list of plain strings, say -- or when an identity repeats. Duplicates
    # matter: keying by them collapses two entries into one and a removal
    # disappears from the diff entirely, which is silent data loss in the one
    # feature people rely on to see what changed.
    duplicated = len(set(before_ids)) != len(before_ids) or len(set(after_ids)) != len(after_ids)
    if not all(before_ids) or not all(after_ids) or duplicated:
        for index in range(max(len(before), len(after))):
            path = f"{prefix}[{index}]"
            if index >= len(before):
                result.changes.append(Change(path=path, kind="added", after=after[index]))
            elif index >= len(after):
                result.changes.append(Change(path=path, kind="removed", before=before[index]))
            else:
                _walk(before[index], after[index], path, result)
        return

    before_by_id = dict(zip(before_ids, before, strict=True))
    after_by_id = dict(zip(after_ids, after, strict=True))

    for identity in before_ids:
        if identity not in after_by_id:
            result.changes.append(
                Change(path=f"{prefix}[{identity}]", kind="removed", before=before_by_id[identity])
            )
    for index, identity in enumerate(after_ids):
        if identity not in before_by_id:
            result.changes.append(
                Change(path=f"{prefix}[{identity}]", kind="added", after=after_by_id[identity])
            )
        else:
            _walk(
                before_by_id[identity],
                after_by_id[identity],
                f"{prefix}[{identity}]",
                result,
            )
        del index


def _leaf(path: str) -> str:
    tail = path.split(".")[-1]
    return tail.replace("_", " ") if tail else path


def summarise(changes: list[Change], *, truncated: bool = False) -> str:
    """One sentence describing a set of changes."""
    if not changes:
        return "No changes."

    added = [change for change in changes if change.kind == "added"]
    removed = [change for change in changes if change.kind == "removed"]
    edited = [change for change in changes if change.kind == "changed"]

    parts: list[str] = []
    if added:
        parts.append(f"added {_describe(added)}")
    if removed:
        parts.append(f"removed {_describe(removed)}")
    if edited:
        parts.append(f"changed {_describe(edited)}")

    sentence = ", ".join(parts[:-1])
    if len(parts) > 1:
        sentence = f"{sentence} and {parts[-1]}"
    else:
        sentence = parts[0]

    if truncated:
        sentence += ", among other things"
    return sentence[0].upper() + sentence[1:] + "."


def _describe(changes: list[Change]) -> str:
    names = [_leaf(change.path) for change in changes]
    unique = list(dict.fromkeys(names))
    if len(unique) == 1:
        return unique[0]
    if len(unique) == 2:
        return f"{unique[0]} and {unique[1]}"
    return f"{unique[0]}, {unique[1]}, and {len(unique) - 2} more"
