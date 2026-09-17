"""Literal paths and patterns: the rule, and the two ways it used to break.

This repository is a Next.js App Router application, so
`apps/web/src/app/projects/[projectId]/datasets/[datasetId]/page.tsx` is an
ordinary file. Under `fnmatch`, which the guard used to call, `[projectId]` is a
character class, and that was wrong in both directions at once: the real file
was refused, and `projects/p/datasets/d/page.tsx` -- a different, unauthorised
file -- was allowed, because `p` and `d` are in those classes.

The rule now is one sentence: a pattern is a glob if and only if it contains `*`
or `?`. These tests hold that sentence in place.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pw_dev.controller.scheduler import Scheduler, TaskNode
from pw_dev.workspace.guard import (ALWAYS_FORBIDDEN, PathGuard, PathViolation,
                                    is_pattern, pattern_covers, patterns_overlap,
                                    resolve_within)

DYNAMIC_PAGE = "apps/web/src/app/projects/[projectId]/datasets/[datasetId]/page.tsx"
T05_PATHS = [
    DYNAMIC_PAGE,
    "apps/web/src/app/projects/[projectId]/datasets/[datasetId]/versions/**",
    "apps/web/src/features/datasets/components/dataset-detail-page.tsx",
    "apps/web/src/features/datasets/versioning/**",
    "apps/web/src/features/datasets/**/*.test.ts",
    "apps/web/src/features/datasets/**/*.test.tsx",
    "apps/web/src/app/projects/[projectId]/runs/[runId]/**",
]


def t05() -> PathGuard:
    return PathGuard(T05_PATHS, ["packages/shared-types/**", "packages/shared-ui/**",
                                 "services/**", "package-lock.json"])


# ------------------------------------------------- the exact reported failure
def test_the_dynamic_route_page_the_specification_grants_is_writable():
    assert t05().check(DYNAMIC_PAGE) == DYNAMIC_PAGE


@pytest.mark.parametrize("path", [
    "apps/web/src/app/projects/[projectId]/datasets/[datasetId]/versions/version-list.tsx",
    "apps/web/src/app/projects/[projectId]/datasets/[datasetId]/versions/diff/panel.tsx",
    "apps/web/src/app/projects/[projectId]/runs/[runId]/page.tsx",
    "apps/web/src/app/projects/[projectId]/runs/[runId]/inputs/pinned.tsx",
])
def test_nested_dynamic_route_directories_are_writable(path: str):
    assert t05().check(path) == path


@pytest.mark.parametrize("path", [
    "apps/web/src/features/datasets/versioning/history.test.tsx",
    "apps/web/src/features/datasets/history.test.ts",
    "apps/web/src/features/datasets/a/b/c/deep.test.tsx",
])
def test_intended_wildcards_still_match(path: str):
    assert t05().check(path) == path


@pytest.mark.parametrize("path", [
    # The over-grant. `[projectId]` matched the single character `p` and
    # `[datasetId]` matched `d`, so this unauthorised file passed the guard.
    "apps/web/src/app/projects/p/datasets/d/page.tsx",
    "apps/web/src/app/projects/j/datasets/t/page.tsx",
    # Siblings of a granted file are not granted.
    "apps/web/src/app/projects/[projectId]/datasets/[datasetId]/layout.tsx",
    "apps/web/src/app/projects/[projectId]/datasets/page.tsx",
    # A different feature area.
    "apps/web/src/features/audit/components/run-audit-page.tsx",
    # Not a test file, so the `*.test.tsx` grant does not reach it.
    "apps/web/src/features/datasets/components/grid.tsx",
])
def test_neighbouring_unauthorised_paths_are_refused(path: str):
    with pytest.raises(PathViolation):
        t05().check(path)


def test_brackets_are_literal_and_stars_are_not():
    assert not is_pattern("apps/web/src/app/[projectId]/page.tsx")
    assert is_pattern("apps/web/**")
    assert is_pattern("src/*.py")
    assert is_pattern("src/?.py")


def test_a_single_star_does_not_cross_a_directory_boundary():
    guard = PathGuard(["src/*.py"])
    assert guard.check("src/app.py")
    with pytest.raises(PathViolation):
        guard.check("src/vendor/lib.py")


def test_double_star_crosses_directory_levels_and_matches_zero():
    guard = PathGuard(["services/service-datasets/**"])
    assert guard.check("services/service-datasets/src/a/b/models.py")
    assert guard.check("services/service-datasets/README.md")


# ------------------------------------------------------ traversal and symlinks
@pytest.mark.parametrize("bad", [
    "../outside.py",
    "apps/../../outside.py",
    "/etc/passwd",
    "~/.ssh/id_rsa",
    "C:/Windows/system32",
    "//host/share/file",
    "apps\\..\\..\\outside.py",
])
def test_traversal_and_absolute_paths_are_refused(bad: str):
    with pytest.raises(PathViolation):
        PathGuard(["**"]).check(bad)


def test_a_dynamic_route_directory_cannot_hide_a_traversal():
    with pytest.raises(PathViolation):
        t05().check("apps/web/src/app/projects/[projectId]/../../../../../etc/passwd")


def test_a_symlink_out_of_the_checkout_is_refused_even_inside_a_granted_root(tmp_path: Path):
    root = tmp_path / "wt"
    nested = root / "apps" / "web" / "src" / "app" / "projects" / "[projectId]"
    nested.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (nested / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathViolation, match="outside"):
        resolve_within(root, "apps/web/src/app/projects/[projectId]/escape/evil.tsx")


def test_a_path_inside_a_dynamic_route_directory_resolves(tmp_path: Path):
    root = tmp_path / "wt"
    nested = root / "apps" / "web" / "src" / "app" / "projects" / "[projectId]"
    nested.mkdir(parents=True)
    resolved = resolve_within(root, "apps/web/src/app/projects/[projectId]/page.tsx")
    assert resolved.parent == nested.resolve()


# ----------------------------------------------------- forbidden takes priority
def test_a_forbidden_path_overrides_an_allowed_one():
    guard = PathGuard(["apps/web/**"], ["apps/web/src/app/projects/[projectId]/**"])
    assert guard.check("apps/web/src/features/x.tsx")
    with pytest.raises(PathViolation, match="forbidden"):
        guard.check("apps/web/src/app/projects/[projectId]/page.tsx")


@pytest.mark.parametrize("target", [
    ".git/config", ".pw-dev/state.sqlite3", "tools/dev-orchestrator/pw-dev.toml",
    "tools/dev-orchestrator/src/pw_dev/verify/registry.py",
    "tools/dev-orchestrator/src/pw_dev/verify/alembic_heads.py",
    "tools/dev-orchestrator/src/pw_dev/verify/live_acceptance.py",
    "tools/dev-orchestrator/src/pw_dev/publish/publisher.py",
    ".env", "apps/web/.env.local", "deploy/id_ed25519", "certs/server.pem",
    ".github/workflows/ci.yml",
])
def test_the_standing_forbidden_set_still_refuses_everything_it_named(target: str):
    """The matcher changed; what it must never allow did not."""
    with pytest.raises(PathViolation, match="forbidden"):
        PathGuard(["**"]).check(target)


def test_a_task_cannot_widen_its_scope_by_also_declaring_a_forbidden_path():
    guard = PathGuard([".git/**", "src/**"])
    with pytest.raises(PathViolation):
        guard.check(".git/config")
    assert guard.check("src/app.py") == "src/app.py"


def test_the_verification_code_a_check_runs_is_in_the_standing_forbidden_set():
    assert "tools/dev-orchestrator/src/pw_dev/verify/**" in ALWAYS_FORBIDDEN


# --------------------------------------------------------- overlapping ownership
@pytest.mark.parametrize("left,right,expected", [
    ("services/a/**", "services/a/models.py", True),
    ("services/a/models.py", "services/a/models.py", True),
    ("services/a/models.py", "services/a/schemas.py", False),
    ("services/service-datasets", "services/service-datasets/src/models.py", True),
    ("services/service-datasets", "services/service-sources/src/models.py", False),
    ("apps/web/**", "apps/web/src/features/datasets/**/*.test.tsx", True),
    (DYNAMIC_PAGE, "apps/web/src/app/projects/[projectId]/**", True),
    (DYNAMIC_PAGE, "apps/web/src/app/projects/p/**", False),
    ("apps/web/src/features/datasets/**", "apps/web/src/features/audit/**", False),
    ("**/package-lock.json", "package-lock.json", True),
    ("**/package-lock.json", "apps/web/**", True),
    ("**/package-lock.json", "apps/web/src/features/**/*.test.tsx", False),
    ("src/*.py", "src/vendor/lib.py", False),
])
def test_overlap_is_decided_not_guessed(left: str, right: str, expected: bool):
    assert patterns_overlap(left, right) is expected
    assert patterns_overlap(right, left) is expected, "overlap is symmetric"


def test_two_frontend_tasks_splitting_dynamic_routes_can_run_concurrently():
    """The over-grant made these look separate and the refusal made them look identical."""
    scheduler = Scheduler([
        TaskNode(id="T-05", title="datasets", role="frontend", depends_on=[],
                 allowed_paths=T05_PATHS),
        TaskNode(id="T-06", title="audit", role="frontend", depends_on=[],
                 allowed_paths=["apps/web/src/features/audit/**",
                                "apps/web/src/app/projects/[projectId]/audit/**"]),
    ], max_parallel=2)
    assert scheduler.overlapping_pairs() == []
    assert len(scheduler.ready(done=set(), running=set(), held_resources={})) == 2


def test_two_tasks_claiming_the_same_dynamic_route_page_are_refused():
    scheduler = Scheduler([
        TaskNode(id="T-05", title="page", role="frontend", depends_on=[],
                 allowed_paths=[DYNAMIC_PAGE]),
        TaskNode(id="T-07", title="tree", role="frontend", depends_on=[],
                 allowed_paths=["apps/web/src/app/projects/[projectId]/datasets/**"]),
    ], max_parallel=2)
    overlaps = scheduler.overlapping_pairs()
    assert overlaps and overlaps[0][:2] == ("T-05", "T-07")
    assert len(scheduler.ready(done=set(), running=set(), held_resources={})) == 1


# ------------------------------------------------------------------ containment
@pytest.mark.parametrize("outer,inner,expected", [
    ("apps/api-gateway/alembic/**", "apps/api-gateway/alembic/versions/0031_x.py", True),
    ("apps/api-gateway/alembic/**", "apps/api-gateway/alembic/versions/**", True),
    ("apps/**", "apps/api-gateway/alembic/**", True),
    ("apps/web/**", "**/package-lock.json", False),
    ("**/package-lock.json", "apps/web/**", False),
    ("apps/web/src/app/projects/[projectId]/**", DYNAMIC_PAGE, True),
    ("apps/web/src/app/projects/p/**", DYNAMIC_PAGE, False),
])
def test_containment_is_narrower_than_overlap(outer: str, inner: str, expected: bool):
    assert pattern_covers(outer, inner) is expected


def test_a_recursive_claim_does_not_take_the_lockfile_lock_for_existing_beneath_it():
    """`apps/web/**` could contain a lockfile. It has not declared that it edits one."""
    web = TaskNode(id="T", title="t", role="frontend", depends_on=[],
                   allowed_paths=["apps/web/**"])
    assert "lockfile" not in web.effective_resources()
    assert any("lockfile" in reach for reach in web.unguarded_resource_reach()) is False


def test_a_dynamic_route_claim_no_longer_flattens_into_a_serialized_resource():
    node = TaskNode(id="T-05", title="t", role="frontend", depends_on=[],
                    allowed_paths=T05_PATHS)
    assert node.effective_resources() == []


@pytest.mark.parametrize("paths,resource", [
    (["apps/api-gateway/alembic/versions/0031_dataset_versions.py"], "alembic"),
    (["apps/api-gateway/alembic/versions/**"], "alembic"),
    (["package-lock.json"], "lockfile"),
    (["packages/shared-types/src/domain.ts"], "contracts"),
])
def test_the_implicit_locks_that_mattered_still_engage(paths: list[str], resource: str):
    node = TaskNode(id="T", title="t", role="backend", depends_on=[], allowed_paths=paths)
    assert resource in node.effective_resources()


def test_a_claim_that_reaches_a_lock_without_holding_it_is_reported():
    node = TaskNode(id="T", title="t", role="backend", depends_on=[],
                    allowed_paths=["apps/api-gateway/**/*.py"])
    assert "alembic" not in node.effective_resources()
    assert any("alembic" in reach for reach in node.unguarded_resource_reach())


# ------------------------------------------------------------------ sandbox scope
def test_literal_roots_anchor_on_dynamic_route_directories():
    roots = t05().literal_roots()
    assert "apps/web/src/app/projects/[projectId]/datasets/[datasetId]/versions" in roots
    assert "apps/web/src/features/datasets" in roots
    # A descendant of another root is not listed twice.
    assert "apps/web/src/features/datasets/versioning" not in roots


def test_every_literal_root_resolves_inside_a_checkout(tmp_path: Path):
    """The roots a task is anchored at must all be reachable in its own worktree."""
    root = tmp_path / "wt"
    root.mkdir()
    for relative in t05().literal_roots():
        resolved = resolve_within(root, relative)
        assert str(resolved).startswith(str(root.resolve()))


def test_a_task_whose_anchor_escapes_its_checkout_is_refused_before_it_starts(
        tmp_path: Path):
    """The dispatch-time check, exercised through the controller's own method."""
    from pw_dev.controller.run import Controller

    checkout = tmp_path / "wt"
    (checkout / "apps" / "web").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (checkout / "apps" / "web" / "src").symlink_to(outside, target_is_directory=True)

    events: list[tuple] = []

    controller = Controller.__new__(Controller)
    controller.run_id = "run-test"
    controller.store = type("Store", (), {
        "event": lambda self, *a, **k: events.append((a, k)),
    })()

    honest = TaskNode(id="T-01", title="t", role="frontend", depends_on=[],
                      allowed_paths=["apps/web/**"])
    controller._assert_scope_resolves_inside(honest, checkout)
    assert events, "an anchor that resolves is recorded, not silently accepted"

    escaping = TaskNode(id="T-02", title="t", role="frontend", depends_on=[],
                        allowed_paths=[DYNAMIC_PAGE])
    with pytest.raises(PathViolation, match="outside"):
        controller._assert_scope_resolves_inside(escaping, checkout)


