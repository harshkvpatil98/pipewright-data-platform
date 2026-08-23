"""Version history, and the rollback it exists for."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.orm import Session

from collections.abc import Iterator
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from service_auth.models import User
from service_auth.schemas import UserRead
from service_governance import versions as version_ops
from service_governance.models import ResourceVersion
from service_governance.schemas import RestoreRequest
from service_governance.service import (
    diff_resource_versions,
    get_resource_version,
    list_resource_versions,
    restore_resource_version,
)
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError, NotFoundError

RESOURCE_ID = uuid.UUID("77777777-7777-7777-7777-777777777777")
TYPE = "workflow"


@pytest.fixture()
def live_store() -> dict:
    """Stands in for the real resource a restorer would write to."""
    return {}


@pytest.fixture(autouse=True)
def registered(live_store: dict):
    """Stand in for the real workflow snapshotter for the length of a test.

    The resource type has to be a real one -- the response contract only admits
    the types the platform actually versions -- so the genuine registration is
    put back afterwards rather than deleted.
    """

    def snapshotter(_db, _project_id, resource_id):
        return live_store.get(resource_id)

    def restorer(_db, _project_id, resource_id, snapshot, _actor):
        live_store[resource_id] = dict(snapshot)

    previous_snapshotter = version_ops._snapshotters.get(TYPE)
    previous_restorer = version_ops._restorers.get(TYPE)
    version_ops.register_snapshotter(TYPE, snapshotter)
    version_ops.register_restorer(TYPE, restorer)
    yield
    if previous_snapshotter is not None:
        version_ops.register_snapshotter(TYPE, previous_snapshotter)
    if previous_restorer is not None:
        version_ops.register_restorer(TYPE, previous_restorer)


def _record(db: Session, project: Project, snapshot: dict, actor: User | None = None):
    return version_ops.record_version(
        db,
        project_id=project.id,
        resource_type=TYPE,
        resource_id=RESOURCE_ID,
        name="Widget",
        snapshot=snapshot,
        actor_user_id=actor.id if actor else None,
    )


def test_the_first_version_is_numbered_one_and_says_created(db: Session, project: Project):
    version = _record(db, project, {"name": "a"})
    assert version is not None
    assert version.version == 1
    assert version.change_summary == "Created."


def test_versions_increment(db: Session, project: Project):
    _record(db, project, {"name": "a"})
    second = _record(db, project, {"name": "b"})
    assert second is not None
    assert second.version == 2


def test_saving_without_changing_anything_records_nothing(db: Session, project: Project):
    """A form saved untouched must not fill the history with identical rows."""
    _record(db, project, {"name": "a"})
    assert _record(db, project, {"name": "a"}) is None
    assert db.query(ResourceVersion).count() == 1


def test_the_summary_describes_what_changed(db: Session, project: Project):
    _record(db, project, {"name": "a", "enabled": True})
    second = _record(db, project, {"name": "b", "enabled": True})
    assert second is not None
    assert "name" in second.change_summary


def test_history_comes_back_newest_first(db: Session, project: Project, owner: User):
    for name in ("a", "b", "c"):
        _record(db, project, {"name": name}, owner)
    db.commit()

    listing = list_resource_versions(db, project.id, TYPE, RESOURCE_ID, as_read(owner))
    assert [item.version for item in listing.items] == [3, 2, 1]
    assert listing.items[0].created_by_username == "owner"


def test_a_version_can_be_read_back_whole(db: Session, project: Project, owner: User):
    _record(db, project, {"name": "a", "nested": {"x": 1}}, owner)
    db.commit()
    detail = get_resource_version(db, project.id, TYPE, RESOURCE_ID, 1, as_read(owner))
    assert detail.snapshot_json == {"name": "a", "nested": {"x": 1}}


def test_a_version_that_does_not_exist_is_a_404(db: Session, project: Project, owner: User):
    with pytest.raises(NotFoundError):
        get_resource_version(db, project.id, TYPE, RESOURCE_ID, 9, as_read(owner))


def test_two_versions_can_be_compared(db: Session, project: Project, owner: User):
    _record(db, project, {"name": "a"}, owner)
    _record(db, project, {"name": "b"}, owner)
    db.commit()

    response = diff_resource_versions(db, project.id, TYPE, RESOURCE_ID, 1, 2, as_read(owner))
    assert response.diff.identical is False
    assert response.diff.changes[0].before == "a"
    assert response.diff.changes[0].after == "b"


def test_comparing_a_version_with_itself_is_refused(db: Session, project: Project, owner: User):
    _record(db, project, {"name": "a"}, owner)
    db.commit()
    with pytest.raises(BadRequestError):
        diff_resource_versions(db, project.id, TYPE, RESOURCE_ID, 1, 1, as_read(owner))


def test_restoring_writes_the_old_snapshot_back_to_the_live_resource(
    db: Session, project: Project, owner: User, live_store: dict
):
    _record(db, project, {"name": "original"}, owner)
    _record(db, project, {"name": "broken"}, owner)
    db.commit()

    restore_resource_version(
        db, project.id, TYPE, RESOURCE_ID, RestoreRequest(version=1), as_read(owner)
    )
    assert live_store[RESOURCE_ID] == {"name": "original"}


def test_restoring_moves_history_forward_rather_than_truncating_it(
    db: Session, project: Project, owner: User
):
    """The rollback is itself an edit; erasing what it undid loses the record."""
    _record(db, project, {"name": "original"}, owner)
    _record(db, project, {"name": "broken"}, owner)
    db.commit()

    response = restore_resource_version(
        db, project.id, TYPE, RESOURCE_ID, RestoreRequest(version=1), as_read(owner)
    )
    assert response.new_version == 3
    assert db.query(ResourceVersion).count() == 3

    newest = version_ops.latest_version(db, TYPE, RESOURCE_ID)
    assert newest is not None
    assert newest.restored_from_version == 1
    assert newest.snapshot_json == {"name": "original"}


def test_restoring_the_current_version_is_refused(db: Session, project: Project, owner: User):
    _record(db, project, {"name": "a"}, owner)
    db.commit()
    with pytest.raises(BadRequestError) as caught:
        restore_resource_version(
            db, project.id, TYPE, RESOURCE_ID, RestoreRequest(version=1), as_read(owner)
        )
    assert "already the current version" in str(caught.value.detail)


def test_a_type_nobody_registered_cannot_be_restored(db: Session, project: Project, owner: User):
    version_ops.record_version(
        db,
        project_id=project.id,
        resource_type="quality_rule",
        resource_id=RESOURCE_ID,
        name="Mystery",
        snapshot={"name": "a"},
    )
    version_ops.record_version(
        db,
        project_id=project.id,
        resource_type="quality_rule",
        resource_id=RESOURCE_ID,
        name="Mystery",
        snapshot={"name": "b"},
    )
    db.commit()

    with pytest.raises(BadRequestError) as caught:
        restore_resource_version(
            db, project.id, "quality_rule", RESOURCE_ID, RestoreRequest(version=1), as_read(owner)
        )
    assert "cannot be restored automatically" in str(caught.value.detail)


def test_history_is_scoped_to_its_project(db: Session, project: Project, owner: User):
    _record(db, project, {"name": "a"}, owner)
    other = Project(name="Other", slug="other", owner_user_id=owner.id, status="active")
    db.add(other)
    db.commit()

    assert list_resource_versions(db, other.id, TYPE, RESOURCE_ID, as_read(owner)).items == []


# Fixtures live in the module rather than a shared conftest: this suite runs
# with `--import-mode=importlib` and no `__init__.py`, so two conftest.py files
# in different service directories collide on module name and one silently
# supplies the other's fixtures.


@pytest.fixture()
def db() -> Iterator[Session]:
    import api_gateway.metadata  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def make_user(db: Session, username: str) -> User:
    row = User(username=username, password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.flush()
    return row


def as_read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def owner(db: Session) -> User:
    return make_user(db, "owner")


@pytest.fixture()
def reviewer(db: Session) -> User:
    return make_user(db, "reviewer")


@pytest.fixture()
def project(db: Session, owner: User) -> Project:
    row = Project(name="Ops", slug="ops", owner_user_id=owner.id, status="active")
    db.add(row)
    db.commit()
    return row
