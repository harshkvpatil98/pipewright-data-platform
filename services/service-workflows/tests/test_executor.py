"""Executor tests.

These drive a real SQLite-backed session so ordering, conditional routing, and
recorded node history are exercised against actual persistence. Node handlers are
replaced with scripted stand-ins: what is under test is the graph walk, not the
services it delegates to.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from service_workflows import executor as executor_module
from service_workflows.executor import execute_workflow_run
from service_workflows.models import (
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
)
from service_workflows.nodes import NodeResult
from shared_python.db import Base


@pytest.fixture()
def db() -> Iterator[Session]:
    # Import every model so the shared metadata can create a complete schema.
    import api_gateway.metadata  # noqa: F401

    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


@pytest.fixture()
def actor(db: Session, monkeypatch: pytest.MonkeyPatch):
    """Bypass the user lookup; identity is not what these tests cover."""
    from service_auth.schemas import UserRead

    user = UserRead(
        id=uuid.uuid4(),
        username="worker",
        role="admin",
        is_active=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    monkeypatch.setattr(executor_module, "_actor_for_run", lambda *_args, **_kwargs: user)
    return user


def build_workflow(
    db: Session,
    nodes: list[tuple[str, str]],
    edges: list[tuple[str, str, str]] = (),
    *,
    continue_on_failure: set[str] = frozenset(),
) -> tuple[Workflow, WorkflowRun]:
    project_id = uuid.uuid4()
    workflow = Workflow(
        project_id=project_id,
        name="test workflow",
        trigger_type="manual",
        enabled=True,
    )
    db.add(workflow)
    db.flush()

    for key, node_type in nodes:
        db.add(
            WorkflowNode(
                workflow_id=workflow.id,
                project_id=project_id,
                node_key=key,
                name=key,
                node_type=node_type,
                config_json={},
                continue_on_failure=key in continue_on_failure,
            )
        )
    for source, target, condition in edges:
        db.add(
            WorkflowEdge(
                workflow_id=workflow.id,
                from_node_key=source,
                to_node_key=target,
                condition=condition,
            )
        )

    run = WorkflowRun(
        workflow_id=workflow.id,
        project_id=project_id,
        status="queued",
        trigger="manual",
        queued_at=datetime.now(UTC),
    )
    db.add(run)
    db.commit()
    return workflow, run


def scripted(outcomes: dict[str, bool], calls: list[str]):
    """A stand-in handler that succeeds or fails per node key and records order."""

    def _execute(node_type: str, config: dict, context) -> NodeResult:  # noqa: ARG001
        key = config.get("__key__", "")
        calls.append(key)
        success = outcomes.get(key, True)
        return NodeResult(
            success=success,
            message="ok" if success else "boom",
            output={"dataset_id": str(uuid.uuid4())} if success else {},
        )

    return _execute


def install_handlers(
    monkeypatch: pytest.MonkeyPatch, db: Session, run: WorkflowRun, outcomes: dict[str, bool]
) -> list[str]:
    """Route the executor's node calls to a scripted handler keyed by node_key."""
    calls: list[str] = []
    handler = scripted(outcomes, calls)

    # The executor passes the node's config, so stamp the key into it first.
    for node in db.query(WorkflowNode).filter(WorkflowNode.workflow_id == run.workflow_id):
        node.config_json = {"__key__": node.node_key}
    db.commit()

    monkeypatch.setattr(executor_module, "execute_node", handler)
    return calls


def node_runs(db: Session, run: WorkflowRun) -> dict[str, WorkflowNodeRun]:
    rows = db.query(WorkflowNodeRun).filter(WorkflowNodeRun.workflow_run_id == run.id).all()
    return {row.node_key: row for row in rows}


# ------------------------------------------------------------------ happy path


