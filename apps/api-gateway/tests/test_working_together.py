"""Working together on a recipe and a dataset, through HTTP (roadmap Phase 21, C2).

The measured defect first: two saves of one recipe from the same starting
point both succeeded and the second silently dropped the first's step. Then
the shared copy two Studios edit at once, suggestions from someone who may
not save, the approval a project can now ask for, who is here, threads on a
cell, and what happened to a dataset.

Runs on SQLite and, where CI provides one, on PostgreSQL in a schema of its
own (see test_data_contracts for why the tables are made from a copy).
"""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import MetaData, create_engine, select, text
from sqlalchemy.orm import sessionmaker

import api_gateway.metadata  # noqa: F401
from api_gateway import dependencies
from api_gateway.dependencies import get_db
from api_gateway.main import app
from service_access.models import ProjectMembership
from service_auth.models import User
from service_governance.audit import is_audited
from service_governance.audit_words import summarise
from service_governance.models import Presence
from service_notifications.models import UserNotification
from shared_python.auth.security import hash_password
from shared_python.db import Base
from shared_python.storage.local import LocalStorageBackend

PASSWORD = "a-long-enough-password"
POSTGRES = os.environ.get("CONNECTORS_TEST_POSTGRES_URL")


def _engine(backend: str, tmp_path):
    if backend == "sqlite":
        return create_engine(f"sqlite:///{tmp_path / 'together.db'}", connect_args={"check_same_thread": False}), None
    if not POSTGRES:
        pytest.skip("Set CONNECTORS_TEST_POSTGRES_URL to run these on PostgreSQL too.")
    schema = f"together_{uuid.uuid4().hex[:12]}"
    admin = create_engine(POSTGRES)
    with admin.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    admin.dispose()
    return create_engine(POSTGRES, connect_args={"options": f"-csearch_path={schema}"}), schema


def _create_tables(engine) -> None:
    if engine.dialect.name == "sqlite":
        Base.metadata.create_all(engine)
        return
    private = MetaData()
    for table in Base.metadata.tables.values():
        table.to_metadata(private)
    private.create_all(engine)


def _client(username: str) -> TestClient:
    client = TestClient(app)
    token = client.post("/api/v1/auth/login", json={"username": username, "password": PASSWORD}).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return client


@pytest.fixture(params=["sqlite", "postgres"])
def world(request, tmp_path, monkeypatch):
    engine, schema = _engine(request.param, tmp_path)
    _create_tables(engine)
    factory = sessionmaker(bind=engine)

    def _db():
        session = factory()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(dependencies, "storage_backend", LocalStorageBackend(str(tmp_path / "storage")))
    monkeypatch.setenv("RATE_LIMITS_ENABLED", "false")
    with factory() as db:
        for username, display in (("ann", "Ann Lee"), ("bob", "Bob"), ("vic", "Vic")):
            db.add(User(username=username, display_name=display, password_hash=hash_password(PASSWORD), role="user", is_active=True))
        db.commit()
    ann = _client("ann")
    project = ann.post("/api/v1/projects", json={"name": "Shop"}).json()["id"]
    with factory() as db:
        ids = {user.username: user.id for user in db.scalars(select(User)).all()}
        db.add(ProjectMembership(project_id=uuid.UUID(project), user_id=ids["bob"], role="editor"))
        db.add(ProjectMembership(project_id=uuid.UUID(project), user_id=ids["vic"], role="viewer"))
        db.commit()
    orders = _ok(ann.post(f"/api/v1/projects/{project}/samples/orders"), 201)["dataset"]
    recipe = _ok(
        ann.post(
            f"/api/v1/projects/{project}/datasets/{orders['id']}/pipelines",
            json={"name": "Clean orders", "steps_json": [{"step_type": "remove_duplicates", "config": {}}]},
        ),
        201,
    )
    yield {
        "ann": ann,
        "bob": _client("bob"),
        "vic": _client("vic"),
        "db": factory,
        "project": project,
        "orders": orders,
        "recipe": recipe,
        "ids": ids,
    }
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()
    if schema is not None:
        admin = create_engine(POSTGRES)
        with admin.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _ok(response, code: int = 200):
    assert response.status_code == code, response.text
    return response.json() if response.content else None


def _base(world) -> str:
    return f"/api/v1/projects/{world['project']}"


def _recipe(world) -> str:
    return f"{_base(world)}/pipelines/{world['recipe']['id']}"


SORT = {"step_type": "sort_rows", "config": {"columns": ["amount"], "ascending": False}}
DEDUPE = {"step_type": "remove_duplicates", "config": {}}
DROP = {"step_type": "drop_columns", "config": {"columns": ["status"]}}


