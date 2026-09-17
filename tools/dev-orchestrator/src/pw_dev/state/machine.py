"""The run state machine.

Every transition is explicit. A status is only allowed to mean one thing, and
the ones that look like success are the narrowest.

Three of them are separated on purpose, because they were once one word:

* `PLAN_READY` -- a specification passed structural and policy validation.
  Nobody implemented it, no check ran against it, and no reviewer saw it.
  Validation establishes that the document is well-formed, in scope, within the
  adopted budget and free of the conflicts the controller can decide; it
  establishes nothing about whether the design is right;
* `VERIFIED_LOCAL` -- an implementation the controller verified and an
  independent reviewer approved. Nothing was published;
* `COMPLETE` -- the above, published, with the remote ref read back and matched.

A plan-only run used to finish in `VERIFIED_LOCAL`, whose own description says
"verified and approved". It was neither. `PLAN_READY` exists so the status is
the truth rather than the nearest available word.

Neither success state is reachable from an exhausted budget -- that is `PAUSED`,
which is resumable, and says so.
"""

from __future__ import annotations

from enum import Enum


class RunState(str, Enum):
    DISCOVER = "DISCOVER"
    PLAN = "PLAN"
    WAITING_FOR_PLAN = "WAITING_FOR_PLAN"
    VALIDATE_PLAN = "VALIDATE_PLAN"
    PLAN_READY = "PLAN_READY"
    IMPLEMENT = "IMPLEMENT"
    INTEGRATE = "INTEGRATE"
    VERIFY = "VERIFY"
    REVIEW = "REVIEW"
    WAITING_FOR_REVIEW = "WAITING_FOR_REVIEW"
    NEEDS_FIX = "NEEDS_FIX"
    COMMIT = "COMMIT"
    PUSH = "PUSH"
    COMPLETE = "COMPLETE"
    VERIFIED_LOCAL = "VERIFIED_LOCAL"
    BLOCKED = "BLOCKED"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"
    FAILED = "FAILED"


