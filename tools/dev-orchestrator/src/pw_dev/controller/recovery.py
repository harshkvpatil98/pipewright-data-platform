"""Crash recovery and idempotent resume.

The rule this file exists to enforce: **never assume a timed-out or crashed
provider did nothing.** A worker that was killed may have written half its
changes; a controller that died between `commit` and `push` may or may not have
published. Recovery reconciles against the actual filesystem, Git and remote
state before deciding anything.

Duplicate work is the failure mode being avoided:

* a duplicate worker, because a stale lease looked free;
* a duplicate commit, because the previous one was not noticed;
* a duplicate push, because the remote was not read before pushing again.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..config import Config
from ..state.db import RunStore
from ..state.machine import RESUMABLE_RUN_STATES, RunState, TaskState, is_terminal
from ..util.hashing import tree_fingerprint
from ..workspace import git


@dataclass
class Reconciliation:
    """What was found on disk and at the remote, and what it means."""

    run_id: str
    recorded_state: str
    resumable: bool
    observations: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    blocked_reason: str | None = None

    def render(self) -> str:
        lines = [f"run {self.run_id} recorded as {self.recorded_state}"]
        lines += [f"  observed: {o}" for o in self.observations]
        lines += [f"  action:   {a}" for a in self.actions]
        if self.blocked_reason:
            lines.append(f"  blocked:  {self.blocked_reason}")
        return "\n".join(lines)


def reconcile(config: Config, store: RunStore, run_id: str, *,
              own_token: str | None = None) -> Reconciliation:
    """Work out what actually happened, before deciding anything.

    `own_token` is the caller's own controller lock, so a controller that has
    already claimed the run does not report itself as a competing owner.
    """
    row = store.get_run(run_id)
    state = RunState(row["state"])
    report = Reconciliation(
        run_id=run_id, recorded_state=state.value,
        resumable=state in RESUMABLE_RUN_STATES or not is_terminal(state),
    )

    holder = store.run_lock_holder(run_id)
    if holder is not None and own_token is not None and holder["owner_token"] == own_token:
        holder = None  # this caller already owns the run
    if holder is not None:
        from ..state.db import _pid_alive

        if _pid_alive(int(holder["owner_pid"])):
            report.resumable = False
            report.blocked_reason = (
                f"pid {holder['owner_pid']} on {holder['hostname']} still owns this run. "
                f"Two controllers would dispatch the same task twice."
            )
            return report
        report.observations.append(
            f"the controller lock was left by pid {holder['owner_pid']}, which is gone"
        )
        report.actions.append("the lock will be reclaimed on resume")

    for lease in store.stale_leases(run_id):
        task_id = lease["task_id"]
        report.observations.append(
            f"task {task_id} holds an expired lease from pid {lease['owner_pid']}"
            + (f" (child pid {lease['child_pid']})" if lease["child_pid"] else "")
        )
        task = store.get_task(run_id, task_id)
        worktree = task["worktree"]
        if worktree and Path(worktree).is_dir():
            changed = git.changed_paths(Path(worktree), row["base_commit"] or "HEAD")
            if changed:
                report.observations.append(
                    f"  its checkout {Path(worktree).name} contains {len(changed)} changed "
                    f"path(s); the interrupted provider did not do nothing"
                )
                report.actions.append(
                    f"  {task_id} will be re-run from a fresh checkout and the partial work "
                    f"kept as an artifact, not applied blind"
                )
            else:
                report.observations.append("  its checkout is unchanged")
                report.actions.append(f"  {task_id} will be re-dispatched")
        store.set_task_state(
            run_id, task_id, TaskState.PENDING,
            "reset after an expired lease; the previous attempt is preserved as an artifact",
        )

    # An exclusive resource is held by a *running* task, and nothing is running:
    # the process that held this run's lock is gone, which is why we are
    # reconciling at all. Locks that outlived it belong to nobody.
    #
    # Leaving them was a deadlock with no way out. A task reset to PENDING above
    # still held its own resources, so the scheduler refused to dispatch it --
    # "T-01: waiting on exclusive resource: alembic (held by T-01)" -- and every
    # later task waited on T-01 for ever.
    stranded = store.held_resources(run_id)
    if stranded:
        for resource, holder in sorted(stranded.items()):
            store.release_resource(run_id, resource, holder)
        report.actions.append(
            f"released {len(stranded)} exclusive resource(s) still recorded as held by "
            f"{', '.join(sorted(set(stranded.values())))}; the run that held them is gone, "
            f"and the scheduler re-acquires what it needs"
        )

    candidate = config.runs_dir() / run_id / "candidate"
    if candidate.is_dir():
        fingerprint = tree_fingerprint(candidate)
        recorded = row["candidate_fingerprint"]
        report.observations.append(
            f"the integration checkout is at {fingerprint[:20]}…"
            + (f" (recorded {recorded[:20]}…)" if recorded else " (nothing recorded)")
        )
        if recorded and fingerprint != recorded:
            report.actions.append(
                "the candidate changed since the recorded fingerprint; all evidence and any "
                "approval bound to the old one are invalidated and will be re-run"
            )
            store.update_run_fields(run_id, approved_fingerprint=None)

    if state in (RunState.COMMIT, RunState.PUSH, RunState.COMPLETE):
        report.observations.extend(_reconcile_publication(config, store, run_id, row, candidate))

    return report


def _reconcile_publication(config: Config, store: RunStore, run_id: str, row,
                           candidate: Path) -> list[str]:
    """Find out whether the commit and the push actually happened.

    Asked of Git and of the remote, not of our own record: the record is what
    might be missing.
    """
    notes: list[str] = []
    base = row["base_commit"]
    if not candidate.is_dir() or not base:
        notes.append("no integration checkout remains; publication state cannot be re-derived")
        return notes

    head = git.head_sha(candidate)
    new_commits = git.commits_between(candidate, base, head)
    if new_commits:
        notes.append(
            f"{len(new_commits)} commit(s) already exist locally beyond the base; the newest "
            f"is {new_commits[0][:12]}. A resume must not create a second one."
        )
    else:
        notes.append("no commit was created locally")

    receipt = config.runs_dir() / run_id / "publication-receipt.json"
    branch = None
    if receipt.is_file():
        import json

        try:
            document = json.loads(receipt.read_text(encoding="utf-8"))
            branch = document.get("branch")
            notes.append(
                f"a publication receipt exists: published={document.get('published')}, "
                f"branch={branch}, remote sha={document.get('remote_sha_after_push')}"
            )
        except (OSError, ValueError):
            notes.append("a publication receipt exists but could not be read")

    if branch:
        try:
            remote_sha = git.ls_remote(candidate, config.publication.remote,
                                       f"refs/heads/{branch}")
        except Exception as exc:  # noqa: BLE001 - the remote may be unreachable
            notes.append(f"the remote could not be queried: {exc}")
        else:
            if remote_sha is None:
                notes.append(
                    f"{config.publication.remote}/{branch} does not exist: nothing was "
                    f"published, so a resume may publish once"
                )
            elif new_commits and remote_sha == new_commits[0]:
                notes.append(
                    f"{config.publication.remote}/{branch} already points at "
                    f"{remote_sha[:12]} — this run was published. A resume must not push again."
                )
                store.set_run_state(
                    run_id, RunState.COMPLETE,
                    f"reconciled after a crash: {branch} already carries {remote_sha[:12]}",
                    force=True,
                )
            else:
                notes.append(
                    f"{config.publication.remote}/{branch} is at {remote_sha[:12]}, which is "
                    f"not this run's commit. The target moved; resume will block rather than "
                    f"overwrite it."
                )
    return notes