# ======================= regressions from the independent review =============
def test_a_bare_directory_claim_overlaps_a_rooted_filename_pattern():
    """Both guards accept `apps/web/package-lock.json`, so the claims overlap.

    The overlap check compared the wildcard-free claim against a same-length
    prefix of the other pattern, which cannot work when the other pattern opens
    with `**`. It answered "no overlap", and the scheduler would have dispatched
    both tasks into the same file.
    """
    assert patterns_overlap("apps/web", "**/package-lock.json")
    assert PathGuard(["apps/web"]).check("apps/web/package-lock.json")
    assert PathGuard(["**/package-lock.json"]).check("apps/web/package-lock.json")

    scheduler = Scheduler([
        TaskNode(id="T-01", title="web", role="frontend", depends_on=[],
                 allowed_paths=["apps/web"]),
        TaskNode(id="T-02", title="deps", role="backend", depends_on=[],
                 allowed_paths=["**/package-lock.json"]),
    ], max_parallel=2)
    assert scheduler.overlapping_pairs(), "these two claim one file"
    assert len(scheduler.ready(done=set(), running=set(), held_resources={})) == 1


@pytest.mark.parametrize("left,right", [
    ("services/service-datasets", "services/**"),
    ("docs", "**/*.md"),
    ("package-lock.json", "**/package-lock.json"),
    ("apps/web/src", "apps/web/**/*.tsx"),
])
def test_a_wildcard_free_claim_overlaps_anything_reaching_into_its_subtree(left, right):
    assert patterns_overlap(left, right)
    assert patterns_overlap(right, left)


