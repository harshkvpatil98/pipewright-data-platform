from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import BootstrapUserRequest
from shared_python.auth.security import hash_password, verify_password
from shared_python.errors import ConflictError, UnauthorizedError


def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalar(select(User).where(User.username == username))


def get_user_by_id(db: Session, user_id: uuid.UUID) -> User | None:
    return db.get(User, user_id)


def create_user(db: Session, payload: BootstrapUserRequest) -> User:
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
