"""Offboarding an account, and the ways doing it could lock the platform.

`is_active` was read on every login and every authenticated request, and set to
`True` at creation and never again -- an enforcement mechanism with no trigger.
An account, once created, could not be withdrawn by any means the API offered.

Most of what follows is about what these two operations refuse. Deactivating
the last admin, or deleting a user who still owns projects, are both one
request away from an install nobody can reach, and neither looks destructive at
the moment it is made.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - imports every model onto one Base
from service_auth.models import User
from service_auth.schemas import UserRead, UserUpdateRequest
from service_auth.service import authenticate_user, delete_user, update_user
from service_projects.models import Project
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.errors import (
    BadRequestError,
    ConflictError,
    NotFoundError,
    UnauthorizedError,
)


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")

    @event.listens_for(engine, "connect")
    def _enforce_foreign_keys(connection, _record):  # noqa: ANN001
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _user(db: Session, username: str, role: str = "viewer", *, active: bool = True) -> User:
    row = User(
        username=username,
        password_hash=hash_password("correct horse battery"),
        role=role,
        is_active=active,
    )
    db.add(row)
    db.flush()
    return row


def _read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role=user.role, is_active=user.is_active,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def world(db: Session) -> dict:
    admin = _user(db, "admin", "admin")
    second_admin = _user(db, "second-admin", "admin")
    analyst = _user(db, "analyst", "viewer")
    db.commit()
    return {"admin": admin, "second_admin": second_admin, "analyst": analyst}


# -------------------------------------------------------------- deactivating


def test_an_account_can_be_deactivated(db: Session, world: dict):
    updated = update_user(
        db, world["analyst"].id, UserUpdateRequest(is_active=False), _read(world["admin"])
    )
    assert updated.is_active is False


def test_a_deactivated_account_can_no_longer_sign_in(db: Session, world: dict):
    """The whole point: the flag was always enforced, just never settable."""
    assert authenticate_user(db, "analyst", "correct horse battery") is not None

    update_user(
        db, world["analyst"].id, UserUpdateRequest(is_active=False), _read(world["admin"])
    )

    with pytest.raises(UnauthorizedError):
        authenticate_user(db, "analyst", "correct horse battery")


def test_a_deactivated_account_can_be_restored(db: Session, world: dict):
    """Offboarding has to be reversible; people come back, and people fat-finger."""
    admin = _read(world["admin"])
    update_user(db, world["analyst"].id, UserUpdateRequest(is_active=False), admin)
    update_user(db, world["analyst"].id, UserUpdateRequest(is_active=True), admin)
    assert authenticate_user(db, "analyst", "correct horse battery") is not None


def test_a_platform_role_can_be_changed(db: Session, world: dict):
    updated = update_user(
        db, world["analyst"].id, UserUpdateRequest(role="admin"), _read(world["admin"])
    )
    assert updated.role == "admin"


def test_changing_the_role_leaves_the_account_active(db: Session, world: dict):
    """`exclude_unset` again: a promotion must not switch the account off."""
    updated = update_user(
        db, world["analyst"].id, UserUpdateRequest(role="operator"), _read(world["admin"])
    )
    assert updated.is_active is True


def test_you_cannot_deactivate_yourself(db: Session, world: dict):
    """Signing yourself out with no way back is never what was meant."""
    with pytest.raises(BadRequestError):
        update_user(
            db, world["admin"].id, UserUpdateRequest(is_active=False), _read(world["admin"])
        )


def test_the_last_active_admin_cannot_be_deactivated(db: Session, world: dict):
    """An install with no admin has no way to appoint one."""
    admin = _read(world["admin"])
    update_user(db, world["second_admin"].id, UserUpdateRequest(is_active=False), admin)

    # `admin` is now the only active admin, and the second admin's account is
    # the one left to act through.
    with pytest.raises(ConflictError, match="only active admin"):
        update_user(
            db, world["admin"].id, UserUpdateRequest(is_active=False),
            _read(world["second_admin"]),
        )


def test_the_last_active_admin_cannot_be_demoted(db: Session, world: dict):
    """The path that does not look destructive, and locks the platform anyway."""
    admin = _read(world["admin"])
    update_user(db, world["second_admin"].id, UserUpdateRequest(is_active=False), admin)

    with pytest.raises(ConflictError, match="only active admin"):
        update_user(
            db, world["admin"].id, UserUpdateRequest(role="viewer"),
            _read(world["second_admin"]),
        )


def test_an_admin_can_be_deactivated_while_another_remains(db: Session, world: dict):
    """The guard is about the last one, not about admins in general."""
    updated = update_user(
        db, world["second_admin"].id, UserUpdateRequest(is_active=False),
        _read(world["admin"]),
    )
    assert updated.is_active is False


def test_updating_an_account_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        update_user(
            db, uuid.uuid4(), UserUpdateRequest(is_active=False), _read(world["admin"])
        )


# ----------------------------------------------------------------- deleting


def test_an_account_can_be_deleted(db: Session, world: dict):
    delete_user(db, world["analyst"].id, _read(world["admin"]))
    assert db.get(User, world["analyst"].id) is None


def test_you_cannot_delete_yourself(db: Session, world: dict):
    with pytest.raises(BadRequestError):
        delete_user(db, world["admin"].id, _read(world["admin"]))


def test_a_user_who_owns_projects_cannot_be_deleted(db: Session, world: dict):
    """The failure this refusal exists to prevent.

    `projects.owner_user_id` is `ON DELETE SET NULL`, and `project_role` can
    never return a role for a project whose owner is null. Deleting the owner
    would leave the project in the database and reachable by nobody -- not its
    members, not an admin. Deactivating keeps ownership intact, which is why
    the message points there.
    """
    db.add(Project(
        name="Revenue", slug="revenue", owner_user_id=world["analyst"].id, status="active",
    ))
    db.commit()

    with pytest.raises(ConflictError, match="still owns 1 project"):
        delete_user(db, world["analyst"].id, _read(world["admin"]))

    assert db.get(User, world["analyst"].id) is not None


def test_a_user_can_be_deleted_once_their_projects_are_gone(db: Session, world: dict):
    project = Project(
        name="Revenue", slug="revenue", owner_user_id=world["analyst"].id, status="active",
    )
    db.add(project)
    db.commit()
    db.delete(project)
    db.commit()

    delete_user(db, world["analyst"].id, _read(world["admin"]))
    assert db.get(User, world["analyst"].id) is None


def test_the_last_active_admin_cannot_be_deleted(db: Session, world: dict):
    admin = _read(world["admin"])
    update_user(db, world["second_admin"].id, UserUpdateRequest(is_active=False), admin)

    with pytest.raises(ConflictError, match="only active admin"):
        delete_user(db, world["admin"].id, _read(world["second_admin"]))


def test_deleting_an_account_that_does_not_exist_is_a_404(db: Session, world: dict):
    with pytest.raises(NotFoundError):
        delete_user(db, uuid.uuid4(), _read(world["admin"]))