def test_linear_workflow_runs_every_node_in_order(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = build_workflow(
        db,
        [("extract", "extraction"), ("clean", "transformation"), ("ship", "publish")],
        [("extract", "clean", "on_success"), ("clean", "ship", "on_success")],
    )
    calls = install_handlers(monkeypatch, db, run, {})

    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert calls == ["extract", "clean", "ship"]
    assert finished.status == "succeeded"
    assert finished.nodes_succeeded == 3
    assert finished.nodes_failed == 0
    assert finished.finished_at is not None


def test_every_node_run_is_recorded(db: Session, actor, monkeypatch: pytest.MonkeyPatch) -> None:
    _, run = build_workflow(
        db, [("a", "extraction"), ("b", "publish")], [("a", "b", "on_success")]
    )
    install_handlers(monkeypatch, db, run, {})

    execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    recorded = node_runs(db, run)
    assert set(recorded) == {"a", "b"}
    assert recorded["a"].sequence == 1
    assert recorded["b"].sequence == 2
    assert recorded["a"].duration_ms is not None
    assert recorded["a"].status == "succeeded"


# ------------------------------------------------------------ gating behaviour


def test_failure_skips_downstream_nodes(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The point of a quality gate: a failure must stop the publish."""
    _, run = build_workflow(
        db,
        [("extract", "extraction"), ("gate", "quality_gate"), ("ship", "publish")],
        [("extract", "gate", "on_success"), ("gate", "ship", "on_success")],
    )
    calls = install_handlers(monkeypatch, db, run, {"gate": False})

    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert "ship" not in calls
    assert finished.status == "failed"
    assert finished.nodes_failed == 1
    assert finished.nodes_skipped == 1
    assert node_runs(db, run)["ship"].status == "skipped"
    assert "gate" in node_runs(db, run)["ship"].skip_reason


def test_on_failure_branch_runs_only_when_upstream_fails(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = build_workflow(
        db,
        [("load", "extraction"), ("ship", "publish"), ("alert", "notify")],
        [("load", "ship", "on_success"), ("load", "alert", "on_failure")],
    )
    calls = install_handlers(monkeypatch, db, run, {"load": False})

    execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert "alert" in calls
    assert "ship" not in calls


def test_always_branch_runs_after_either_outcome(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = build_workflow(
        db,
        [("load", "extraction"), ("done", "notify")],
        [("load", "done", "always")],
    )
    calls = install_handlers(monkeypatch, db, run, {"load": False})

    execute_workflow_run(db, run=run, storage_backend=None, settings=None)
    assert "done" in calls


def test_continue_on_failure_keeps_the_run_going(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A non-blocking node that fails downgrades the run, it does not stop it."""
    _, run = build_workflow(
        db,
        [("optional", "notify"), ("main", "publish")],
        [],
        continue_on_failure={"optional"},
    )
    calls = install_handlers(monkeypatch, db, run, {"optional": False})

    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert set(calls) == {"optional", "main"}
    assert finished.status == "partial"
    assert finished.nodes_failed == 1
    assert finished.nodes_succeeded == 1


def test_join_waits_for_both_parents(db: Session, actor, monkeypatch: pytest.MonkeyPatch) -> None:
    _, run = build_workflow(
        db,
        [("a", "extraction"), ("b", "extraction"), ("join", "publish")],
        [("a", "join", "on_success"), ("b", "join", "on_success")],
    )
    calls = install_handlers(monkeypatch, db, run, {})

    execute_workflow_run(db, run=run, storage_backend=None, settings=None)
    assert calls.index("join") > max(calls.index("a"), calls.index("b"))


def test_join_skips_when_one_parent_fails(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = build_workflow(
        db,
        [("a", "extraction"), ("b", "extraction"), ("join", "publish")],
        [("a", "join", "on_success"), ("b", "join", "on_success")],
    )
    calls = install_handlers(monkeypatch, db, run, {"b": False})

    execute_workflow_run(db, run=run, storage_backend=None, settings=None)
    assert "join" not in calls


def test_parallel_branches_both_run(db: Session, actor, monkeypatch: pytest.MonkeyPatch) -> None:
    _, run = build_workflow(
        db,
        [("root", "extraction"), ("left", "transformation"), ("right", "transformation")],
        [("root", "left", "on_success"), ("root", "right", "on_success")],
    )
    calls = install_handlers(monkeypatch, db, run, {})

    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)
    assert set(calls) == {"root", "left", "right"}
    assert finished.status == "succeeded"


# ------------------------------------------------------------- failure guards


def test_invalid_graph_fails_the_run_before_executing_anything(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = build_workflow(
        db,
        [("a", "extraction"), ("b", "publish")],
        [("a", "b", "on_success"), ("b", "a", "on_success")],
    )
    calls = install_handlers(monkeypatch, db, run, {})

    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert calls == []
    assert finished.status == "failed"
    assert "not runnable" in finished.error_message


def test_run_without_an_actor_fails_rather_than_escalating(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No resolvable user means no ownership checks; refuse instead of guessing."""
    _, run = build_workflow(db, [("a", "extraction")], [])
    monkeypatch.setattr(executor_module, "execute_node", scripted({}, []))

    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert finished.status == "failed"
    assert "user to act as" in finished.error_message


def test_lease_is_released_when_the_run_finishes(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = build_workflow(db, [("a", "extraction")], [])
    run.claim_owner_id = "worker-1"
    run.claim_expires_at = datetime.now(UTC)
    db.commit()
    install_handlers(monkeypatch, db, run, {})

    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert finished.claim_owner_id is None
    assert finished.claim_expires_at is None


def test_node_config_macros_resolve_against_the_runs_slot(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A backfill run must see its own slot, not the day it happens to execute."""
    _, run = build_workflow(db, [("ship", "publish")], [])
    run.logical_date = datetime(2026, 3, 3, tzinfo=UTC)
    for node in db.query(WorkflowNode).filter(WorkflowNode.workflow_id == run.workflow_id):
        node.config_json = {"table_name": "orders_{{ ds_nodash }}", "max_rows": 500}
    db.commit()

    seen: dict[str, object] = {}

    def capture(node_type: str, config: dict, context) -> NodeResult:  # noqa: ARG001
        seen.update(config)
        return NodeResult(success=True, message="ok")

    monkeypatch.setattr(executor_module, "execute_node", capture)
    execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    assert seen["table_name"] == "orders_20260303"
    # Non-string values keep their type through rendering.
    assert seen["max_rows"] == 500


def test_an_unknown_macro_fails_only_its_own_node(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, run = build_workflow(
        db,
        [("good", "notify"), ("broken", "publish")],
        [],
    )
    for node in db.query(WorkflowNode).filter(WorkflowNode.workflow_id == run.workflow_id):
        node.config_json = (
            {"table_name": "t_{{ nonsense }}"} if node.node_key == "broken" else {"__key__": "good"}
        )
    db.commit()

    monkeypatch.setattr(executor_module, "execute_node", scripted({}, []))
    finished = execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    recorded = node_runs(db, finished)
    assert recorded["broken"].status == "failed"
    assert "Unknown macro" in recorded["broken"].message
    assert recorded["good"].status == "succeeded"


def test_workflow_summary_is_updated_after_a_run(
    db: Session, actor, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflow, run = build_workflow(db, [("a", "extraction")], [])
    install_handlers(monkeypatch, db, run, {})

    execute_workflow_run(db, run=run, storage_backend=None, settings=None)

    db.refresh(workflow)
    assert workflow.last_run_status == "succeeded"
    assert workflow.execution_count == 1
    assert workflow.last_run_at is not None
