"""Who else has something open right now (roadmap Phase 21, C2).

A page that wants people to see each other (the Studio, on a recipe) says
so every few seconds with what the person has open in it; the answer is
everyone else there. Someone not heard from for twenty seconds has gone,
and is dropped from the answer at once and from the table soon after. No
history is kept: who was here an hour ago is the activity stream's
business, not this.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project

from service_governance.models import Presence
from service_governance.schemas import PresencePerson, PresenceResponse, PresenceUpdate

#: Someone not heard from for this long has left.
GONE_AFTER = timedelta(seconds=20)
#: Rows older than this are removed when anyone next says they are here.
FORGET_AFTER = timedelta(hours=1)
COLOURS = 8


def _now() -> datetime:
    return datetime.now(UTC)


def colour_for(user_id: uuid.UUID) -> int:
    """The same colour for a person on every machine."""
    return int(hashlib.sha256(str(user_id).encode()).hexdigest(), 16) % COLOURS


def initials_of(name: str) -> str:
    parts = [part for part in name.replace(".", " ").replace("_", " ").replace("-", " ").split() if part]
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _people(db: Session, target_type: str, target_id: uuid.UUID, current_user: UserRead) -> PresenceResponse:
    since = _now() - GONE_AFTER
    rows = db.execute(
        select(Presence, User.display_name, User.username)
        .join(User, User.id == Presence.user_id)
        .where(Presence.target_type == target_type, Presence.target_id == target_id, Presence.seen_at >= since)
        .order_by(Presence.created_at)
    ).all()
    people = []
    for row, display_name, username in rows:
        name = display_name or username
        people.append(
            PresencePerson(
                user_id=row.user_id,
                name=name,
                initials=initials_of(name),
                colour=colour_for(row.user_id),
                focus=row.focus_json,
                you=row.user_id == current_user.id,
                client_id=row.client_id,
            )
        )
    return PresenceResponse(people=people)


def _check_target(db: Session, project_id: uuid.UUID, target_type: str, target_id: uuid.UUID) -> None:
    from shared_python.errors import NotFoundError

    if target_type == "recipe":
        from service_transformations.models import TransformationPipeline

        found = db.scalar(
            select(TransformationPipeline.id).where(
                TransformationPipeline.id == target_id, TransformationPipeline.project_id == project_id
            )
        )
        if found is None:
            raise NotFoundError("That recipe is not in this project.")


def _row(db: Session, payload: PresenceUpdate) -> Presence | None:
    return db.scalar(
        select(Presence).where(
            Presence.target_type == payload.target_type,
            Presence.target_id == payload.target_id,
            Presence.client_id == payload.client_id,
        )
    )


def here(db: Session, project_id: uuid.UUID, payload: PresenceUpdate, current_user: UserRead) -> PresenceResponse:
    """Say this person has it open (and what in it); hear who else has."""
    ensure_owned_project(db, project_id, current_user.id)
    _check_target(db, project_id, payload.target_type, payload.target_id)
    moment = _now()
    row = _row(db, payload)
    if row is None:
        # Two requests from one page can arrive together; the second finds
        # the first's row rather than failing on the unique constraint.
        try:
            with db.begin_nested():
                db.add(
                    Presence(
                        project_id=project_id,
                        target_type=payload.target_type,
                        target_id=payload.target_id,
                        client_id=payload.client_id,
                        user_id=current_user.id,
                        seen_at=moment,
                    )
                )
        except IntegrityError:
            pass
        row = _row(db, payload)
    if row is None or row.user_id != current_user.id:
        # A browser tab is one person's; another's id is not taken over.
        from shared_python.errors import ConflictError

        raise ConflictError("That page belongs to someone else; reload it.")
    row.focus_json = {key: value[:64] for key, value in (payload.focus or {}).items()} or None
    row.seen_at = moment
    db.execute(
        delete(Presence).where(
            Presence.target_type == payload.target_type,
            Presence.target_id == payload.target_id,
            Presence.seen_at < moment - FORGET_AFTER,
        )
    )
    db.commit()
    return _people(db, payload.target_type, payload.target_id, current_user)


def leave(
    db: Session, project_id: uuid.UUID, target_type: str, target_id: uuid.UUID, client_id: str, current_user: UserRead
) -> None:
    """This tab has closed: drop it at once rather than after twenty seconds."""
    ensure_owned_project(db, project_id, current_user.id)
    db.execute(
        delete(Presence).where(
            Presence.target_type == target_type,
            Presence.target_id == target_id,
            Presence.client_id == client_id,
            Presence.user_id == current_user.id,
        )
    )
    db.commit()


def who_is_here(
    db: Session, project_id: uuid.UUID, target_type: str, target_id: uuid.UUID, current_user: UserRead
) -> PresenceResponse:
    ensure_owned_project(db, project_id, current_user.id)
    return _people(db, target_type, target_id, current_user)
