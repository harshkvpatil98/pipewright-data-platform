"""Who may do what, decided from the HTTP method and path alone.

Every ownership check in the platform used to be "are you the one owner of this
project". That is the single thing stopping a second person from using it, and
the naive fix -- widen the check to "are you a member" -- would silently give a
viewer permission to delete a pipeline.

So permission is enforced in one place, as a function of the request rather
than of each service's own opinion:

* reads need membership,
* running things needs an operator,
* changing definitions needs an editor,
* changing *who has access* needs an admin.

The rule table below is the whole policy. Keeping it as a pure function over
``(method, path)`` means it is exhaustively testable without a server, and that
adding a route cannot accidentally skip the check -- an unrecognised write path
falls through to the strictest sensible role rather than to "allowed".
"""

from __future__ import annotations

from typing import Iterable

# Ordered from least to most privileged; index is the rank.
ROLES: tuple[str, ...] = ("viewer", "operator", "editor", "admin")
ROLE_RANK: dict[str, int] = {role: rank for rank, role in enumerate(ROLES)}

DEFAULT_ROLE = "viewer"
OWNER_ROLE = "admin"

READ_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})

# Path segments that mean "do the thing", not "change what the thing is".
# An operator can run the nightly job and clear an incident; they cannot edit
# the job or invent a new quality rule.
OPERATOR_SEGMENTS = frozenset(
    {
        "run",
        "runs",
        "run-queue-once",
        "execute",
        "evaluate",
        "backfill",
        "cancel",
        "acknowledge",
        "resolve",
        "reopen",
        "assign",
        "comments",
        "check",
        "capture",
        "retry",
        "ingest",
        "profile",
        # Re-reading every connector's schema and filing a drift incident. It
        # is the nightly job, run by hand -- the same thing "run" means
        # everywhere else in this set, and not a change to any definition.
        "watch",
    }
)

# Analytical POSTs. They compute an answer and store nothing, so requiring an
# editor for them would make "can I look at this?" an editing permission.
READ_ONLY_SEGMENTS = frozenset(
    {
        "preview",
        "impact",
        "validate",
        "test-connection",
        "test",
        "compare",
        "diff",
        "suggestions",
        "export",
        "discover",
        # EXPLAIN reports a plan without running the statement. The workbench
        # never emits EXPLAIN ANALYZE, which would.
        "explain",
        # Autocomplete. A POST because the script it completes against is too
        # long for a URL, not because it changes anything.
        "completions",
        # Working out how to read an uploaded file. A POST because the file is
        # the body; it stores nothing at all, and requiring an editor for it
        # would mean a viewer could not look at a file before somebody imports
        # it -- which is exactly when looking is useful.
        "analyze",
    }
)

# Anything touching who has access, or the project's own existence.
ADMIN_SEGMENTS = frozenset({"members", "memberships", "transfer"})


# Resources whose definitions are versioned, and therefore reviewable. An
# approval requirement covers edits to these and nothing else: gating runs or
# incident work behind review would stop the people on call from doing their job.
REVIEWABLE_SEGMENTS = frozenset({"workflows", "pipelines"})

# Actions that apply a staged change to a system this platform does not own.
# Staging one is a proposal and stays open to everyone who may edit; applying it
# is the reviewable moment, and the segment vocabulary above cannot express that
# because the reviewable thing is the final segment, not the resource.
APPLY_ACTIONS: dict[tuple[str, str], str] = {
    ("POST", "commit"): (
        "This project requires changes to be reviewed. The change set is saved; "
        "ask an approver to review and commit it."
    ),
}

_REVIEW_DEFAULT = (
    "This project requires changes to be reviewed. Propose the edit as a "
    "change request instead of saving it directly."
)