def _notes(world, username: str) -> list[str]:
    with world["db"]() as session:
        return [
            note.title
            for note in session.scalars(
                select(UserNotification).where(UserNotification.user_id == world["ids"][username])
            ).all()
        ]


# --------------------------------------------------------------------------
# W1: no silent overwrites
# --------------------------------------------------------------------------


def test_the_measured_defect_a_second_save_from_an_old_revision_is_refused(world) -> None:
    start = world["recipe"]["revision"]
    assert start == 1 and len(world["recipe"]["step_ids"]) == 1
    first = _ok(world["ann"].patch(_recipe(world), json={"steps_json": [DEDUPE, SORT], "expected_revision": start}))
    assert first["revision"] == 2
    refused = world["bob"].patch(_recipe(world), json={"steps_json": [DEDUPE, DROP], "expected_revision": start})
    assert refused.status_code == 409, refused.text
    assert refused.json()["detail"].startswith("Ann Lee saved this recipe at ")
    assert "would replace their changes" in refused.json()["detail"]
    kept = _ok(world["ann"].get(_recipe(world)))
    assert [step["step_type"] for step in kept["steps_json"]] == ["remove_duplicates", "sort_rows"]
    # Every save is in the recipe's history, so it can be compared and restored.
    history = _ok(world["ann"].get(f"{_base(world)}/history/pipeline/{world['recipe']['id']}"))
    assert len(history["items"]) == 2


# --------------------------------------------------------------------------
# W2: the shared copy
# --------------------------------------------------------------------------


def _ops_add(step_id: str, pos: str, stamp: list) -> list[dict]:
    return [{"k": "add", "id": step_id, "type": "sort_rows", "pos": pos, "cfg": {"columns": ["amount"]}, "s": stamp}]


def test_two_studios_see_each_others_changes_and_save_them_together(world) -> None:
    ann_copy = _ok(world["ann"].get(f"{_recipe(world)}/shared"))
    assert ann_copy["epoch"] == 1 and ann_copy["seq"] == 0 and ann_copy["your_role"] == "admin"
    assert ann_copy["saved"]["step_ids"] == world["recipe"]["step_ids"]
    [first] = world["recipe"]["step_ids"]
    bob_copy = _ok(world["bob"].get(f"{_recipe(world)}/shared"))

    # Ann adds a step after the first; Bob changes the first step's setting.
    _ok(world["ann"].post(f"{_recipe(world)}/shared", json={"epoch": 1, "client_id": "ann-tab", "ops": _ops_add("new1", "r", [1, "ann-tab"])}))
    _ok(
        world["bob"].post(
            f"{_recipe(world)}/shared",
            json={"epoch": 1, "client_id": "bob-tab", "ops": [{"k": "set", "id": first, "key": "columns", "v": ["order_id"], "s": [1, "bob-tab"]}]},
        )
    )
    news = _ok(world["bob"].get(f"{_recipe(world)}/shared", params={"epoch": 1, "after": bob_copy["seq"], "revision": 1}))
    assert [batch["actor"] for batch in news["batches"]] == ["Ann Lee", "Bob"]
    assert news["saved"] is None, "nothing new is saved"

    # Saving the shared copy keeps it; the steps and their ids are saved.
    saved = _ok(
        world["ann"].patch(
            _recipe(world),
            json={
                "steps_json": [{"step_type": "remove_duplicates", "config": {"columns": ["order_id"]}}, {"step_type": "sort_rows", "config": {"columns": ["amount"]}}],
                "step_ids": [first, "new1"],
                "expected_revision": 1,
                "shared_epoch": 1,
            },
        )
    )
    assert saved["step_ids"] == [first, "new1"] and saved["revision"] == 2
    after = _ok(world["bob"].get(f"{_recipe(world)}/shared", params={"epoch": 1, "after": news["seq"], "revision": 1}))
    assert after["epoch"] == 1 and after["saved"]["revision"] == 2 and after["saved"]["revised_by"] == "Ann Lee"


def test_a_change_outside_the_studio_starts_the_copy_again_and_says_why(world) -> None:
    _ok(world["ann"].get(f"{_recipe(world)}/shared"))
    _ok(world["ann"].post(f"{_recipe(world)}/shared", json={"epoch": 1, "client_id": "a", "ops": _ops_add("n", "r", [1, "a"])}))
    # Bob saves through the API, without the copy.
    _ok(world["bob"].patch(_recipe(world), json={"steps_json": [DEDUPE, DROP]}))
    stale = world["ann"].post(f"{_recipe(world)}/shared", json={"epoch": 1, "client_id": "a", "ops": _ops_add("m", "z", [2, "a"])})
    assert stale.status_code == 409
    fresh = _ok(world["ann"].get(f"{_recipe(world)}/shared", params={"epoch": 1, "after": 1}))
    assert fresh["epoch"] == 2 and fresh["doc"] is not None
    assert fresh["reset_reason"] == "bob changed this recipe outside the Studio."
    steps = [step for step in fresh["doc"]["steps"].values() if not step["del"]["v"]]
    assert sorted(step["type"] for step in steps) == ["drop_columns", "remove_duplicates"]


