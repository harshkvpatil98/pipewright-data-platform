"""Durable state: transitions, locks, leases, artifacts, usage, crash recovery."""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from pw_dev.errors import StateError
from pw_dev.state.db import RunStore
from pw_dev.state.machine import (RESUMABLE_RUN_STATES, RunState, TaskState, describe,
                                  is_terminal, transition_allowed)


def _run(store: RunStore, **kwargs) -> str:
    return store.create_run(
        brain="automatic", config_snapshot={"x": 1}, publication_mode="none",
        deadline_epoch=None, **kwargs,
    )


# ------------------------------------------------------------------- machine
def test_an_illegal_transition_is_refused(store: RunStore):
    run_id = _run(store)
    with pytest.raises(StateError, match="not a legal transition"):
        store.set_run_state(run_id, RunState.COMPLETE, "skipping straight to done")


def test_a_run_cannot_reach_complete_without_passing_through_push():
    assert transition_allowed(RunState.PUSH, RunState.COMPLETE)
    assert not transition_allowed(RunState.VERIFY, RunState.COMPLETE)
    assert not transition_allowed(RunState.REVIEW, RunState.COMPLETE)


def test_an_exhausted_budget_pauses_rather_than_completes():
    """The distinction the whole design turns on."""
    assert RunState.PAUSED in RESUMABLE_RUN_STATES
    assert not is_terminal(RunState.PAUSED)
    assert is_terminal(RunState.COMPLETE)
    assert transition_allowed(RunState.IMPLEMENT, RunState.PAUSED)
    assert not transition_allowed(RunState.PAUSED, RunState.COMPLETE)


def test_verified_local_is_reachable_without_publication():
    assert transition_allowed(RunState.REVIEW, RunState.VERIFIED_LOCAL)
    assert transition_allowed(RunState.COMMIT, RunState.VERIFIED_LOCAL)
    assert is_terminal(RunState.VERIFIED_LOCAL)


def test_every_state_states_its_outstanding_condition():
    for state in RunState:
        text = describe(state)
        assert len(text) > 20, f"{state} needs a condition a person can act on"


# --------------------------------------------------------------------- locks
def test_a_second_controller_cannot_take_a_live_lock(store: RunStore, config):
    run_id = _run(store)
    store.acquire_run_lock(run_id)
    with RunStore(config.db_path(), config.runs_dir()) as other:
        with pytest.raises(StateError, match="owned by pid"):
            other.acquire_run_lock(run_id)


def test_a_lock_left_by_a_dead_process_is_reclaimed(store: RunStore):
    run_id = _run(store)
    dead = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    dead.wait()
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO run_locks(run_id, owner_pid, owner_token, hostname, acquired_at,"
            " heartbeat_at) VALUES(?,?,?,?,?,?)",
            (run_id, dead.pid, "stale", os.uname().nodename, "t", "t"),
        )
    token = store.acquire_run_lock(run_id)
    assert token != "stale"
    assert any(e["kind"] == "run.lock.reclaimed" for e in store.events(run_id))


def test_the_same_controller_can_refresh_its_own_lock_with_its_token(store: RunStore):
    run_id = _run(store)
    token = store.acquire_run_lock(run_id)
    assert store.acquire_run_lock(run_id, existing_token=token) == token


def test_a_lost_lock_is_detected_on_heartbeat(store: RunStore):
    run_id = _run(store)
    store.acquire_run_lock(run_id)
    with pytest.raises(StateError, match="lost the controller lock"):
        store.heartbeat_run_lock(run_id, "not-the-token")


# -------------------------------------------------------------------- leases
def test_a_live_lease_prevents_a_duplicate_worker(store: RunStore):
    run_id = _run(store)
    store.create_tasks(run_id, [{"id": "T-01", "title": "t", "role": "backend"}])
    store.acquire_lease(run_id, "T-01", ttl_seconds=60)
    with pytest.raises(StateError, match="already leased"):
        store.acquire_lease(run_id, "T-01", ttl_seconds=60)


def test_an_expired_lease_from_a_dead_process_is_reclaimed(store: RunStore):
    run_id = _run(store)
    store.create_tasks(run_id, [{"id": "T-01", "title": "t", "role": "backend"}])
    dead = subprocess.Popen([sys.executable, "-c", "pass"])  # noqa: S603
    dead.wait()
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO leases(run_id, task_id, lease_token, owner_pid, child_pid,"
            " acquired_at, heartbeat_at, expires_at_epoch) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, "T-01", "stale", dead.pid, None, "t", "t", time.time() - 1),
        )
    token = store.acquire_lease(run_id, "T-01", ttl_seconds=60)
    assert token != "stale"
    assert any(e["kind"] == "task.lease.expired" for e in store.events(run_id))