def review_refusal(method: str, path: str) -> str | None:
    """Why a governed project must refuse this request, or None if it may pass.

    Returning the sentence rather than a boolean keeps the reason next to the
    rule: "propose it as a change request" is wrong advice for a change set that
    has already been proposed and is waiting to be applied.
    """
    verb = method.upper()
    if verb in READ_METHODS:
        return None
    parts = _segments(path)
    if parts:
        specific = APPLY_ACTIONS.get((verb, parts[-1]))
        if specific is not None:
            return specific
    segments = set(parts)
    if segments & (ADMIN_SEGMENTS | READ_ONLY_SEGMENTS | OPERATOR_SEGMENTS):
        return None
    return _REVIEW_DEFAULT if segments & REVIEWABLE_SEGMENTS else None


def needs_review(method: str, path: str) -> bool:
    """Would this request change something a reviewer should see first?"""
    return review_refusal(method, path) is not None


class AccessDecision:
    """The outcome of one check, carrying why so callers can say it plainly."""

    __slots__ = ("allowed", "required_role", "actual_role", "reason")

    def __init__(self, *, allowed: bool, required_role: str, actual_role: str | None, reason: str) -> None:
        self.allowed = allowed
        self.required_role = required_role
        self.actual_role = actual_role
        self.reason = reason

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"AccessDecision(allowed={self.allowed}, required={self.required_role!r}, "
            f"actual={self.actual_role!r})"
        )


def normalise_role(role: str | None) -> str | None:
    if role is None:
        return None
    candidate = role.strip().lower()
    return candidate if candidate in ROLE_RANK else None


def outranks(role: str, required: str) -> bool:
    """Does ``role`` meet or exceed ``required``?"""
    known = normalise_role(role)
    if known is None:
        return False
    return ROLE_RANK[known] >= ROLE_RANK[required]


def _segments(path: str) -> list[str]:
    return [segment for segment in path.split("/") if segment]


def required_role(method: str, path: str) -> str:
    """The lowest role that may make this request.

    Deliberately ordered so the strictest rule wins: a POST to
    ``/members/{id}/run`` is member management first and a run second.
    """
    verb = method.upper()
    segments = set(_segments(path))

    if segments & ADMIN_SEGMENTS:
        return "admin"

    if verb in READ_METHODS:
        return "viewer"

    # Deleting a project is not the same as deleting something inside it.
    parts = _segments(path)
    if verb == "DELETE" and len(parts) >= 2 and parts[-2] == "projects":
        return "admin"

    if segments & READ_ONLY_SEGMENTS:
        return "viewer"

    if segments & OPERATOR_SEGMENTS:
        return "operator"

    # An unrecognised write is treated as a definition change. Failing closed
    # is the only safe default when a new route appears.
    return "editor"


def evaluate(
    *,
    method: str,
    path: str,
    role: str | None,
) -> AccessDecision:
    """Decide one request."""
    needed = required_role(method, path)
    known = normalise_role(role)

    if known is None:
        return AccessDecision(
            allowed=False,
            required_role=needed,
            actual_role=None,
            reason="You are not a member of this project.",
        )

    if outranks(known, needed):
        return AccessDecision(
            allowed=True, required_role=needed, actual_role=known, reason="Allowed."
        )

    return AccessDecision(
        allowed=False,
        required_role=needed,
        actual_role=known,
        reason=(
            f"This needs the {needed} role or above; you have {known} access to this project."
        ),
    )


def describe(role: str) -> str:
    """One line a person can read next to the role name."""
    return {
        "viewer": "Can see everything in the project, and change nothing.",
        "operator": "Can run pipelines and workflows, and work incidents. Cannot edit definitions.",
        "editor": "Can create and edit pipelines, workflows, and rules, and run them.",
        "admin": "Full control, including managing who has access.",
    }.get(role, "Unknown role.")


def highest(roles: Iterable[str | None]) -> str | None:
    """The most privileged of several roles, ignoring unknown ones."""
    known = [normalise_role(role) for role in roles]
    ranked = [role for role in known if role is not None]
    if not ranked:
        return None
    return max(ranked, key=lambda role: ROLE_RANK[role])
