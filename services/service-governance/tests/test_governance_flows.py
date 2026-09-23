"""Approvals, the audit log, and comments."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

import api_gateway.metadata  # noqa: F401
import service_access  # noqa: F401  - registers the membership resolver
from service_access.models import ProjectMembership
from service_auth.models import User
from service_auth.schemas import UserRead
from service_governance import versions as version_ops
from service_governance.audit import (
    describe_action,
    outcome_for,
    project_id_from,
    resource_hint,
)
from service_governance.models import AuditEntry, Comment, ResourceVersion
from service_governance.schemas import (
    ChangeRequestCreate,
    ChangeRequestReview,
    CommentCreate,
)
from service_governance.service import (
    add_comment,
    approve_change,
    extract_mentions,
    get_change_request,
    list_audit_entries,
    list_change_requests,
    list_comments,
    propose_change,
    reject_change,
    resolve_comment,
    withdraw_change,
)
from service_notifications.models import UserNotification
from service_projects.models import Project
from shared_python.db import Base
from shared_python.errors import BadRequestError

RESOURCE_ID = uuid.UUID("abcdabcd-1111-2222-3333-abcdabcdabcd")
TYPE = "workflow"


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


def _make_user(db: Session, username: str) -> User:
    row = User(username=username, password_hash="x", role="admin", is_active=True)
    db.add(row)
    db.flush()
    return row


def _as_read(user: User) -> UserRead:
    now = datetime.now(UTC)
    return UserRead(
        id=user.id, username=user.username, role="admin", is_active=True,
        created_at=now, updated_at=now,
    )


@pytest.fixture()
def world(db: Session) -> dict:
    author = _make_user(db, "author")
    reviewer = _make_user(db, "reviewer")
    project = Project(name="Ops", slug="ops", owner_user_id=author.id, status="active")
    db.add(project)
    db.flush()
    # The reviewer is a second person on the project. Without a membership they
    # cannot see it at all, which is the access control doing its job.
    db.add(
        ProjectMembership(project_id=project.id, user_id=reviewer.id, role="admin")
    )
    db.commit()
    return {"author": author, "reviewer": reviewer, "project": project}


@pytest.fixture()
def live_store() -> dict:
    return {}


@pytest.fixture(autouse=True)
def registered(live_store: dict):
    def snapshotter(_db, _project_id, resource_id):
        return live_store.get(resource_id)

    def restorer(_db, _project_id, resource_id, snapshot, _actor):
        live_store[resource_id] = dict(snapshot)

    previous_snap = version_ops._snapshotters.get(TYPE)
    previous_restore = version_ops._restorers.get(TYPE)
    version_ops.register_snapshotter(TYPE, snapshotter)
    version_ops.register_restorer(TYPE, restorer)
    yield
    if previous_snap is not None:
        version_ops.register_snapshotter(TYPE, previous_snap)
    if previous_restore is not None:
        version_ops.register_restorer(TYPE, previous_restore)


def _propose(db: Session, world: dict, after: dict):
    return propose_change(
        db,
        world["project"].id,
        ChangeRequestCreate(
            resource_type=TYPE,
            resource_id=RESOURCE_ID,
            title="Add a quality gate",
            description="Stops bad rows reaching the warehouse.",
            after_json=after,
        ),
        _as_read(world["author"]),
    )


# ---- change requests ----


def test_a_proposal_carries_a_diff_against_what_is_live(
    db: Session, world: dict, live_store: dict
):
    live_store[RESOURCE_ID] = {"name": "Nightly", "nodes": []}
    change = _propose(db, world, {"name": "Nightly", "nodes": [{"node_key": "gate"}]})

    assert change.status == "open"
    assert change.diff.identical is False
    assert "nodes" in change.change_summary


def test_a_proposal_that_changes_nothing_is_refused(db: Session, world: dict, live_store: dict):
    live_store[RESOURCE_ID] = {"name": "Nightly"}
    with pytest.raises(BadRequestError) as caught:
        _propose(db, world, {"name": "Nightly"})
    assert "does not change anything" in str(caught.value.detail)


def test_approving_applies_the_change_and_records_a_version(
    db: Session, world: dict, live_store: dict
):
    live_store[RESOURCE_ID] = {"name": "Nightly", "nodes": []}
    change = _propose(db, world, {"name": "Nightly", "nodes": [{"node_key": "gate"}]})

    approved = approve_change(
        db,
        world["project"].id,
        change.id,
        ChangeRequestReview(note="Looks right"),
        _as_read(world["reviewer"]),
    )

    assert approved.status == "approved"
    assert approved.reviewed_by_username == "reviewer"
    assert live_store[RESOURCE_ID]["nodes"] == [{"node_key": "gate"}]

    version = db.query(ResourceVersion).one()
    # The version is credited to whoever proposed it, not whoever clicked approve.
    assert version.created_by_user_id == world["author"].id


def test_you_cannot_approve_your_own_change(db: Session, world: dict, live_store: dict):
    """A review with one pair of eyes is not a review."""
    live_store[RESOURCE_ID] = {"name": "Nightly"}
    change = _propose(db, world, {"name": "Nightly v2"})

    with pytest.raises(BadRequestError) as caught:
        approve_change(
            db, world["project"].id, change.id, ChangeRequestReview(), _as_read(world["author"])
        )
    assert "your own change" in str(caught.value.detail)


def test_a_rejected_change_is_not_applied(db: Session, world: dict, live_store: dict):
    live_store[RESOURCE_ID] = {"name": "Nightly"}
    change = _propose(db, world, {"name": "Nightly v2"})

    rejected = reject_change(
        db,
        world["project"].id,
        change.id,
        ChangeRequestReview(note="Not now"),
        _as_read(world["reviewer"]),
    )
    assert rejected.status == "rejected"
    assert live_store[RESOURCE_ID] == {"name": "Nightly"}
    assert db.query(ResourceVersion).count() == 0


def test_a_change_can_only_be_reviewed_once(db: Session, world: dict, live_store: dict):
    live_store[RESOURCE_ID] = {"name": "Nightly"}
    change = _propose(db, world, {"name": "Nightly v2"})
    reject_change(
        db, world["project"].id, change.id, ChangeRequestReview(), _as_read(world["reviewer"])
    )
    with pytest.raises(BadRequestError) as caught:
        approve_change(
            db, world["project"].id, change.id, ChangeRequestReview(), _as_read(world["reviewer"])
        )
    assert "already rejected" in str(caught.value.detail)


def test_only_the_proposer_can_withdraw(db: Session, world: dict, live_store: dict):
    live_store[RESOURCE_ID] = {"name": "Nightly"}
    change = _propose(db, world, {"name": "Nightly v2"})

    with pytest.raises(BadRequestError):
        withdraw_change(db, world["project"].id, change.id, _as_read(world["reviewer"]))

    withdrawn = withdraw_change(db, world["project"].id, change.id, _as_read(world["author"]))
    assert withdrawn.status == "withdrawn"


def test_the_change_list_counts_what_is_waiting(db: Session, world: dict, live_store: dict):
    live_store[RESOURCE_ID] = {"name": "Nightly"}
    _propose(db, world, {"name": "Nightly v2"})
    listing = list_change_requests(db, world["project"].id, _as_read(world["author"]))
    assert listing.open_count == 1
    assert listing.items[0].requested_by_username == "author"


def test_a_change_detail_shows_both_sides(db: Session, world: dict, live_store: dict):
    live_store[RESOURCE_ID] = {"name": "Nightly"}
    change = _propose(db, world, {"name": "Nightly v2"})
    detail = get_change_request(db, world["project"].id, change.id, _as_read(world["author"]))
    assert detail.before_json == {"name": "Nightly"}
    assert detail.after_json == {"name": "Nightly v2"}


# ---- audit log ----


def test_the_audit_action_reads_like_a_phrase():
    assert (
        describe_action("POST", "/api/v1/projects/11111111-1111-1111-1111-111111111111/workflows")
        == "create workflow"
    )
    assert (
        describe_action(
            "DELETE",
            "/api/v1/projects/11111111-1111-1111-1111-111111111111/datasets/22222222-2222-2222-2222-222222222222",
        )
        == "delete dataset"
    )
    assert (
        describe_action(
            "POST",
            "/api/v1/projects/11111111-1111-1111-1111-111111111111/workflows/22222222-2222-2222-2222-222222222222/run",
        )
        == "run workflow"
    )


def test_writeback_actions_name_what_happened():
    """"create commit" is both wrong and unsearchable."""
    project = "11111111-1111-1111-1111-111111111111"
    change_set = "22222222-2222-2222-2222-222222222222"
    base = f"/api/v1/projects/{project}/writeback/change-sets/{change_set}"
    assert describe_action("POST", f"{base}/commit") == "commit change-set"
    assert describe_action("POST", f"{base}/discard") == "discard change-set"
    assert describe_action("POST", f"{base}/plan") == "plan change-set"
    # And the entry points at the change set, which is where the SQL is kept.
    assert resource_hint(f"{base}/commit") == ("change-set", change_set)


def test_identifiers_are_stripped_so_actions_group():
    first = describe_action("PATCH", "/api/v1/projects/11111111-1111-1111-1111-111111111111/workflows/22222222-2222-2222-2222-222222222222")
    second = describe_action("PATCH", "/api/v1/projects/33333333-3333-3333-3333-333333333333/workflows/44444444-4444-4444-4444-444444444444")
    assert first == second == "update workflow"


def test_the_project_is_read_out_of_the_path():
    path = "/api/v1/projects/11111111-1111-1111-1111-111111111111/workflows"
    assert project_id_from(path) == uuid.UUID("11111111-1111-1111-1111-111111111111")
    assert project_id_from("/api/v1/auth/login") is None


def test_the_resource_kind_and_id_come_from_the_path():
    kind, resource_id = resource_hint(
        "/api/v1/projects/11111111-1111-1111-1111-111111111111/workflows/22222222-2222-2222-2222-222222222222/run"
    )
    assert kind == "workflow"
    assert resource_id == "22222222-2222-2222-2222-222222222222"


def test_a_refusal_is_recorded_as_denied_not_failed():
    """Denied and failed are different questions someone asks the log."""
    assert outcome_for(403) == "denied"
    assert outcome_for(401) == "denied"
    assert outcome_for(500) == "failed"
    assert outcome_for(422) == "failed"
    assert outcome_for(201) == "succeeded"


def test_the_audit_log_can_be_filtered_by_outcome(db: Session, world: dict):
    for status_code, outcome in ((201, "succeeded"), (403, "denied")):
        db.add(
            AuditEntry(
                project_id=world["project"].id,
                actor_user_id=world["author"].id,
                actor_username="author",
                method="POST",
                path="/api/v1/projects/x/workflows",
                action="create workflow",
                status_code=status_code,
                outcome=outcome,
            )
        )
    db.commit()

    everything = list_audit_entries(db, world["project"].id, _as_read(world["author"]))
    denied = list_audit_entries(
        db, world["project"].id, _as_read(world["author"]), outcome="denied"
    )
    assert len(everything.items) == 2
    assert [item.status_code for item in denied.items] == [403]


# ---- comments ----


def test_mentions_are_parsed_out_of_the_body():
    assert extract_mentions("hey @alice and @Bob") == ["alice", "bob"]
    assert extract_mentions("no mentions here") == []
    assert extract_mentions("@alice @alice") == ["alice"]
    assert extract_mentions("email me at name@example.com") == ["example.com"]


def test_a_comment_records_its_author_and_mentions(db: Session, world: dict):
    comment = add_comment(
        db,
        world["project"].id,
        CommentCreate(target_type="dataset", target_id=RESOURCE_ID, body="@reviewer take a look"),
        _as_read(world["author"]),
    )
    assert comment.author_username == "author"
    assert comment.mentions == ["reviewer"]


def test_a_mention_notifies_the_person_named(db: Session, world: dict):
    add_comment(
        db,
        world["project"].id,
        CommentCreate(target_type="dataset", target_id=RESOURCE_ID, body="@reviewer take a look"),
        _as_read(world["author"]),
    )
    notification = db.query(UserNotification).one()
    assert notification.user_id == world["reviewer"].id
    assert notification.type == "mention"


def test_a_mention_notification_points_at_the_thing_discussed(db: Session, world: dict):
    add_comment(
        db,
        world["project"].id,
        CommentCreate(target_type="dataset", target_id=RESOURCE_ID, body="@reviewer see this"),
        _as_read(world["author"]),
    )
    notification = db.query(UserNotification).one()
    assert notification.related_dataset_id == RESOURCE_ID
    assert notification.title == "author mentioned you on a dataset"


def test_dashboards_and_charts_can_be_discussed(db: Session, world: dict):
    for target_type in ("dashboard", "chart"):
        comment = add_comment(
            db,
            world["project"].id,
            CommentCreate(target_type=target_type, target_id=RESOURCE_ID, body="looks off"),
            _as_read(world["author"]),
        )
        assert comment.target_type == target_type


def test_mentioning_yourself_is_not_news(db: Session, world: dict):
    add_comment(
        db,
        world["project"].id,
        CommentCreate(target_type="dataset", target_id=RESOURCE_ID, body="note to self @author"),
        _as_read(world["author"]),
    )
    assert db.query(UserNotification).count() == 0


def test_comments_come_back_oldest_first_per_target(db: Session, world: dict):
    for body in ("first", "second"):
        add_comment(
            db,
            world["project"].id,
            CommentCreate(target_type="dataset", target_id=RESOURCE_ID, body=body),
            _as_read(world["author"]),
        )
    other_target = uuid.uuid4()
    add_comment(
        db,
        world["project"].id,
        CommentCreate(target_type="dataset", target_id=other_target, body="elsewhere"),
        _as_read(world["author"]),
    )

    listing = list_comments(
        db, world["project"].id, "dataset", RESOURCE_ID, _as_read(world["author"])
    )
    assert [item.body for item in listing.items] == ["first", "second"]
    assert listing.open_count == 2


def test_resolving_a_comment_closes_the_thread(db: Session, world: dict):
    comment = add_comment(
        db,
        world["project"].id,
        CommentCreate(target_type="run", target_id=RESOURCE_ID, body="why did this fail?"),
        _as_read(world["author"]),
    )
    resolved = resolve_comment(
        db, world["project"].id, comment.id, _as_read(world["reviewer"])
    )
    assert resolved.resolved_at is not None

    listing = list_comments(db, world["project"].id, "run", RESOURCE_ID, _as_read(world["author"]))
    assert listing.open_count == 0


def test_an_empty_comment_is_refused(db: Session, world: dict):
    with pytest.raises(BadRequestError):
        add_comment(
            db,
            world["project"].id,
            CommentCreate(target_type="dataset", target_id=RESOURCE_ID, body="   "),
            _as_read(world["author"]),
        )


def test_a_comment_survives_a_notification_failure(db: Session, world: dict, monkeypatch):
    import service_notifications.service as notifications

    monkeypatch.setattr(
        notifications, "create_user_notification", lambda *a, **k: (_ for _ in ()).throw(RuntimeError())
    )
    add_comment(
        db,
        world["project"].id,
        CommentCreate(target_type="dataset", target_id=RESOURCE_ID, body="@reviewer look"),
        _as_read(world["author"]),
    )
    assert db.query(Comment).count() == 1


def test_trailing_verbs_read_as_the_action_not_a_creation():
    """'create restore' is not a thing anybody did."""
    base = "/api/v1/projects/11111111-1111-1111-1111-111111111111"
    workflow = "22222222-2222-2222-2222-222222222222"
    assert describe_action("POST", f"{base}/history/workflow/{workflow}/restore") == "restore workflow"
    assert describe_action("POST", f"{base}/changes/{workflow}/approve") == "approve change"
    assert describe_action("POST", f"{base}/promote") == "promote project"


def test_a_change_request_can_be_commented_on(db: Session, world: dict):
    """The Approvals UX asks for changes by commenting on the proposal itself,
    so change_request must be a valid comment target alongside datasets et al."""
    change_id = uuid.uuid4()
    add_comment(
        db,
        world["project"].id,
        CommentCreate(
            target_type="change_request",
            target_id=change_id,
            body="Please rename the step before I approve.",
        ),
        _as_read(world["reviewer"]),
    )
    listing = list_comments(
        db, world["project"].id, "change_request", change_id, _as_read(world["author"])
    )
    assert len(listing.items) == 1
    assert listing.items[0].body.startswith("Please rename")
    assert listing.items[0].author_username == "reviewer"
