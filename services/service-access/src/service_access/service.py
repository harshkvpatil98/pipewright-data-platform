"""Managing who has access to a project."""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError

from service_access.models import ProjectMembership
from service_access.permissions import ROLES, describe, normalise_role
from service_access.resolver import role_for
from service_access.schemas import (
    MemberInvite,
    MemberListResponse,
    MemberRead,
    MemberRoleUpdate,
    RoleCatalogResponse,
    RoleReference,
)


def role_catalog() -> RoleCatalogResponse:
    return RoleCatalogResponse(
        items=[RoleReference(role=role, description=describe(role)) for role in ROLES]  # type: ignore[arg-type]
    )


def _user_by_name(db: Session, username: str) -> User:
    user = db.scalar(select(User).where(func.lower(User.username) == username.strip().lower()))
    if user is None:
        raise NotFoundError(f"No user named '{username.strip()}'.")
    return user


def list_members(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> MemberListResponse:
    project = ensure_owned_project(db, project_id, current_user.id)

    rows = db.scalars(
        select(ProjectMembership)
        .where(ProjectMembership.project_id == project_id)
        .order_by(ProjectMembership.created_at.asc())
    ).all()

    user_ids = [row.user_id for row in rows]
    if project.owner_user_id:
        user_ids.append(project.owner_user_id)
    user_ids.extend(row.invited_by_user_id for row in rows if row.invited_by_user_id)
    names = _usernames(db, user_ids)

    items: list[MemberRead] = []
    if project.owner_user_id is not None:
        items.append(
            MemberRead(
                id=None,
                user_id=project.owner_user_id,
                username=names.get(project.owner_user_id, "unknown"),
                role="admin",
                is_owner=True,
                created_at=project.created_at,
            )
        )
    for row in rows:
        items.append(
            MemberRead(
                id=row.id,
                user_id=row.user_id,
                username=names.get(row.user_id, "unknown"),
                role=normalise_role(row.role) or "viewer",  # type: ignore[arg-type]
                is_owner=False,
                invited_by_username=(
                    names.get(row.invited_by_user_id) if row.invited_by_user_id else None
                ),
                created_at=row.created_at,
            )
        )

    return MemberListResponse(
        items=items,
        your_role=role_for(db, project_id, current_user.id) or "viewer",  # type: ignore[arg-type]
    )


def _usernames(db: Session, user_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    unique = [user_id for user_id in dict.fromkeys(user_ids) if user_id is not None]
    if not unique:
        return {}
    rows = db.execute(select(User.id, User.username).where(User.id.in_(unique))).all()
    return {row[0]: row[1] for row in rows}


def invite_member(
    db: Session, project_id: uuid.UUID, payload: MemberInvite, current_user: UserRead
) -> MemberRead:
    project = ensure_owned_project(db, project_id, current_user.id)
    user = _user_by_name(db, payload.username)

    if project.owner_user_id == user.id:
        raise BadRequestError(
            f"'{user.username}' owns this project and already has full access."
        )

    existing = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.project_id == project_id, ProjectMembership.user_id == user.id
        )
    )
    if existing is not None:
        raise BadRequestError(
            f"'{user.username}' is already a member; change their role instead."
        )

    membership = ProjectMembership(
        project_id=project_id,
        user_id=user.id,
        role=payload.role,
        invited_by_user_id=current_user.id,
    )
    db.add(membership)
    db.commit()
    db.refresh(membership)

    return MemberRead(
        id=membership.id,
        user_id=user.id,
        username=user.username,
        role=payload.role,
        is_owner=False,
        invited_by_username=current_user.username,
        created_at=membership.created_at,
    )


def _get_membership(
    db: Session, project_id: uuid.UUID, membership_id: uuid.UUID
) -> ProjectMembership:
    membership = db.scalar(
        select(ProjectMembership).where(
            ProjectMembership.id == membership_id,
            ProjectMembership.project_id == project_id,
        )
    )
    if membership is None:
        raise NotFoundError("Membership not found.")
    return membership


def update_member_role(
    db: Session,
    project_id: uuid.UUID,
    membership_id: uuid.UUID,
    payload: MemberRoleUpdate,
    current_user: UserRead,
) -> MemberRead:
    ensure_owned_project(db, project_id, current_user.id)
    membership = _get_membership(db, project_id, membership_id)

    if membership.user_id == current_user.id:
        # Otherwise an admin can demote themselves and lock the project.
        raise BadRequestError("You cannot change your own role.")

    membership.role = payload.role
    db.commit()
    db.refresh(membership)

    names = _usernames(db, [membership.user_id])
    return MemberRead(
        id=membership.id,
        user_id=membership.user_id,
        username=names.get(membership.user_id, "unknown"),
        role=payload.role,
        is_owner=False,
        created_at=membership.created_at,
    )


def remove_member(
    db: Session, project_id: uuid.UUID, membership_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    membership = _get_membership(db, project_id, membership_id)
    if membership.user_id == current_user.id:
        raise BadRequestError("You cannot remove your own access.")
    db.delete(membership)
    db.commit()


def total_memberships(db: Session) -> int:
    return db.scalar(select(func.count(ProjectMembership.id))) or 0


def shared_project_count(db: Session) -> int:
    """Projects with at least one member besides their owner."""
    return (
        db.scalar(
            select(func.count(func.distinct(ProjectMembership.project_id)))
        )
        or 0
    )