class TaskState(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    REPORTED = "REPORTED"
    INTEGRATED = "INTEGRATED"
    NEEDS_FIX = "NEEDS_FIX"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    DONE = "DONE"


#: States a run can stop in. Only two of them mean the work is finished, and
#: `VERIFIED_LOCAL` explicitly does not mean anything was published.
TERMINAL_RUN_STATES = frozenset({
    RunState.COMPLETE, RunState.VERIFIED_LOCAL, RunState.PLAN_READY,
    RunState.CANCELLED, RunState.FAILED,
})

#: Stopping states that are not a failure. They mean different amounts, which is
#: the point of keeping them apart.
SUCCESSFUL_RUN_STATES = frozenset({
    RunState.COMPLETE, RunState.VERIFIED_LOCAL, RunState.PLAN_READY,
})

#: Stopped but resumable. A run here has preserved work and a stated condition.
RESUMABLE_RUN_STATES = frozenset({
    RunState.WAITING_FOR_PLAN, RunState.WAITING_FOR_REVIEW,
    RunState.PAUSED, RunState.BLOCKED, RunState.NEEDS_FIX,
})

_ALLOWED: dict[RunState, frozenset[RunState]] = {
    RunState.DISCOVER: frozenset({
        RunState.PLAN,
        # `pw-dev run --spec <path>` supplies a specification instead of asking
        # the planner for one, so a run can go straight to validation. The
        # specification is validated either way -- skipping PLAN does not skip
        # the gate.
        RunState.VALIDATE_PLAN,
        RunState.BLOCKED, RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.PLAN: frozenset({
        RunState.VALIDATE_PLAN, RunState.WAITING_FOR_PLAN, RunState.BLOCKED,
        RunState.PAUSED, RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.WAITING_FOR_PLAN: frozenset({
        RunState.VALIDATE_PLAN, RunState.BLOCKED, RunState.CANCELLED, RunState.FAILED,
    }),
    RunState.VALIDATE_PLAN: frozenset({
        RunState.IMPLEMENT, RunState.PLAN, RunState.WAITING_FOR_PLAN,
        # A plan-only run stops here: a validated specification was produced and
        # deliberately not implemented. That is a finished run, not an abandoned
        # one -- and it is `PLAN_READY`, not `VERIFIED_LOCAL`, because nothing
        # was verified and nobody reviewed it.
        RunState.PLAN_READY,
        RunState.BLOCKED, RunState.PAUSED, RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.IMPLEMENT: frozenset({
        RunState.INTEGRATE, RunState.NEEDS_FIX, RunState.BLOCKED,
        RunState.PAUSED, RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.INTEGRATE: frozenset({
        RunState.VERIFY, RunState.NEEDS_FIX, RunState.IMPLEMENT,
        RunState.BLOCKED, RunState.PAUSED, RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.VERIFY: frozenset({
        RunState.REVIEW, RunState.NEEDS_FIX, RunState.BLOCKED,
        RunState.PAUSED, RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.REVIEW: frozenset({
        RunState.COMMIT, RunState.VERIFIED_LOCAL, RunState.NEEDS_FIX,
        RunState.WAITING_FOR_REVIEW, RunState.BLOCKED, RunState.PAUSED,
        RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.WAITING_FOR_REVIEW: frozenset({
        RunState.COMMIT, RunState.VERIFIED_LOCAL, RunState.NEEDS_FIX,
        RunState.BLOCKED, RunState.CANCELLED, RunState.FAILED,
    }),
    RunState.NEEDS_FIX: frozenset({
        RunState.IMPLEMENT, RunState.BLOCKED, RunState.PAUSED,
        RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.COMMIT: frozenset({
        RunState.PUSH, RunState.VERIFIED_LOCAL, RunState.BLOCKED,
        RunState.FAILED, RunState.CANCELLED,
    }),
    RunState.PUSH: frozenset({
        RunState.COMPLETE, RunState.BLOCKED, RunState.FAILED, RunState.CANCELLED,
    }),
    # A paused or blocked run re-enters at the phase it stopped in.
    RunState.PAUSED: frozenset({
        RunState.DISCOVER, RunState.PLAN, RunState.VALIDATE_PLAN, RunState.IMPLEMENT,
        RunState.INTEGRATE, RunState.VERIFY, RunState.REVIEW, RunState.NEEDS_FIX,
        RunState.CANCELLED, RunState.FAILED,
    }),
    RunState.BLOCKED: frozenset({
        RunState.PLAN, RunState.VALIDATE_PLAN, RunState.IMPLEMENT, RunState.INTEGRATE,
        RunState.VERIFY, RunState.REVIEW, RunState.NEEDS_FIX, RunState.COMMIT,
        RunState.PUSH, RunState.CANCELLED, RunState.FAILED,
    }),
    RunState.COMPLETE: frozenset(),
    RunState.VERIFIED_LOCAL: frozenset(),
    RunState.PLAN_READY: frozenset(),
    RunState.CANCELLED: frozenset(),
    RunState.FAILED: frozenset(),
}


def transition_allowed(current: RunState, nxt: RunState) -> bool:
    return nxt in _ALLOWED.get(current, frozenset())


def is_terminal(state: RunState) -> bool:
    return state in TERMINAL_RUN_STATES


def describe(state: RunState) -> str:
    """One line a person can act on, not a status word on its own."""
    return {
        RunState.DISCOVER: "reading the repository and capturing a baseline",
        RunState.PLAN: "the planner is producing a phase specification",
        RunState.WAITING_FOR_PLAN: "waiting for an operator-supplied specification (pw-dev plan-import)",
        RunState.VALIDATE_PLAN: "validating the specification against the adopted policy",
        RunState.PLAN_READY: (
            "the specification passed structural and policy validation; nothing was "
            "implemented, no check was executed and no reviewer saw it"
        ),
        RunState.IMPLEMENT: "workers are implementing assigned tasks",
        RunState.INTEGRATE: "integrating completed task outputs into the candidate",
        RunState.VERIFY: "the controller is executing required verifications",
        RunState.REVIEW: "an independent reviewer is inspecting the candidate",
        RunState.WAITING_FOR_REVIEW: "waiting for an operator-supplied review (pw-dev review-import)",
        RunState.NEEDS_FIX: "review or verification found concrete problems; repair is pending",
        RunState.COMMIT: "creating the commit for the approved tree",
        RunState.PUSH: "publishing the verified branch",
        RunState.COMPLETE: "published, and the remote ref was read back and matched",
        RunState.VERIFIED_LOCAL: (
            "implemented, verified by the controller and approved by an independent "
            "reviewer; publication was not requested, so nothing was published"
        ),
        RunState.BLOCKED: "stopped on a condition the controller may not decide alone",
        RunState.PAUSED: "a configured limit was reached; the run is resumable",
        RunState.CANCELLED: "cancelled by the operator; recoverable work was preserved",
        RunState.FAILED: "stopped on an unrecoverable error",
    }[state]


def describe_run(state: RunState, *, plan_only: bool = False) -> str:
    """The line for one stored run, which may predate `PLAN_READY`.

    Runs recorded before that state existed finished plan-only work in
    `VERIFIED_LOCAL`. Their rows are historical evidence and are not rewritten;
    they are described for what they were instead, so an old plan-only run is
    not read as an approved implementation and an old implementation run is not
    demoted to a plan.
    """
    if plan_only and state is RunState.VERIFIED_LOCAL:
        return (
            "a specification was produced and validated; nothing was implemented, verified "
            "or reviewed. Recorded before PLAN_READY existed, under the state this tool "
            "then used for a plan-only run"
        )
    return describe(state)
