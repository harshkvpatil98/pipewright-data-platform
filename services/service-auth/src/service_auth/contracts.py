"""How long a session lasts, when something other than the deployment decides.

The deployment sets one session lifetime for everybody. An organisation that
handles regulated data wants a shorter one, and the platform that cannot give it
to them loses the account -- but `service_auth` must not import
`service_enterprise` to find out, because tenancy depends on auth and not the
other way round.

So the lookup is injected, exactly as `service_projects.contracts` injects the
project-role resolver: `service_enterprise` registers a resolver at import time,
and until it does the behaviour is precisely what it was before -- the
deployment default for everyone. A missing resolver therefore falls back to the
existing policy rather than to no policy, which is the safe direction for a
value that controls how long a credential stays valid.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from sqlalchemy.orm import Session

# Returns the session lifetime in minutes for this user, or None to mean "no
# opinion -- use the deployment default".
SessionPolicyResolver = Callable[[Session, uuid.UUID], int | None]

# A session may not be shortened below this or stretched beyond it, whatever a
# tenant asks for. One minute is unusable and someone would eventually type it;
# thirty days is long enough that "session" stops being an honest word for it.
MIN_SESSION_MINUTES = 5
MAX_SESSION_MINUTES = 60 * 24 * 30

_session_policy_resolver: SessionPolicyResolver | None = None


def register_session_policy_resolver(resolver: SessionPolicyResolver | None) -> None:
    """Teach token issuing about per-organisation session policy."""
    global _session_policy_resolver
    _session_policy_resolver = resolver


def clamp_session_minutes(minutes: int) -> int:
    return max(MIN_SESSION_MINUTES, min(MAX_SESSION_MINUTES, int(minutes)))


def session_minutes_for(db: Session, user_id: uuid.UUID, *, default: int) -> int:
    """The session lifetime to stamp on a token issued to this user.

    Every token this platform mints goes through here, so a tenant's policy
    applies whichever way its people sign in -- password, second factor, or an
    identity provider. A resolver that raises must not be able to stop anyone
    signing in, so a failure falls back to the deployment default rather than
    propagating: a misconfigured policy should shorten nobody's day.
    """
    if _session_policy_resolver is None:
        return clamp_session_minutes(default)
    try:
        override = _session_policy_resolver(db, user_id)
    except Exception:  # noqa: BLE001 - a broken policy must not block sign-in
        return clamp_session_minutes(default)
    if override is None:
        return clamp_session_minutes(default)
    return clamp_session_minutes(override)
