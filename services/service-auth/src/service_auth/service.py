from __future__ import annotations

import uuid

from sqlalchemy import Uuid, bindparam, func, select, text
from sqlalchemy.orm import Session

from service_auth.models import User, UserPreference
from service_auth.schemas import (
    BootstrapUserRequest,
    PreferencesRead,
    PreferencesUpdate,
    UserCreateRequest,
    UserRead,
    UserUpdateRequest,
)
from shared_python.auth.security import hash_password, verify_password
from shared_python.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
)


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def create_user(db: Session, payload: BootstrapUserRequest | UserCreateRequest) -> User:
    if get_user_by_username(db, payload.username) is not None:
        raise ConflictError("A user with that username already exists.")

    user = User(
        username=payload.username.strip().lower(),
        password_hash=hash_password(payload.password),
        role=payload.role,
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def authenticate_user(db: Session, username: str, password: str) -> User:
    user = get_user_by_username(db, username.strip().lower())
    if user is None or not verify_password(password, user.password_hash):
        raise UnauthorizedError("Invalid username or password.")
    if not user.is_active:
        raise UnauthorizedError("User account is inactive.")
    return user


def list_users(db: Session, *, limit: int = 200) -> list[User]:
    """Everyone with an account, oldest first."""
    return list(
        db.scalars(select(User).order_by(User.created_at.asc()).limit(limit)).all()
    )


#: Projects this person owns. Raw SQL for the same reason `service_projects`
#: counts datasets that way: `service_projects` imports this package's schemas,
#: so importing its models back would be a cycle. The bind parameter is typed
#: explicitly because an untyped one is handed straight to the driver, which
#: works on Postgres and fails on the SQLite the tests run against.
_COUNT_OWNED_PROJECTS = text(
    "SELECT COUNT(*) FROM projects WHERE owner_user_id = :user_id"
).bindparams(bindparam("user_id", type_=Uuid(as_uuid=True)))


def owned_project_count(db: Session, user_id: uuid.UUID) -> int:
    return db.execute(_COUNT_OWNED_PROJECTS, {"user_id": user_id}).scalar_one() or 0


def _get_user_or_404(db: Session, user_id: uuid.UUID) -> User:
    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    return user


def _other_active_admins(db: Session, user_id: uuid.UUID) -> int:
    """Admins who could still administer the platform without this one."""
    return (
        db.scalar(
            select(func.count(User.id)).where(
                User.role == "admin", User.is_active.is_(True), User.id != user_id
            )
        )
        or 0
    )


def update_user(
    db: Session, user_id: uuid.UUID, payload: UserUpdateRequest, actor: UserRead
) -> User:
    """Deactivate an account, reactivate it, or change its platform role.

    Two things this refuses, both of which are ways to lock the platform.

    You cannot act on yourself. An admin who deactivates their own account is
    signed out with no way back in, and one who demotes themselves cannot
    undo it -- and neither is ever what was meant, because the account being
    offboarded is somebody else's.

    You cannot remove the last admin. Deactivating or demoting the only
    remaining one leaves an install nobody can administer: no new accounts, no
    role changes, and no way to appoint a replacement. Both paths are checked
    because demoting is the one that does not look destructive.
    """
    user = _get_user_or_404(db, user_id)
    if user.id == actor.id:
        raise BadRequestError(
            "You cannot change your own account here. Ask another admin to do it."
        )

    fields = payload.model_dump(exclude_unset=True)
    deactivating = fields.get("is_active") is False
    demoting = "role" in fields and fields["role"] not in (None, "admin")

    if (deactivating or demoting) and user.role == "admin" and user.is_active:
        if _other_active_admins(db, user.id) == 0:
            raise ConflictError(
                "This is the only active admin. Promote another admin before "
                "changing this account, or the platform is left with nobody "
                "who can administer it."
            )

    if "is_active" in fields and fields["is_active"] is not None:
        user.is_active = fields["is_active"]
    if "role" in fields and fields["role"] is not None:
        user.role = fields["role"]

    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: uuid.UUID, actor: UserRead) -> None:
    """Remove an account outright.

    Deactivation is the better answer almost every time, and this refuses the
    cases where deleting would destroy something deactivation would not.

    The important one is ownership. `projects.owner_user_id` is `ON DELETE SET
    NULL`, and a project with a null owner is not a project with no owner -- it
    is one that `project_role` can never return a role for, so it becomes
    invisible to every user including admins, with its datasets and runs still
    in the database. Refusing here, and saying how many projects are in the
    way, keeps that from happening quietly.
    """
    user = _get_user_or_404(db, user_id)
    if user.id == actor.id:
        raise BadRequestError("You cannot delete your own account.")

    if user.role == "admin" and user.is_active and _other_active_admins(db, user.id) == 0:
        raise ConflictError(
            "This is the only active admin. Promote another admin before "
            "deleting this account."
        )

    owned = owned_project_count(db, user.id)
    if owned:
        raise ConflictError(
            f"{user.username} still owns {owned} project(s). Deleting the account "
            f"would leave them with no owner, which hides them from everyone "
            f"while their data stays in the database. Deactivate the account "
            f"instead, or move the projects to another owner first."
        )

    db.delete(user)
    db.commit()


def get_preferences(db: Session, user_id: uuid.UUID) -> PreferencesRead:
    """This person's interface settings, or the defaults if they have none.

    Absent preferences are not an error: most people never open the settings
    page, and "system theme, comfortable density" is the right answer for them.
    """
    row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if row is None:
        return PreferencesRead()
    return PreferencesRead.model_validate(row)


def set_preferences(
    db: Session, user_id: uuid.UUID, payload: PreferencesUpdate
) -> PreferencesRead:
    """Apply a partial update, creating the row on first use.

    Only fields the caller actually sent are touched -- a client saving the
    theme must not silently reset the density to its default.
    """
    row = db.scalar(select(UserPreference).where(UserPreference.user_id == user_id))
    if row is None:
        row = UserPreference(user_id=user_id)
        db.add(row)
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return PreferencesRead.model_validate(row)