def test_discarding_unsaved_changes_is_for_everyone(world) -> None:
    _ok(world["ann"].get(f"{_recipe(world)}/shared"))
    _ok(world["ann"].post(f"{_recipe(world)}/shared", json={"epoch": 1, "client_id": "a", "ops": _ops_add("n", "r", [1, "a"])}))
    reset = _ok(world["bob"].post(f"{_recipe(world)}/shared/discard"))
    assert reset["epoch"] == 2 and "n" not in reset["doc"]["steps"]
    assert summarise("POST", f"{_recipe(world)}/shared/discard") == "discarded a recipe's unsaved changes"


def test_bad_changes_are_refused_in_words(world) -> None:
    _ok(world["ann"].get(f"{_recipe(world)}/shared"))
    for ops, words in (
        ([{"k": "add", "id": "x", "type": "t", "pos": "r0", "cfg": {}, "s": [1, "a"]}], "place in the recipe"),
        ([{"k": "set", "id": "x", "key": "k", "v": 1}], "missing its stamp"),
        ([{"k": "set", "id": "x", "key": "k", "v": 1, "s": [1, "saved"]}], "missing its stamp"),
        ([{"k": "explode", "id": "x", "s": [1, "a"]}], "not a change a recipe can take"),
    ):
        refused = world["ann"].post(f"{_recipe(world)}/shared", json={"epoch": 1, "client_id": "a", "ops": ops})
        assert refused.status_code == 400, refused.text
        assert words in refused.json()["detail"]
    # A viewer reads the copy but may not change it.
    assert world["vic"].get(f"{_recipe(world)}/shared").status_code == 200
    assert world["vic"].post(f"{_recipe(world)}/shared", json={"epoch": 1, "client_id": "v", "ops": []}).status_code == 403


def test_edits_and_presence_stay_out_of_the_audit_log(world) -> None:
    recipe = _recipe(world)
    assert not is_audited("POST", f"{recipe}/shared")
    assert not is_audited("POST", f"{_base(world)}/presence")
    assert not is_audited("DELETE", f"{_base(world)}/presence/tab-1")
    assert is_audited("POST", f"{recipe}/suggest")
    assert summarise("POST", f"{recipe}/suggest") == "suggested a change to a recipe"


# --------------------------------------------------------------------------
# W4: suggestions and approval
# --------------------------------------------------------------------------


def test_a_viewers_suggestion_is_accepted_and_becomes_the_recipe(world) -> None:
    _ok(world["ann"].get(f"{_recipe(world)}/shared"))
    suggestion = _ok(
        world["vic"].post(
            f"{_recipe(world)}/suggest",
            json={"title": "Sort the big orders first", "note": "Finance reads the top.", "steps_json": [DEDUPE, SORT]},
        ),
        201,
    )
    assert suggestion["before_json"]["steps_json"] == [DEDUPE]
    assert suggestion["change_summary"] and suggestion["change_summary"] != "Changed ."
    assert "A suggestion for Clean orders" in _notes(world, "ann")
    assert "A suggestion for Clean orders" in _notes(world, "bob")
    # The author cannot accept their own; an editor can.
    assert world["vic"].post(f"{_base(world)}/changes/{suggestion['id']}/approve", json={}).status_code == 403
    _ok(world["bob"].post(f"{_base(world)}/changes/{suggestion['id']}/approve", json={"note": "Good idea"}))
    recipe = _ok(world["ann"].get(_recipe(world)))
    assert [step["step_type"] for step in recipe["steps_json"]] == ["remove_duplicates", "sort_rows"]
    assert recipe["revision"] == 2
    copy = _ok(world["ann"].get(f"{_recipe(world)}/shared", params={"epoch": 1, "after": 0}))
    assert copy["epoch"] == 2 and "bob" in copy["reset_reason"]
    assert "Your suggestion was accepted" in _notes(world, "vic")


