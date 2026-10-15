"""The first administrator on a new installation (adoption-readiness A9).

The settings for it were in every example file and the Helm chart, and
nothing read them, so a new installation had nobody who could sign in.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway.first_run import ensure_first_administrator
from service_auth.models import User
from shared_python.auth.security import verify_password
from shared_python.db import Base


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_a_new_installation_gets_its_administrator_once(db: Session) -> None:
    assert ensure_first_administrator(db, username="Admin", password="a-long-enough-password") == "admin"
    [user] = db.scalars(select(User)).all()
    assert (user.username, user.role) == ("admin", "admin")
    assert verify_password("a-long-enough-password", user.password_hash)
    # With an account there, the settings open nothing again.
    assert ensure_first_administrator(db, username="other", password="another-long-password") is None
    assert len(db.scalars(select(User)).all()) == 1


def test_nothing_is_made_without_both_settings_or_with_a_short_password(db: Session) -> None:
    assert ensure_first_administrator(db, username="admin", password=None) is None
    assert ensure_first_administrator(db, username="", password="a-long-enough-password") is None
    assert ensure_first_administrator(db, username="admin", password="short") is None
    assert db.scalars(select(User)).all() == []
