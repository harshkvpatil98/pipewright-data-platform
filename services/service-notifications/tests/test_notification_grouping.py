"""Notifications arrive the way a person asked: each, as a daily summary, or not at all.

Run against a real (SQLite) database, because the behaviour is in the queries:
which existing row an event folds into, and when it starts a new one.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401  - registers every service's tables
from service_auth.models import User
from service_notifications.models import UserNotification
from service_notifications.preferences import all_modes, category_for, set_mode
from service_notifications.service import create_user_notification, mark_notification_read
from service_auth.schemas import UserRead
from shared_python.db import Base
from shared_python.errors import BadRequestError


@pytest.fixture()
def db() -> Iterator[Session]:
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def user(db: Session) -> User:
    row = User(username="ops", password_hash="x", role="user", is_active=True)
    db.add(row)
    db.commit()
    return row


def _rows(db: Session, user: User) -> list[UserNotification]:
    return list(db.scalars(select(UserNotification).where(UserNotification.user_id == user.id)))


def _notify(db: Session, user: User, **overrides):
    values = dict(
        user_id=user.id,
        project_id=None,
        type="schedule_run_succeeded",
        level="success",
        title="Daily refresh finished",
        message="All good.",
    )
    values.update(overrides)
    return create_user_notification(db, **values)


def test_routine_successes_become_one_running_summary(db: Session, user: User) -> None:
    for _ in range(3):
        _notify(db, user)
    rows = _rows(db, user)
    assert len(rows) == 1
    assert rows[0].group_count == 3
    assert rows[0].title == "3 runs finished without problems today"
    assert rows[0].message.startswith("Latest: Daily refresh finished.")


def test_repeated_failures_of_one_schedule_fold_together(db: Session, user: User) -> None:
    schedule = uuid.uuid4()
    for attempt in range(2):
        _notify(
            db, user, type="schedule_run_failed", level="error",
            title="Daily refresh failed", message=f"attempt {attempt}",
            related_schedule_id=schedule,
        )
    rows = _rows(db, user)
    assert len(rows) == 1
    assert rows[0].group_count == 2
    assert rows[0].message == "attempt 1"  # the latest, not the first


def test_a_failure_after_the_first_was_read_is_news_again(db: Session, user: User) -> None:
    schedule = uuid.uuid4()
    first = _notify(db, user, type="schedule_run_failed", level="error", related_schedule_id=schedule)
    mark_notification_read(
        db,
        notification_id=first.id,
        current_user=UserRead(
            id=user.id, username=user.username, role="user", is_active=True,
            created_at=user.created_at, updated_at=user.updated_at,
        ),
    )
    _notify(db, user, type="schedule_run_failed", level="error", related_schedule_id=schedule)
    assert len(_rows(db, user)) == 2


def test_failures_about_different_things_stay_separate(db: Session, user: User) -> None:
    _notify(db, user, type="schedule_run_failed", level="error", related_schedule_id=uuid.uuid4())
    _notify(db, user, type="schedule_run_failed", level="error", related_schedule_id=uuid.uuid4())
    _notify(db, user, type="transformation_run_failed", level="error")
    _notify(db, user, type="transformation_run_failed", level="error")
    assert len(_rows(db, user)) == 4


def test_a_category_turned_off_records_nothing(db: Session, user: User) -> None:
    set_mode(db, user.id, "successes", "off")
    assert _notify(db, user) is None
    assert _rows(db, user) == []


def test_choosing_each_for_successes_writes_one_row_per_run(db: Session, user: User) -> None:
    set_mode(db, user.id, "successes", "each")
    _notify(db, user)
    _notify(db, user)
    assert len(_rows(db, user)) == 2


def test_defaults_put_successes_in_a_summary_and_everything_else_one_by_one(db: Session, user: User) -> None:
    modes = all_modes(db, user.id)
    assert modes["successes"] == "digest"
    assert all(mode == "each" for key, mode in modes.items() if key != "successes")


def test_an_unknown_category_or_mode_is_refused(db: Session, user: User) -> None:
    with pytest.raises(BadRequestError):
        set_mode(db, user.id, "gossip", "each")
    with pytest.raises(BadRequestError):
        set_mode(db, user.id, "failures", "sometimes")


@pytest.mark.parametrize(
    ("event_type", "level", "category"),
    [
        ("schedule_run_failed", "error", "failures"),
        ("workflow_run_partial", "warning", "failures"),
        ("transformation_run_succeeded", "success", "successes"),
        ("mention", "info", "mentions"),
        ("incident", "error", "incidents"),
        ("report", "success", "reports"),
        ("workflow", "info", "workflows"),
    ],
)
def test_every_event_type_has_a_category(event_type: str, level: str, category: str) -> None:
    assert category_for(event_type, level) == category
