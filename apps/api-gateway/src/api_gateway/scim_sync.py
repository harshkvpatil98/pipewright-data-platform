"""SCIM-lite: deactivate accounts that have left the directory.

Full SCIM is a provisioning API the identity provider pushes to. This is the
90% of its value with 10% of the surface: a batch job that takes the set of
people still in the directory and deactivates the directory-managed accounts
that are no longer in it -- so an employee who is offboarded in Okta loses
access here without anyone remembering to click a button.

Two invariants make it safe to run unattended:
* **Only SSO accounts are ever touched.** A local admin created here is never
  in the directory, and must never be swept for it. `auth_source` is the guard.
* **The platform is never left without an admin.** If deactivating the last
  active admin would lock everyone out, that one account is skipped and
  reported, not deactivated.

It deactivates rather than deletes: an account that returns to the directory is
reactivated on its next sign-in, and its owned projects and audit trail survive
in the meantime.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from shared_python.logging import get_logger

logger = get_logger(__name__)


def _active_admins_excluding(db: Session, user_ids: set) -> int:
    return (
        db.scalar(
            select(func.count(User.id)).where(
                User.role == "admin",
                User.is_active.is_(True),
                User.id.notin_(user_ids) if user_ids else User.id.isnot(None),
            )
        )
        or 0
    )


def deactivate_absent_sso_users(
    db: Session,
    *,
    present_usernames: set[str],
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict:
    """Deactivate directory-managed accounts absent from `present_usernames`.

    `present_usernames` is the authoritative snapshot from the directory
    (normalised the same way SSO stores them: lower-cased). Returns a summary
    naming what was deactivated and what was skipped, so a run is auditable.
    """
    present = {name.strip().lower() for name in present_usernames if name and name.strip()}
    moment = now or datetime.now(UTC)

    managed = list(
        db.scalars(
            select(User).where(User.auth_source == "sso", User.is_active.is_(True))
        ).all()
    )
    absent = [user for user in managed if user.username.lower() not in present]

    deactivated: list[str] = []
    skipped_admins: list[str] = []

    # Which absent admins can we safely deactivate? Never drop active admins to
    # zero; if several admins are absent at once, keep whichever would be last.
    to_deactivate = []
    for user in absent:
        if user.role == "admin":
            # Would deactivating this admin (and the ones already queued) leave
            # no active admin at all?
            queued_ids = {u.id for u in to_deactivate} | {user.id}
            if _active_admins_excluding(db, queued_ids) == 0:
                skipped_admins.append(user.username)
                continue
        to_deactivate.append(user)

    if not dry_run:
        for user in to_deactivate:
            user.is_active = False
            # End every live session for the offboarded person immediately.
            user.token_version = int(user.token_version or 0) + 1
        if to_deactivate:
            db.commit()

    deactivated = [user.username for user in to_deactivate]
    summary = {
        "checked": len(managed),
        "present": len(present),
        "deactivated": deactivated,
        "skipped_last_admin": skipped_admins,
        "dry_run": dry_run,
        "ran_at": moment.isoformat(),
    }
    if deactivated or skipped_admins:
        logger.info(
            "scim_sync deactivated=%s skipped_admins=%s dry_run=%s",
            len(deactivated),
            len(skipped_admins),
            dry_run,
        )
    return summary
