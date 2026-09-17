"""Builds the context packet each role receives.

Two things are deliberately absent from every packet:

* the operator's conversation. The interactive application's chat history is not
  shared with either CLI. Everything that crosses the boundary crosses it as a
  versioned artifact, which is why a new session can resume a run;
* the whole repository. Files are supplied because a task needs them, bounded by
  size and count, with the reason attached. Sending everything is how a run gets
  expensive and how a worker loses the thread.

Nothing outside the repository is ever read into a packet, and file bodies are
passed through the redactor on the way in.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..config import Limits
from ..schemas.validate import validate_artifact
from ..util.hashing import digest_bytes, digest_json, digest_text
from ..util.redact import redact
from ..workspace.guard import PathViolation, normalise


@dataclass
class ContextFile:
    path: str
    reason: str
    body: str
    truncated: bool


class ContextBuilder:
    """Reads repository files for a prompt, under explicit bounds."""

    def __init__(self, repo_root: Path, limits: Limits) -> None:
        self.repo_root = Path(repo_root).resolve()
        self.limits = limits

    def read(self, requests: list[tuple[str, str]]) -> tuple[list[ContextFile], list[str]]:
        """Return `(files, problems)` for `(path, reason)` requests.

        A path that escapes the repository is a problem, not a file. This is the
        same check the integration guard applies, done here so a malicious or
        confused path request never reaches an `open()`.
        """
        files: list[ContextFile] = []
        problems: list[str] = []
        budget = self.limits.max_context_file_bytes * self.limits.max_context_files
        spent = 0

        for raw_path, reason in requests[: self.limits.max_context_files]:
            try:
                relative = normalise(raw_path)
            except PathViolation as violation:
                problems.append(str(violation))
                continue
            absolute = (self.repo_root / relative).resolve()
            try:
                absolute.relative_to(self.repo_root)
            except ValueError:
                problems.append(f"{raw_path}: resolves outside the repository")
                continue
            if not absolute.is_file():
                problems.append(f"{relative}: not a file in this checkout")
                continue
            if spent >= budget:
                problems.append(f"{relative}: context budget exhausted before reading it")
                continue
            try:
                raw = absolute.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                problems.append(f"{relative}: unreadable ({exc})")
                continue
            limit = self.limits.max_context_file_bytes
            truncated = len(raw) > limit
            body = raw[:limit]
            if truncated:
                body += f"\n… [truncated at {limit} characters]"
            spent += len(body)
            files.append(ContextFile(relative, reason, redact(body), truncated))

        if len(requests) > self.limits.max_context_files:
            problems.append(
                f"{len(requests) - self.limits.max_context_files} further file(s) were not "
                f"read: the packet is capped at {self.limits.max_context_files} files"
            )
        return files, problems

    def render(self, files: list[ContextFile]) -> str:
        if not files:
            return "(no files supplied; ask for what you need by path)"
        blocks = []
        for entry in files:
            blocks.append(
                f"### `{entry.path}`\n_why: {entry.reason}_\n\n```\n{entry.body}\n```"
            )
        return "\n\n".join(blocks)


@dataclass
class OperatorContext:
    """Text the operator hands the planner, bounded and recorded.

    A filename in a prompt is a hope. `plan --context-file` reads the file,
    bounds it, redacts it, digests it and puts the body in the packet, so what
    the planner received is what the operator wrote and the digest proves which
    revision of it that was.

    The file must be inside the repository, like every other context source in
    this package: a planning packet that can read `~/.aws/credentials` is a
    different tool.
    """

    files: list[ContextFile]
    digests: list[dict]
    problems: list[str]

    def render(self) -> str:
        if not self.files:
            return ""
        blocks = []
        for entry, meta in zip(self.files, self.digests):
            note = (f" — TRUNCATED at {len(entry.body)} characters of "
                    f"{meta['source_bytes']} bytes; read the rest from `{entry.path}` in "
                    f"this checkout before relying on it" if entry.truncated else "")
            stamp = (meta["source_digest"] or meta["delivered_digest"])[:16]
            blocks.append(
                f"### `{entry.path}` (sha256 {stamp}…{note})\n\n{entry.body}"
            )
        return "\n\n".join(blocks)


def read_operator_context(repo_root: Path, paths: list[str], limits: Limits,
                          *, max_files: int = 8) -> OperatorContext:
    """Read operator-supplied context files, refusing anything outside the repository.

    Two digests are recorded, because they answer two questions. `source_digest`
    is SHA-256 over the file's bytes on disk, and it identifies *which revision
    of the document* the operator supplied. `delivered_digest` is over the text
    that actually reached the provider, after redaction and any truncation, and
    it identifies *what the planner read*. Recording only the second would let
    two files with the same bounded prefix and different tails share an
    identifier -- which is the opposite of what a digest is for.
    """
    builder = ContextBuilder(repo_root, limits)
    requested = list(paths)[:max_files]
    problems: list[str] = []
    if len(paths) > max_files:
        problems.append(
            f"{len(paths) - max_files} further context file(s) were not read: "
            f"--context-file is capped at {max_files} files"
        )
    files, read_problems = builder.read(
        [(p, "supplied by the operator for this planning run") for p in requested]
    )
    problems.extend(read_problems)

    digests = []
    for entry in files:
        source = Path(repo_root) / entry.path
        try:
            raw = source.read_bytes()
            source_digest, source_bytes = digest_bytes(raw), len(raw)
        except OSError:
            source_digest, source_bytes = None, None
        digests.append({
            "path": entry.path,
            "source_digest": source_digest,
            "source_bytes": source_bytes,
            "delivered_digest": digest_text(entry.body),
            "delivered_characters": len(entry.body),
            "truncated": entry.truncated,
        })
    return OperatorContext(files=files, digests=digests, problems=problems)


def build_task_assignment(
    *, run_id: str, task: dict, spec: dict, base_commit: str,
    prerequisite_fingerprint: str, spec_digest: str, limits: Limits,
    prerequisite_artifacts: list[dict] | None = None,
    extra_rules: list[str] | None = None,
) -> dict:
    """Assemble and validate one `task_assignment/v1` packet."""
    requirement_index = {r["id"]: r["statement"] for r in spec["requirements"]}
    document = {
        "schema_version": "task_assignment/v1",
        "run_id": run_id,
        "task_id": task["id"],
        "title": task["title"],
        "role": task["role"],
        "objective": task["objective"],
        "base_commit": base_commit,
        "prerequisite_fingerprint": prerequisite_fingerprint,
        "spec_digest": spec_digest,
        "requirements": [
            {"id": rid, "statement": requirement_index.get(rid, "(not in the specification)")}
            for rid in task.get("requirement_ids", [])
        ],
        "acceptance_criteria": list(task.get("acceptance_criteria", [])),
        "allowed_paths": list(task.get("allowed_paths", [])),
        "forbidden_paths": list(task.get("forbidden_paths", [])),
        "verification_ids": list(task.get("verification_ids", [])),
        "context_files": [
            {"path": p, "reason": "named by the specification as task-relevant"}
            for p in task.get("context_paths", [])
        ],
        "prerequisite_artifacts": list(prerequisite_artifacts or []),
        "limits": {
            "deadline_seconds": limits.per_task_seconds,
            "max_output_bytes": limits.max_output_bytes,
        },
        "rules": [
            "Write only inside allowed_paths.",
            "Do not run git commit, push, merge, rebase, reset or stash; the controller owns Git.",
            "Do not modify controller state, verification definitions, or CI configuration.",
            "Request checks by registry id; the controller runs them and records evidence.",
            "Do not weaken or delete a failing test to make a check pass.",
            *(extra_rules or []),
        ],
    }
    validate_artifact(document, "task_assignment/v1")
    return document


def spec_digest_of(spec: dict) -> str:
    return digest_json(spec)
