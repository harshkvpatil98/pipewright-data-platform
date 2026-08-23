from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.models import User, UserPreference
from service_auth.schemas import (
    BootstrapUserRequest,
    PreferencesRead,
    PreferencesUpdate,
    UserCreateRequest,
)
from shared_python.auth.security import hash_password, verify_password
from shared_python.errors import ConflictError, UnauthorizedError


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
