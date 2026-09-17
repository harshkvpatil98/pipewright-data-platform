"""Planning as an operator actually uses it: status wording, preflight, context
files, the publication handoff, and validating a specification without running it.

The thread running through all of these is that a word has to mean one thing. A
plan-only run finished in `VERIFIED_LOCAL`, whose own description said "verified
and approved"; the plan summary printed eight resolved contradictions under a
heading that read like eight blockers; `plan` forced `publication=none` onto
every specification and `run --publish feature-branch` then refused it; and
there was no way to check a specification at all without starting a run.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from pw_dev.cli import main
from pw_dev.config import Config
from pw_dev.controller.context import read_operator_context
from pw_dev.controller.roles import plan_prompt
from pw_dev.controller.validate_plan import CAVEAT, validate_plan
from pw_dev.state.machine import (RESUMABLE_RUN_STATES, SUCCESSFUL_RUN_STATES, RunState,
                                  describe, describe_run, is_terminal, transition_allowed)
from pw_dev.testing import make_spec, run_git
from pw_dev.verify.registry import Registry


def _validate(spec, config, base=None):
    return validate_plan(spec, config=config, registry=Registry(),
                         base_commit=base or spec.get("base_commit", "0" * 40),
                         repo_root=config.repo_root)


# ============================================================== A2: the status
def test_a_plan_only_run_does_not_end_in_a_state_that_says_approved():
    assert transition_allowed(RunState.VALIDATE_PLAN, RunState.PLAN_READY)
    assert not transition_allowed(RunState.VALIDATE_PLAN, RunState.VERIFIED_LOCAL)
    assert is_terminal(RunState.PLAN_READY)
    assert RunState.PLAN_READY in SUCCESSFUL_RUN_STATES
    assert RunState.PLAN_READY not in RESUMABLE_RUN_STATES


def test_the_three_success_states_say_three_different_things():
    plan = describe(RunState.PLAN_READY)
    verified = describe(RunState.VERIFIED_LOCAL)
    complete = describe(RunState.COMPLETE)

    assert "nothing was implemented" in plan
    assert "no reviewer saw it" in plan
    for word in ("approved", "verified by"):
        assert word not in plan, f"a validated plan must not describe itself as {word}"

    assert "independent" in verified and "reviewer" in verified
    assert "nothing was published" in verified
    assert "read back" in complete


def test_a_stored_plan_only_run_from_before_the_state_existed_is_described_honestly():
    """Old rows are evidence. They are re-described, never relabelled."""
    legacy = describe_run(RunState.VERIFIED_LOCAL, plan_only=True)
    assert "nothing was implemented, verified or reviewed" in legacy
    assert "Recorded before PLAN_READY existed" in legacy

    implementation = describe_run(RunState.VERIFIED_LOCAL, plan_only=False)
    assert implementation == describe(RunState.VERIFIED_LOCAL)
    assert "independent" in implementation, (
        "a real implementation run must not be demoted to a plan"
    )


def test_the_plan_summary_separates_resolved_questions_from_open_ones(capsys):
    from pw_dev.cli import _summarise_spec

    spec = make_spec(open_questions=[
        {"question": "Which record selects the next phase?",
         "evidence": "roadmap line 3 against the ledger",
         "resolution": "follow the ledger; the roadmap opening is stale"},
        {"question": "Does anything else read the artifact directly?",
         "evidence": "not determined", "resolution": ""},
    ])
    _summarise_spec(spec, Path("/tmp/phase-spec.json"))
    out = capsys.readouterr().out

    assert "contradictions with a proposed resolution (1)" in out
    assert "they are not blockers" in out
    assert "proposed: follow the ledger" in out
    assert "unresolved questions (1)" in out
    assert "nothing in the plan" in out


def test_the_plan_summary_discloses_truncation_and_names_the_full_artifact(capsys):
    from pw_dev.cli import _summarise_spec

    spec = make_spec(summary="word " * 300)
    _summarise_spec(spec, Path("/tmp/phase-spec.json"))
    out = capsys.readouterr().out
    assert "more characters]" in out
    assert "this is a summary; the complete specification is at /tmp/phase-spec.json" in out
    assert "validate it without running anything" in out


# ======================================================== A5: the plan preflight
def test_a_declared_dynamic_route_path_is_checked_against_the_real_guard(config):
    spec = make_spec()
    spec["tasks"][0]["allowed_paths"] = [
        "apps/web/src/app/projects/[projectId]/datasets/[datasetId]/page.tsx",
    ]
    assert _validate(spec, config).ok, "the guard must accept what the plan grants"


def test_a_task_that_forbids_everything_it_was_granted_is_refused(config):
    spec = make_spec()
    spec["tasks"][0]["allowed_paths"] = ["services/service-datasets/**"]
    spec["tasks"][0]["forbidden_paths"] = ["services/**"]
    report = _validate(spec, config)
    assert any("cannot write what it was given" in e for e in report.errors)


def test_a_recursive_claim_beside_a_credential_rule_is_not_an_error(config):
    """`services/x/tests/**` could contain a `.env`; the guard refuses that one file."""
    spec = make_spec()
    spec["tasks"][0]["allowed_paths"] = ["services/service-pipeline-runs/tests/**"]
    assert _validate(spec, config).ok


def test_claiming_the_verification_code_itself_is_still_refused(config):
    spec = make_spec()
    spec["tasks"][0]["allowed_paths"] = ["tools/dev-orchestrator/src/pw_dev/verify/**"]
    report = _validate(spec, config)
    assert any("never writable by a task" in e for e in report.errors)


def test_a_requirement_no_task_owns_is_an_error(config):
    spec = make_spec()
    spec["requirements"].append({"id": "R-02", "statement": "retention", "rationale": "x",
                                 "priority": "must"})
    report = _validate(spec, config)
    assert any("no task owns requirement(s) ['R-02']" in e for e in report.errors)


def test_a_requirement_with_no_acceptance_criterion_is_warned_about(config):
    spec = make_spec()
    spec["requirements"].append({"id": "R-02", "statement": "retention", "rationale": "x",
                                 "priority": "must"})
    spec["tasks"][0]["requirement_ids"] = ["R-01", "R-02"]
    report = _validate(spec, config)
    assert report.ok
    assert any("have no acceptance criterion" in w for w in report.warnings)


def test_an_acceptance_criterion_naming_an_unregistered_check_is_refused(config):
    spec = make_spec()
    spec["acceptance_criteria"][0]["verification_ids"] = ["time-travel:e2e"]
    report = _validate(spec, config)
    assert any("names unregistered verification ids" in e for e in report.errors)


def test_an_accepted_preexisting_failure_must_name_a_real_check(config):
    spec = make_spec()
    spec["accepted_preexisting_failures"] = [
        {"verification_id": "repo:imaginary", "reason": "flaky"}]
    report = _validate(spec, config)
    assert any("unregistered verification" in e for e in report.errors)


def test_a_duplicate_acceptance_criterion_id_is_refused(config):
    spec = make_spec()
    spec["acceptance_criteria"].append(copy.deepcopy(spec["acceptance_criteria"][0]))
    report = _validate(spec, config)
    assert any("duplicate acceptance criterion id" in e for e in report.errors)


def test_a_plan_cannot_raise_the_per_task_budget(config):
    spec = make_spec()
    spec["resource_limits"]["per_task_seconds"] = config.limits.per_task_seconds + 1
    report = _validate(spec, config)
    assert any("per task" in e and "adopted limit" in e for e in report.errors)


def test_a_single_task_that_can_exhaust_the_whole_run_is_refused(config):
    spec = make_spec()
    spec["resource_limits"] = {"max_parallel_workers": 2, "per_task_seconds": 120,
                               "total_run_seconds": 60, "repair_rounds_per_task": 2}
    report = _validate(spec, config)
    assert any("the first task can exhaust the run" in e for e in report.errors)


def test_worker_capacity_is_a_bound_even_without_a_dependency_chain(config):
    """Twelve independent tasks and two workers is six unavoidable waves.

    Dropping this bound was the overcorrection: `ceil(N / W) x timeout` is wrong
    as a *ceiling* -- a chain can force more waves than capacity does -- but it
    is a perfectly good lower bound on the worst case, and removing it let a
    plan needing 180s pass with a 60s budget.
    """
    spec = make_spec()
    spec["tasks"] = [
        {**copy.deepcopy(spec["tasks"][0]), "id": f"T-{i:02d}",
         "allowed_paths": [f"src/module_{i}.py"]}
        for i in range(1, 13)
    ]
    spec["resource_limits"] = {"max_parallel_workers": 2, "per_task_seconds": 30,
                               "total_run_seconds": 60, "repair_rounds_per_task": 2}
    report = _validate(spec, config)
    error = next((e for e in report.errors if "cannot overlap" in e), None)
    assert error, report.render()
    assert "12 worker task(s) across 2 worker(s), so 6 wave(s)" in error
    assert "180s" in error


def test_a_migration_nobody_owns_is_refused(config):
    spec = make_spec()
    spec["migration_strategy"] = {"needed": True, "notes": "adds dataset_versions",
                                  "alembic_revisions": ["0031_dataset_versions"]}
    report = _validate(spec, config)
    assert any("no task's allowed_paths reach" in e for e in report.errors)


def test_holding_the_alembic_lock_without_owning_the_file_is_refused(config):
    """A lock is not ownership: this task can never write the revision it locks."""
    spec = make_spec()
    spec["migration_strategy"] = {"needed": True, "notes": "adds dataset_versions",
                                  "alembic_revisions": ["0031_dataset_versions"]}
    spec["tasks"][0]["exclusive_resources"] = ["alembic"]
    spec["tasks"][0]["allowed_paths"] = ["src/app.py"]
    report = _validate(spec, config)
    assert any("cannot allocate the revision" in e for e in report.errors)


def test_a_migration_a_task_owns_validates(config):
    spec = make_spec()
    spec["migration_strategy"] = {"needed": True, "notes": "adds dataset_versions",
                                  "alembic_revisions": ["0031_dataset_versions"]}
    spec["tasks"][0]["allowed_paths"] = [
        "src/app.py", "apps/api-gateway/alembic/versions/0031_dataset_versions.py"]
    spec["tasks"][0]["exclusive_resources"] = ["alembic"]
    assert _validate(spec, config).ok


def test_an_implementation_task_owning_no_tests_is_reported(config):
    spec = make_spec()
    spec["tasks"][0]["allowed_paths"] = ["services/service-datasets/src/**"]
    report = _validate(spec, config)
    assert any("owns implementation paths and no test path" in w for w in report.warnings)


def test_a_task_owning_its_tests_is_not_reported(config):
    spec = make_spec()
    spec["tasks"][0]["allowed_paths"] = ["services/service-datasets/src/**",
                                         "services/service-datasets/tests/**"]
    report = _validate(spec, config)
    assert not any("no test path" in w for w in report.warnings)


def test_relying_on_the_optional_smoke_alone_is_reported(config):
    spec = make_spec(required_verifications=["repo:smoke"])
    report = _validate(spec, config)
    assert any("optional diagnostic" in w and "repo:live-acceptance" in w
               for w in report.warnings)


def test_a_task_asking_for_the_live_path_without_requiring_it_is_refused(config):
    spec = make_spec()
    spec["tasks"][0]["verification_ids"] = ["repo:live-acceptance"]
    report = _validate(spec, config)
    assert any("is not a gate on the phase" in e for e in report.errors)


def test_requiring_the_live_path_validates(config):
    spec = make_spec(required_verifications=["repo:smoke", "repo:live-acceptance"])
    spec["tasks"][0]["verification_ids"] = ["repo:live-acceptance"]
    report = _validate(spec, config)
    assert report.ok
    assert not any("optional diagnostic" in w for w in report.warnings)


def test_every_report_states_what_validation_does_not_prove(config):
    rendered = _validate(make_spec(), config).render()
    assert CAVEAT in rendered
    assert "does not establish that the design is correct" in rendered


# ===================================================== A6: operator context files
def test_an_operator_context_file_is_read_bounded_and_digested(config):
    target = config.repo_root / "docs" / "corrections.md"
    target.write_text("# Corrections\n\nInventory every producer.\n", encoding="utf-8")
    context = read_operator_context(config.repo_root, ["docs/corrections.md"], config.limits)

    assert not context.problems
    entry = context.digests[0]
    assert entry["path"] == "docs/corrections.md"
    # The digest identifies the file, not the bounded prompt body: two files
    # sharing a prefix must not share an identifier.
    assert entry["source_digest"] == hashlib.sha256(target.read_bytes()).hexdigest()
    assert entry["source_bytes"] == target.stat().st_size
    assert len(entry["delivered_digest"]) == 64
    assert "Inventory every producer." in context.render()


def test_two_files_sharing_a_bounded_prefix_get_different_source_digests(config):
    from dataclasses import replace

    limits = replace(config.limits, max_context_file_bytes=20)
    digests = []
    for index, tail in enumerate(("first ending", "second ending")):
        target = config.repo_root / "docs" / f"note-{index}.md"
        target.write_text("identical prefix....." + tail, encoding="utf-8")
        context = read_operator_context(config.repo_root, [f"docs/note-{index}.md"], limits)
        digests.append(context.digests[0])

    assert digests[0]["delivered_digest"] == digests[1]["delivered_digest"], (
        "the bounded bodies are the same, which is why the delivered digest cannot "
        "identify the file"
    )
    assert digests[0]["source_digest"] != digests[1]["source_digest"]


def test_the_operator_context_reaches_the_planner_prompt_in_full(config):
    target = config.repo_root / "docs" / "corrections.md"
    body = "B2. Resolve immutable snapshots versus enterprise erasure."
    target.write_text(body, encoding="utf-8")
    context = read_operator_context(config.repo_root, ["docs/corrections.md"], config.limits)

    prompt = plan_prompt(
        discovery={"phases": [], "contradictions": [], "deferred_decisions": [],
                   "branch": "main", "dirty_paths": [], "untracked_paths": [],
                   "recommendation_text": None},
        registry_ids=[("python:tests", "the bundle")], base_commit="0" * 40,
        config_summary={}, requested_phase="18", context_text="(none)",
        operator_context=context.render(),
    )
    assert body in prompt, "a filename is not delivery; the text must be in the packet"
    assert "Corrections and requirements supplied by the operator" in prompt
    assert "They rank above roadmap prose" in prompt


def test_a_context_file_outside_the_repository_is_refused(config, tmp_path: Path):
    outside = tmp_path / "secrets.md"
    outside.write_text("do not read me", encoding="utf-8")
    context = read_operator_context(config.repo_root, [str(outside)], config.limits)
    assert not context.files
    assert context.problems


def test_a_missing_context_file_is_a_problem_not_a_silent_omission(config):
    context = read_operator_context(config.repo_root, ["docs/absent.md"], config.limits)
    assert not context.files
    assert any("not a file in this checkout" in p for p in context.problems)


def test_an_oversized_context_file_is_truncated_and_says_so(config):
    from dataclasses import replace

    target = config.repo_root / "docs" / "huge.md"
    target.write_text("x" * 5000, encoding="utf-8")
    limits = replace(config.limits, max_context_file_bytes=100)
    context = read_operator_context(config.repo_root, ["docs/huge.md"], limits)
    assert context.digests[0]["truncated"]
    assert context.digests[0]["source_bytes"] == 5000
    rendered = context.render()
    assert "TRUNCATED" in rendered
    assert "of 5000 bytes" in rendered
    assert "read the rest from" in rendered


def test_too_many_context_files_are_reported_rather_than_dropped(config):
    for index in range(10):
        (config.repo_root / "docs" / f"note-{index}.md").write_text("x", encoding="utf-8")
    context = read_operator_context(
        config.repo_root, [f"docs/note-{i}.md" for i in range(10)], config.limits,
        max_files=3,
    )
    assert len(context.files) == 3
    assert any("were not read" in p for p in context.problems)


def test_context_files_survive_the_configuration_snapshot(config):
    from dataclasses import replace

    with_files = replace(config, planner_context_files=("docs/corrections.md",))
    assert Config.from_snapshot(with_files.snapshot()).planner_context_files == (
        "docs/corrections.md",
    )


# ============================================== A7: the publication-policy handoff
def test_a_specification_planned_for_one_policy_is_refused_under_another(config):
    from dataclasses import replace

    planned_for_none = make_spec()
    feature_branch = replace(
        config, publication=replace(config.publication, mode="feature_branch"))
    report = _validate(planned_for_none, feature_branch)
    assert not report.ok
    error = next(e for e in report.errors if "publication mode" in e)
    assert "pw-dev plan --publish feature-branch" in error, (
        "the refusal has to name the supported procedure, not just refuse"
    )
    assert "Neither the frozen policy of a recorded run nor this equality check is edited" \
        in error


def test_a_specification_planned_for_the_policy_it_runs_under_validates(config):
    from dataclasses import replace

    feature_branch = replace(
        config, publication=replace(config.publication, mode="feature_branch"))
    spec = make_spec()
    spec["publication_policy"]["mode"] = "feature_branch"
    assert _validate(spec, feature_branch).ok


def test_the_plan_command_exposes_the_policy_it_plans_for():
    from pw_dev.cli import build_parser

    parser = build_parser()
    args = parser.parse_args(["plan", "--phase", "18", "--publish", "feature-branch"])
    assert args.publish == "feature-branch"
    assert parser.parse_args(["plan", "--phase", "18"]).publish == "none"


def test_the_plan_command_accepts_repeated_context_files():
    from pw_dev.cli import build_parser

    args = build_parser().parse_args(
        ["plan", "--phase", "18", "--context-file", "a.md", "--context-file", "b.md"])
    assert args.context_file == ["a.md", "b.md"]


# ================================================= A8: validation without a run
@pytest.fixture
def spec_on_disk(config, tmp_path: Path) -> Path:
    base = run_git(config.repo_root, "rev-parse", "HEAD")
    spec = make_spec(base_commit=base)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec), encoding="utf-8")
    return path


def test_validate_spec_accepts_a_good_specification(spec_on_disk, config, capsys):
    code = main(["--repo", str(config.repo_root), "validate-spec", str(spec_on_disk)])
    out = capsys.readouterr().out
    assert code == 0
    assert "ACCEPTED" in out
    assert "Nothing was implemented, executed or published" in out


def test_validate_spec_exits_nonzero_on_rejection(spec_on_disk, config, capsys):
    document = json.loads(spec_on_disk.read_text(encoding="utf-8"))
    document["tasks"][0]["verification_ids"] = ["make-it-pass"]
    spec_on_disk.write_text(json.dumps(document), encoding="utf-8")
    code = main(["--repo", str(config.repo_root), "validate-spec", str(spec_on_disk)])
    out = capsys.readouterr().out
    assert code == 1
    assert "REJECTED" in out


def test_validate_spec_exits_two_on_a_malformed_document(tmp_path: Path, config, capsys):
    path = tmp_path / "broken.json"
    path.write_text(json.dumps({"schema_version": "phase_spec/v1"}), encoding="utf-8")
    code = main(["--repo", str(config.repo_root), "validate-spec", str(path)])
    assert code == 2
    assert "not a valid phase_spec/v1" in capsys.readouterr().out


def test_validate_spec_checks_against_head_by_default(spec_on_disk, config, capsys):
    document = json.loads(spec_on_disk.read_text(encoding="utf-8"))
    document["base_commit"] = "f" * 40
    spec_on_disk.write_text(json.dumps(document), encoding="utf-8")
    code = main(["--repo", str(config.repo_root), "validate-spec", str(spec_on_disk)])
    assert code == 1
    assert "Replan" in capsys.readouterr().out


def test_validate_spec_checks_the_policy_it_was_given(spec_on_disk, config, capsys):
    code = main(["--repo", str(config.repo_root), "validate-spec", str(spec_on_disk),
                 "--publish", "feature-branch"])
    assert code == 1
    assert "publication mode" in capsys.readouterr().out


def test_validate_spec_creates_no_run_and_no_worktree(spec_on_disk, config, capsys):
    main(["--repo", str(config.repo_root), "validate-spec", str(spec_on_disk)])
    capsys.readouterr()
    state_dir = config.repo_root / ".pw-dev"
    assert not state_dir.exists() or not list((state_dir / "runs").glob("*")), (
        "validating a specification must not start anything"
    )


def test_the_checks_listing_labels_what_each_result_is_worth(capsys):
    assert main(["checks"]) == 0
    out = capsys.readouterr().out
    assert "repo:live-acceptance [required_live]" in out
    assert "repo:smoke [optional_smoke]" in out
    assert "alembic:heads [gate]" in out
    assert "it cannot stand in for acceptance evidence" in out


# ============ A6 end to end: the file reaches the provider's actual argv ==========
def test_a_context_file_reaches_the_planner_process(fixture_repo: Path, tmp_path: Path):
    """The whole path: CLI override, controller, prompt, provider invocation.

    Asserted against what the stand-in planner was really handed, because "the
    prompt builder includes it" and "the planner received it" are different
    claims and only the second one matters.
    """
    from dataclasses import replace

    from pw_dev.controller.run import Controller
    from pw_dev.state.db import RunStore
    from pw_dev.testing import fake_claude, fake_codex, make_run_config, spec_for
    from pw_dev.workspace import git

    base = git.head_sha(fixture_repo)
    corrections = fixture_repo / "docs" / "phase-18-review-requirements.md"
    corrections.write_text(
        "# Corrections\n\nB2. The erasure path overwrites the stored file in place.\n",
        encoding="utf-8")

    bin_dir = tmp_path / "bin"
    codex = fake_codex(bin_dir, {"planner": spec_for(base)})
    claude = fake_claude(bin_dir, edits={})
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="none")
    config = replace(config,
                     planner_context_files=("docs/phase-18-review-requirements.md",))

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None, plan_only=True)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic",
                            reporter=lambda line: None)
    controller.acquire()
    try:
        state = controller.execute(plan_only=True)
    finally:
        controller.release()

    assert state is RunState.PLAN_READY

    calls = json.loads((bin_dir / "codex-calls.json").read_text(encoding="utf-8"))
    planner_prompt = next(c["argv"][-1] for c in calls if c["role"] == "planner")
    assert "B2. The erasure path overwrites the stored file in place." in planner_prompt
    assert "Corrections and requirements supplied by the operator" in planner_prompt

    messages = [e["message"] for e in store.events(run_id)]
    digest_line = next(m for m in messages if "planning context supplied by the operator" in m)
    assert "docs/phase-18-review-requirements.md" in digest_line
    assert "sha256" in digest_line
    store.close()


def test_a_planning_run_whose_every_context_file_is_rejected_is_blocked(
        fixture_repo: Path, tmp_path: Path):
    """Silently planning without the corrections is the failure this prevents."""
    from dataclasses import replace

    from pw_dev.controller.run import Controller
    from pw_dev.state.db import RunStore
    from pw_dev.testing import fake_claude, fake_codex, make_run_config, spec_for
    from pw_dev.workspace import git

    base = git.head_sha(fixture_repo)
    bin_dir = tmp_path / "bin"
    codex = fake_codex(bin_dir, {"planner": spec_for(base)})
    claude = fake_claude(bin_dir, edits={})
    config = make_run_config(fixture_repo, tmp_path, codex, claude, mode="none")
    config = replace(config, planner_context_files=("docs/never-written.md",))

    store = RunStore(config.db_path(), config.runs_dir())
    run_id = store.create_run(brain="automatic", config_snapshot=config.snapshot(),
                              publication_mode="none", deadline_epoch=None, plan_only=True)
    controller = Controller(config, store=store, run_id=run_id, brain="automatic",
                            reporter=lambda line: None)
    controller.acquire()
    try:
        state = controller.execute(plan_only=True)
    finally:
        controller.release()

    assert state is RunState.BLOCKED
    assert not (bin_dir / "codex-calls.json").exists(), (
        "the planner must not be called without the corrections it was given"
    )
    store.close()