def test_stale_leases_are_listed_for_reconciliation(store: RunStore):
    run_id = _run(store)
    store.create_tasks(run_id, [{"id": "T-01", "title": "t", "role": "backend"}])
    with store.transaction() as conn:
        conn.execute(
            "INSERT INTO leases(run_id, task_id, lease_token, owner_pid, child_pid,"
            " acquired_at, heartbeat_at, expires_at_epoch) VALUES(?,?,?,?,?,?,?,?)",
            (run_id, "T-01", "t", 999999, None, "t", "t", time.time() - 10),
        )
    assert [r["task_id"] for r in store.stale_leases(run_id)] == ["T-01"]


# ------------------------------------------------------------------ resources
def test_a_resource_has_one_holder(store: RunStore):
    run_id = _run(store)
    assert store.acquire_resource(run_id, "alembic", "T-01")
    assert not store.acquire_resource(run_id, "alembic", "T-02")
    assert store.acquire_resource(run_id, "alembic", "T-01"), "re-entrant for its holder"
    store.release_resource(run_id, "alembic", "T-01")
    assert store.acquire_resource(run_id, "alembic", "T-02")


# ------------------------------------------------------------------- the log
def test_state_changes_and_their_events_are_written_together(store: RunStore):
    run_id = _run(store)
    store.set_run_state(run_id, RunState.PLAN, "planning")
    events = [e for e in store.events(run_id) if e["kind"] == "run.state"]
    assert len(events) == 1
    assert "DISCOVER -> PLAN" in events[0]["message"]


def test_the_log_is_redacted(store: RunStore):
    run_id = _run(store)
    store.event(run_id, "test", "the provider returned sk-ant-abcdefghijklmnopqrstuvwxyz012345")
    body = "\n".join(e["message"] for e in store.events(run_id))
    assert "sk-ant-abcdefghij" not in body
    assert "<redacted>" in body


def test_the_log_is_append_only_in_sequence(store: RunStore):
    run_id = _run(store)
    for index in range(5):
        store.event(run_id, "test", f"event {index}")
    seqs = [e["seq"] for e in store.events(run_id)]
    assert seqs == sorted(seqs)


# ----------------------------------------------------------------- artifacts
def test_artifacts_are_stored_by_content_hash(store: RunStore):
    run_id = _run(store)
    first = store.put_json_artifact(run_id, "phase_spec", {"a": 1})
    second = store.put_json_artifact(run_id, "phase_spec", {"a": 1})
    assert first == second
    assert store.load_json_artifact(run_id, "phase_spec", first) == {"a": 1}


def test_a_missing_artifact_is_an_error_not_an_empty_document(store: RunStore):
    run_id = _run(store)
    with pytest.raises(StateError, match="no phase_spec artifact"):
        store.artifact_path(run_id, "phase_spec", "0" * 64)


# --------------------------------------------------------------------- usage
def test_a_missing_cost_is_unknown_not_zero(store: RunStore):
    """codex exec reports tokens and no dollars. Zero would be a claim."""
    run_id = _run(store)
    store.record_usage(run_id, role="planner", provider="codex", model="m",
                       input_tokens=100, output_tokens=10, cost_usd=None)
    summary = store.usage_summary(run_id)
    assert summary["cost_usd_known"] is None
    assert summary["calls_without_cost"] == 1


def test_known_and_unknown_costs_are_reported_separately(store: RunStore):
    run_id = _run(store)
    store.record_usage(run_id, role="planner", provider="codex", model="m",
                       input_tokens=100, output_tokens=10, cost_usd=None)
    store.record_usage(run_id, role="worker", provider="claude", model="m",
                       input_tokens=200, output_tokens=20, cost_usd=0.5)
    summary = store.usage_summary(run_id)
    assert summary["cost_usd_known"] == 0.5
    assert summary["calls_without_cost"] == 1
    assert summary["calls"] == 2
    assert summary["by_provider"] == ["claude", "codex"]


# ---------------------------------------------------------------- durability
def test_state_survives_reopening_the_database(config):
    with RunStore(config.db_path(), config.runs_dir()) as store:
        run_id = _run(store)
        store.set_run_state(run_id, RunState.PLAN, "planning")
        store.create_tasks(run_id, [{"id": "T-01", "title": "t", "role": "backend"}])
        store.set_task_state(run_id, "T-01", TaskState.RUNNING, "working")

    with RunStore(config.db_path(), config.runs_dir()) as reopened:
        assert reopened.get_run(run_id)["state"] == "PLAN"
        assert reopened.get_task(run_id, "T-01")["state"] == "RUNNING"
        assert len(reopened.events(run_id)) >= 3


def test_a_newer_schema_is_refused_rather_than_misread(config):
    with RunStore(config.db_path(), config.runs_dir()) as store:
        with store.transaction() as conn:
            conn.execute("UPDATE meta SET value='999' WHERE key='schema_version'")
    with pytest.raises(StateError, match="newer pw-dev"):
        RunStore(config.db_path(), config.runs_dir())