def test_a_declined_suggestion_says_why_and_changes_nothing(world) -> None:
    suggestion = _ok(world["vic"].post(f"{_recipe(world)}/suggest", json={"title": "Drop status", "steps_json": [DEDUPE, DROP]}), 201)
    _ok(world["ann"].post(f"{_base(world)}/changes/{suggestion['id']}/reject", json={"note": "We need status"}))
    assert _ok(world["ann"].get(_recipe(world)))["revision"] == 1
    with world["db"]() as session:
        [note] = session.scalars(
            select(UserNotification).where(
                UserNotification.user_id == world["ids"]["vic"], UserNotification.title == "Your suggestion was declined"
            )
        ).all()
    assert note.message.endswith("Their note: We need status")
    # A suggestion that changes nothing is refused.
    same = world["vic"].post(f"{_recipe(world)}/suggest", json={"title": "Nothing", "steps_json": [DEDUPE]})
    assert same.status_code == 400 and "does not change anything" in same.json()["detail"]


def test_a_project_can_ask_for_approval_and_then_editors_suggest(world) -> None:
    assert _ok(world["ann"].patch(_base(world), json={"requires_approval": True}))["requires_approval"] is True
    # Bob is an editor, not an admin: the setting is the admin's to change.
    assert world["bob"].patch(_base(world), json={"requires_approval": False}).status_code == 403
    refused = world["bob"].patch(_recipe(world), json={"steps_json": [DEDUPE, SORT]})
    assert refused.status_code == 403 and "Propose the edit as a change request" in refused.json()["detail"]
    # The shared copy is a draft, so editing it still works; suggesting does too.
    copy = _ok(world["bob"].get(f"{_recipe(world)}/shared"))
    assert copy["needs_approval"] is True
    _ok(world["bob"].post(f"{_recipe(world)}/shared", json={"epoch": 1, "client_id": "b", "ops": _ops_add("n", "r", [1, "b"])}))
    _ok(world["bob"].post(f"{_recipe(world)}/suggest", json={"title": "Sort it", "steps_json": [DEDUPE, SORT]}), 201)
    assert _ok(world["ann"].get(f"{_recipe(world)}/shared"))["open_suggestions"] == 1


# --------------------------------------------------------------------------
# W3: who is here
# --------------------------------------------------------------------------


def test_people_with_a_recipe_open_see_each_other_and_where(world) -> None:
    target = {"target_type": "recipe", "target_id": world["recipe"]["id"]}
    _ok(world["ann"].post(f"{_base(world)}/presence", json={**target, "client_id": "ann-tab"}))
    seen = _ok(world["vic"].post(f"{_base(world)}/presence", json={**target, "client_id": "vic-tab", "focus": {"step": "s1"}}))
    people = {person["name"]: person for person in seen["people"]}
    assert set(people) == {"Ann Lee", "Vic"}
    assert people["Ann Lee"]["initials"] == "AL" and people["Vic"]["you"] is True
    assert people["Vic"]["focus"] == {"step": "s1"}
    # Leaving drops a person at once; going quiet drops them after twenty seconds.
    _ok(world["vic"].delete(f"{_base(world)}/presence/vic-tab", params=target), 204)
    with world["db"]() as session:
        row = session.scalar(select(Presence).where(Presence.client_id == "ann-tab"))
        row.seen_at = datetime.now(UTC) - timedelta(seconds=30)
        session.commit()
    assert _ok(world["bob"].get(f"{_base(world)}/presence", params=target))["people"] == []
    # A tab is one person's; another's id is not taken over.
    _ok(world["bob"].post(f"{_base(world)}/presence", json={**target, "client_id": "bob-tab"}))
    assert world["vic"].post(f"{_base(world)}/presence", json={**target, "client_id": "bob-tab"}).status_code == 409


# --------------------------------------------------------------------------
# W5: threads on a cell
# --------------------------------------------------------------------------


def test_a_thread_on_a_cell_takes_replies_and_resolves_as_a_whole(world) -> None:
    dataset = world["orders"]["id"]
    root = _ok(
        world["ann"].post(
            f"{_base(world)}/discussion",
            json={
                "target_type": "dataset",
                "target_id": dataset,
                "body": "Is 1,200 right here?",
                "anchor": {"column": "amount", "row_key_column": "order_id", "row_key_value": "1004"},
            },
        ),
        201,
    )
    reply = _ok(
        world["bob"].post(
            f"{_base(world)}/discussion",
            json={"target_type": "dataset", "target_id": dataset, "body": "Yes, two chairs.", "parent_id": root["id"]},
        ),
        201,
    )
    assert reply["parent_id"] == root["id"]
    assert "bob replied in a thread you are in" in _notes(world, "ann")
    threads = _ok(world["ann"].get(f"{_base(world)}/discussion", params={"target_type": "dataset", "target_id": dataset}))
    [thread] = threads["items"]
    assert thread["anchor"]["column"] == "amount" and [item["body"] for item in thread["replies"]] == ["Yes, two chairs."]
    # Resolving a reply resolves its thread; replying again opens it.
    _ok(world["bob"].post(f"{_base(world)}/discussion/{reply['id']}/resolve"))
    assert _ok(world["ann"].get(f"{_base(world)}/discussion", params={"target_type": "dataset", "target_id": dataset}))["open_count"] == 0
    _ok(world["ann"].post(f"{_base(world)}/discussion", json={"target_type": "dataset", "target_id": dataset, "body": "Thanks", "parent_id": reply["id"]}), 201)
    again = _ok(world["ann"].get(f"{_base(world)}/discussion", params={"target_type": "dataset", "target_id": dataset}))
    assert again["open_count"] == 1 and len(again["items"][0]["replies"]) == 2