def test_containment_is_not_inferred_from_a_single_witness():
    """`src/x` matches `src/*` and not `src/*p*`, so neither contains the other.

    The previous implementation built one placeholder path and matched it. The
    placeholder text contained a `p`, so `src/*p*` "contained" `src/*`; the same
    letters made the ordinary claim `**/*pw*` look like it contained `.git/**`.
    """
    assert not pattern_covers("src/*p*", "src/*")
    assert not pattern_covers("src/*", "src/*p*")
    assert not pattern_covers(".git/**", "**/*pw*")
    assert not pattern_covers("**/*pw*", ".git/**")


def test_a_claim_whose_name_contains_the_placeholder_letters_is_not_refused():
    from pw_dev.testing import make_spec
    from pw_dev.controller.validate_plan import validate_plan
    from pw_dev.verify.registry import Registry

    spec = make_spec()
    spec["tasks"][0]["allowed_paths"] = ["**/*pw*"]

    class _Publication:
        mode = "none"
        branch_prefix = "pw-dev"
        allow_existing_branch = None

    class _Limits:
        max_parallel_workers = 2
        per_task_seconds = 30
        total_run_seconds = 300
        repair_rounds_per_task = 2

    class _Config:
        publication = _Publication()
        limits = _Limits()

    report = validate_plan(spec, config=_Config(), registry=Registry(),
                           base_commit=spec["base_commit"], repo_root=None)
    assert not any("never writable by a task" in e for e in report.errors)


def test_the_containment_cases_the_scheduler_relies_on_still_hold():
    assert pattern_covers("apps/api-gateway/alembic/**",
                          "apps/api-gateway/alembic/versions/0031_x.py")
    assert pattern_covers("apps/**", "apps/api-gateway/alembic/**")
    assert pattern_covers("services/**", "services/service-datasets/**")
    assert pattern_covers(".git/**", ".git/config")
    assert pattern_covers("package-lock.json", "package-lock.json")
    # Not established, and therefore False: the safe direction.
    assert not pattern_covers("**/package-lock.json", "apps/web/**")
    assert not pattern_covers("apps/web/**", "**/package-lock.json")


def test_a_concrete_lockfile_claim_still_takes_the_lock():
    """Containment cannot prove it, so the concrete-path case carries it."""
    named = TaskNode(id="T", title="t", role="backend", depends_on=[],
                     allowed_paths=["apps/web/package-lock.json"])
    assert "lockfile" in named.effective_resources()

    recursive = TaskNode(id="T", title="t", role="frontend", depends_on=[],
                         allowed_paths=["apps/web/**"])
    assert "lockfile" not in recursive.effective_resources(), (
        "owning the web app is not declaring a lockfile edit"
    )
