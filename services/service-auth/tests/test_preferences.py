"""Per-user interface preferences.

Run against a real SQLite session rather than fakes: the interesting behaviour
here is upsert and partial-update semantics, and a mock would simply agree with
whatever the implementation does.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Importing the gateway's metadata registers every mapper, without which
# SQLAlchemy cannot resolve the relationships between services.
import api_gateway.metadata  # noqa: F401
from service_auth.models import User, UserPreference
from service_auth.schemas import PreferencesUpdate
from service_auth.service import get_preferences, set_preferences
from shared_python.db import Base


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
    row = User(username="analyst", password_hash="x", role="viewer", is_active=True)
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def test_defaults_when_nothing_saved(db: Session, user: User) -> None:
    """Most people never open settings; that is not an error state."""
    prefs = get_preferences(db, user.id)
    assert prefs.theme == "system"
    assert prefs.density == "comfortable"


def test_system_is_the_default_theme(db: Session, user: User) -> None:
    # Not "light" and not "dark": only "system" stays correct when someone
    # changes their operating system appearance setting.
    assert get_preferences(db, user.id).theme == "system"


def test_first_save_creates_the_row(db: Session, user: User) -> None:
    saved = set_preferences(db, user.id, PreferencesUpdate(theme="dark"))
    assert saved.theme == "dark"
    assert db.query(UserPreference).count() == 1


def test_second_save_updates_rather_than_duplicating(db: Session, user: User) -> None:
    set_preferences(db, user.id, PreferencesUpdate(theme="dark"))
    set_preferences(db, user.id, PreferencesUpdate(theme="light"))
    assert db.query(UserPreference).count() == 1
    assert get_preferences(db, user.id).theme == "light"


def test_partial_update_leaves_other_fields_alone(db: Session, user: User) -> None:
    """A client saving only the theme must not reset the density."""
    set_preferences(db, user.id, PreferencesUpdate(theme="dark", density="dense"))
    set_preferences(db, user.id, PreferencesUpdate(theme="light"))

    prefs = get_preferences(db, user.id)
    assert prefs.theme == "light"
    assert prefs.density == "dense"


def test_explicit_none_is_treated_as_absent(db: Session, user: User) -> None:
    # `PreferencesUpdate(theme=None)` means "not changing the theme", not
    # "reset the theme" -- otherwise a client serialising all fields wipes
    # everything it did not mean to touch.
    set_preferences(db, user.id, PreferencesUpdate(density="compact"))
    set_preferences(db, user.id, PreferencesUpdate(theme=None, density="dense"))

    prefs = get_preferences(db, user.id)
    assert prefs.density == "dense"
    assert prefs.theme == "system"


def test_preferences_are_per_user(db: Session, user: User) -> None:
    other = User(username="second", password_hash="x", role="viewer", is_active=True)
    db.add(other)
    db.commit()
    db.refresh(other)

    set_preferences(db, user.id, PreferencesUpdate(theme="dark"))

    assert get_preferences(db, user.id).theme == "dark"
    assert get_preferences(db, other.id).theme == "system"


@pytest.mark.parametrize("theme", ["light", "dark", "system"])
def test_every_theme_round_trips(db: Session, user: User, theme: str) -> None:
    assert set_preferences(db, user.id, PreferencesUpdate(theme=theme)).theme == theme


@pytest.mark.parametrize("density", ["comfortable", "compact", "dense"])
def test_every_density_round_trips(db: Session, user: User, density: str) -> None:
    saved = set_preferences(db, user.id, PreferencesUpdate(density=density))
    assert saved.density == density


def test_invalid_theme_is_rejected_by_the_schema() -> None:
    """Validation belongs at the edge; the column should never see a bad value."""
    with pytest.raises(ValueError):
        PreferencesUpdate(theme="solarized")
