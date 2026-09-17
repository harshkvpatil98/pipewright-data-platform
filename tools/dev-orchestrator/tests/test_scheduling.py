"""Dependency order, bounded parallelism, ownership and serialized resources."""

from __future__ import annotations

import pytest

from pw_dev.errors import PolicyViolation
from pw_dev.controller.scheduler import Scheduler, TaskNode


def node(task_id: str, *, depends_on=(), paths=("src/**",), resources=(), role="backend") -> TaskNode:
    return TaskNode(
        id=task_id, title=task_id, role=role, depends_on=list(depends_on),
        allowed_paths=list(paths), exclusive_resources=list(resources),
    )


def test_a_task_waits_for_its_dependencies():
    scheduler = Scheduler(
        [node("T-01", paths=["packages/shared-types/**"], role="contract"),
         node("T-02", depends_on=["T-01"], paths=["services/a/**"]),
         node("T-03", depends_on=["T-01"], paths=["apps/web/**"], role="frontend")],
        max_parallel=3,
    )
    first = scheduler.ready(done=set(), running=set(), held_resources={})
    assert [n.id for n in first] == ["T-01"]

    after = scheduler.ready(done={"T-01"}, running=set(), held_resources={})
    assert {n.id for n in after} == {"T-02", "T-03"}


def test_contract_work_is_offered_first():
    scheduler = Scheduler(
        [node("T-09", paths=["services/a/**"]),
         node("T-01", paths=["packages/shared-types/**"], role="contract")],
        max_parallel=1,
    )
    ready = scheduler.ready(done=set(), running=set(), held_resources={})
    assert [n.id for n in ready] == ["T-01"]


def test_parallelism_is_bounded():
    nodes = [node(f"T-{i:02d}", paths=[f"services/s{i}/**"]) for i in range(1, 8)]
    scheduler = Scheduler(nodes, max_parallel=3)
    ready = scheduler.ready(done=set(), running=set(), held_resources={})
    assert len(ready) == 3
    assert not scheduler.ready(done=set(), running={"a", "b", "c"}, held_resources={})


def test_tasks_that_claim_the_same_paths_are_never_offered_together():
    scheduler = Scheduler(
        [node("T-01", paths=["services/a/**"]), node("T-02", paths=["services/a/**"])],
        max_parallel=2,
    )
    ready = scheduler.ready(done=set(), running=set(), held_resources={})
    assert len(ready) == 1, "overlapping write ownership must serialize"


def test_overlapping_ownership_is_reported_at_validation_time():
    scheduler = Scheduler(
        [node("T-01", paths=["services/a/**"]), node("T-02", paths=["services/a/models.py"])],
        max_parallel=2,
    )
    overlaps = scheduler.overlapping_pairs()
    assert overlaps and overlaps[0][:2] == ("T-01", "T-02")


def test_a_dependency_makes_shared_paths_legitimate():
    """A task built on another's work is meant to touch those files."""
    scheduler = Scheduler(
        [node("T-01", paths=["services/a/**"]),
         node("T-02", depends_on=["T-01"], paths=["services/a/**"])],
        max_parallel=2,
    )
    assert scheduler.overlapping_pairs() == []


def test_a_task_that_touches_alembic_takes_the_migration_lock_implicitly():
    """Two workers allocating parallel revisions produce two Alembic heads."""
    migration = node("T-01", paths=["apps/api-gateway/alembic/versions/**"])
    assert "alembic" in migration.effective_resources()


def test_lockfile_and_contract_edits_are_serialized_implicitly():
    assert "lockfile" in node("T-01", paths=["package-lock.json"]).effective_resources()
    assert "contracts" in node("T-02", paths=["packages/shared-types/**"]).effective_resources()


def test_two_tasks_needing_the_same_resource_do_not_run_together():
    scheduler = Scheduler(
        [node("T-01", paths=["apps/api-gateway/alembic/versions/a.py"]),
         node("T-02", paths=["apps/api-gateway/alembic/versions/b.py"])],
        max_parallel=2,
    )
    ready = scheduler.ready(done=set(), running=set(), held_resources={})
    assert len(ready) == 1


def test_a_held_resource_blocks_a_waiting_task():
    scheduler = Scheduler(
        [node("T-01", paths=["services/a/**"], resources=["alembic"]),
         node("T-02", paths=["services/b/**"], resources=["alembic"])],
        max_parallel=2,
    )
    ready = scheduler.ready(done=set(), running=set(), held_resources={"alembic": "T-01"})
    assert [n.id for n in ready] == []


def test_a_cycle_is_refused():
    with pytest.raises(PolicyViolation, match="cycle"):
        Scheduler(
            [node("T-01", depends_on=["T-02"]), node("T-02", depends_on=["T-01"])],
            max_parallel=2,
        )


def test_an_unknown_dependency_is_refused():
    with pytest.raises(PolicyViolation, match="unknown task"):
        Scheduler([node("T-01", depends_on=["T-99"])], max_parallel=2)


def test_a_task_with_no_writable_paths_is_refused():
    with pytest.raises(PolicyViolation, match="no writable paths"):
        Scheduler([node("T-01", paths=[])], max_parallel=2)


def test_blocked_reasons_name_the_precise_condition():
    scheduler = Scheduler(
        [node("T-01", paths=["services/a/**"]),
         node("T-02", depends_on=["T-01"], paths=["services/b/**"])],
        max_parallel=1,
    )
    reason = scheduler.blocked_reason(
        scheduler.nodes["T-02"], done=set(), running=set(), held_resources={},
    )
    assert "waiting on T-01" in reason

    at_limit = scheduler.blocked_reason(
        scheduler.nodes["T-01"], done=set(), running={"T-03"}, held_resources={},
    )
    assert "concurrency limit" in at_limit


def test_topological_order_puts_prerequisites_first():
    scheduler = Scheduler(
        [node("T-03", depends_on=["T-02"], paths=["c/**"]),
         node("T-02", depends_on=["T-01"], paths=["b/**"]),
         node("T-01", paths=["a/**"])],
        max_parallel=3,
    )
    order = scheduler.topological_order()
    assert order.index("T-01") < order.index("T-02") < order.index("T-03")