@pytest.mark.parametrize(
    ("body", "words"),
    [
        ({"anchor": {"column": "amount"}}, "by its identifier's value or by its number"),
        ({"anchor": {"column": "amount", "row_number": 3}}, "needs the version it is in"),
        ({"anchor": {"column": "a", "row_number": 1, "version": 1}, "target_type": "pipeline"}, "Only a dataset's cells"),
    ],
)
def test_a_cell_must_be_named_properly(world, body, words) -> None:
    payload = {"target_type": "dataset", "target_id": world["orders"]["id"], "body": "Hm", **body}
    if body.get("target_type") == "pipeline":
        payload["target_id"] = world["recipe"]["id"]
    refused = world["ann"].post(f"{_base(world)}/discussion", json=payload)
    assert refused.status_code == 400, refused.text
    assert words in refused.json()["detail"]


# --------------------------------------------------------------------------
# W6: what happened to a dataset
# --------------------------------------------------------------------------


def test_a_datasets_history_says_what_made_each_version(world) -> None:
    run = _ok(world["ann"].post(f"{_recipe(world)}/run"))
    output = run["dataset"]["id"]
    _ok(world["bob"].patch(_recipe(world), json={"steps_json": [DEDUPE, {"step_type": "limit_rows", "config": {"count": 10}}]}))
    _ok(world["ann"].post(f"{_recipe(world)}/run"))
    _ok(world["bob"].patch(_recipe(world), json={"steps_json": [DEDUPE, {"step_type": "limit_rows", "config": {"count": 10}}, DROP]}))
    _ok(world["ann"].post(f"{_recipe(world)}/run"))
    _ok(
        world["bob"].post(
            f"{_base(world)}/discussion",
            json={"target_type": "dataset", "target_id": output, "body": "Only ten?", "anchor": {"column": "amount", "row_number": 2, "version": 2}},
        ),
        201,
    )
    feed = _ok(world["ann"].get(f"{_base(world)}/datasets/{output}/activity"))
    sentences = [item["sentence"] for item in feed["items"]]
    assert "Bob commented on amount, row 2 of version 2" in sentences
    versions = [item for item in feed["items"] if item["kind"] == "versions"]
    assert [item["sentence"] for item in versions] == [
        "Version 3: 10 rows, 8 columns (−1 column)",
        "Version 2: 10 rows, 9 columns (−38 rows)",
        "Version 1: 48 rows, 9 columns",
    ]
    assert all(item["detail"] == "Recipe run: Clean orders" for item in versions)
    assert versions[0]["href"].startswith(f"/projects/{world['project']}/runs/")
    # Paged, like the project's stream.
    first = _ok(world["ann"].get(f"{_base(world)}/datasets/{output}/activity", params={"limit": 1}))
    assert len(first["items"]) == 1 and first["next_offset"] == 1


def test_two_pages_arriving_together_share_one_row(world) -> None:
    """Found rehearsing: a page's first two presence requests raced to insert
    the same row, and the loser failed. Each now finds the other's."""
    from concurrent.futures import ThreadPoolExecutor

    target = {"target_type": "recipe", "target_id": world["recipe"]["id"], "client_id": "same-tab"}
    with ThreadPoolExecutor(max_workers=4) as pool:
        answers = list(pool.map(lambda _: world["ann"].post(f"{_base(world)}/presence", json=target), range(4)))
    assert [answer.status_code for answer in answers] == [200, 200, 200, 200]
    with ThreadPoolExecutor(max_workers=4) as pool:
        copies = list(pool.map(lambda _: world["bob"].get(f"{_recipe(world)}/shared"), range(4)))
    assert [copy.status_code for copy in copies] == [200, 200, 200, 200]
    assert len({copy.json()["epoch"] for copy in copies}) == 1
