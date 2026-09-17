"""`pw-dev` — the operator's interface to the development orchestrator.

Every command works from durable state, so a new session can pick up a run
without the conversation that started it. Nothing here requires the original
chat: specifications, decisions, patches, evidence, findings and receipts are
all on disk.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Config, find_repo_root
from .controller.recovery import reconcile
from .controller.run import Controller
from .doctor import run_doctor
from .errors import PwDevError
from .schemas.validate import SchemaError, validate_artifact
from .state.db import RunStore
from .state.machine import RunState, describe


def _store(config: Config) -> RunStore:
    return RunStore(config.db_path(), config.runs_dir())


def _config(args: argparse.Namespace) -> Config:
    repo_root = Path(args.repo).resolve() if getattr(args, "repo", None) else find_repo_root()
    overrides: dict = {}
    publish = getattr(args, "publish", None)
    if publish:
        mode = {"none": "none", "local": "local_commit", "feature-branch": "feature_branch"}[publish]
        overrides["publication"] = {"mode": mode}
        if getattr(args, "branch", None):
            overrides.setdefault("publication", {})["allow_existing_branch"] = args.branch
    if getattr(args, "max_workers", None):
        overrides["limits"] = {"max_parallel_workers": args.max_workers}
    if getattr(args, "unattended", False):
        overrides["isolation"] = {"unattended": True}
    for role, flag in (("planner", "planner_model"), ("implementer", "implementer_model"),
                       ("reviewer", "reviewer_model")):
        value = getattr(args, flag, None)
        if value:
            overrides[role] = {"model": value}
    return Config.load(repo_root, overrides=overrides)


def _echo(line: str) -> None:
    print(line, flush=True)


# --------------------------------------------------------------------- doctor
def cmd_doctor(args: argparse.Namespace) -> int:
    config = _config(args)
    report = run_doctor(config, probe=args.probe, probe_timeout=args.probe_timeout)
    _echo(report.render())
    _echo("")
    _echo("ok" if report.ok else "there are failures above that would stop a run")
    return 0 if report.ok else 1


# ----------------------------------------------------------------------- plan
def cmd_plan(args: argparse.Namespace) -> int:
    config = _config(args)
    with _store(config) as store:
        run_id = store.create_run(
            brain=args.brain, config_snapshot=config.snapshot(),
            publication_mode=config.publication.mode, deadline_epoch=None, plan_only=True,
        )
        controller = Controller(config, store=store, run_id=run_id, brain=args.brain,
                                reporter=_echo)
        controller.acquire()
        try:
            state = controller.execute(
                requested_phase=args.phase, plan_only=True,
            )
        finally:
            controller.release()

        _echo("")
        _echo(f"run {run_id}: {state.value} — {describe(state)}")
        spec_path = config.runs_dir() / run_id / "phase-spec.json"
        if spec_path.is_file():
            _echo(f"specification: {spec_path}")
            if args.show:
                _echo(spec_path.read_text(encoding="utf-8"))
            else:
                _summarise_spec(json.loads(spec_path.read_text(encoding="utf-8")))
        return 0 if state in (RunState.VERIFIED_LOCAL, RunState.WAITING_FOR_PLAN) else 1


def _summarise_spec(spec: dict) -> None:
    _echo("")
    _echo(f"  phase {spec['phase_id']}: {spec['phase_title']}")
    _echo(f"  {spec['summary'][:400]}")
    _echo(f"  {len(spec['requirements'])} requirements, {len(spec['non_goals'])} non-goals, "
          f"{len(spec['tasks'])} tasks, {len(spec['risks'])} risks")
    if spec["open_questions"]:
        _echo("  open questions:")
        for question in spec["open_questions"][:6]:
            _echo(f"    - {question['question'][:160]}")
    _echo("  tasks:")
    for task in spec["tasks"]:
        deps = f" after {','.join(task['depends_on'])}" if task["depends_on"] else ""
        _echo(f"    {task['id']} [{task['role']}]{deps}: {task['title'][:80]}")


# ------------------------------------------------------------------------ run
def cmd_run(args: argparse.Namespace) -> int:
    config = _config(args)
    imported_spec = None
    if args.spec:
        imported_spec = json.loads(Path(args.spec).read_text(encoding="utf-8"))
        try:
            validate_artifact(imported_spec, "phase_spec/v1")
        except SchemaError as exc:
            _echo(str(exc))
            return 2

    with _store(config) as store:
        run_id = store.create_run(
            brain=args.brain, config_snapshot=config.snapshot(),
            publication_mode=config.publication.mode,
            deadline_epoch=None, plan_only=False,
        )
        controller = Controller(config, store=store, run_id=run_id, brain=args.brain,
                                reporter=_echo)
        controller.acquire()
        try:
            state = controller.execute(
                requested_phase=args.phase, plan_only=False, imported_spec=imported_spec,
            )
        finally:
            controller.release()
        return _report_end(config, store, run_id, state)


def _report_end(config: Config, store: RunStore, run_id: str, state: RunState) -> int:
    _echo("")
    _echo(f"run {run_id}: {state.value} — {describe(state)}")
    row = store.get_run(run_id)
    if row["state_detail"]:
        _echo(f"  {row['state_detail']}")
    usage = store.usage_summary(run_id)
    cost = usage["cost_usd_known"]
    _echo(
        f"  usage: {usage['calls']} provider calls, "
        f"{usage['input_tokens']}/{usage['output_tokens']} tokens in/out, cost "
        + (f"${cost:.4f}" if cost is not None else "unknown")
        + (f" ({usage['calls_without_cost']} call(s) reported no cost)"
           if usage["calls_without_cost"] else "")
    )
    receipt = config.runs_dir() / run_id / "publication-receipt.json"
    if receipt.is_file():
        document = json.loads(receipt.read_text(encoding="utf-8"))
        _echo(f"  receipt: {receipt}")
        if document["published"]:
            _echo(f"  published {document['commit_sha'][:12]} to "
                  f"{document['remote']}/{document['branch']} "
                  f"(remote reads back {(document['remote_sha_after_push'] or '')[:12]})")
            _echo(f"  CI: {document['ci_status']}")
    return 0 if state in (RunState.COMPLETE, RunState.VERIFIED_LOCAL) else 1


# --------------------------------------------------------------------- status
def cmd_status(args: argparse.Namespace) -> int:
    config = _config(args)
    with _store(config) as store:
        if not args.run_id:
            rows = store.list_runs(limit=args.limit)
            if not rows:
                _echo("no runs recorded")
                return 0
            for row in rows:
                _echo(f"{row['run_id']}  {row['state']:<18} {row['brain']:<11} "
                      f"phase={row['phase_id'] or '-':<6} {row['created_at'][:19]}")
            return 0

        row = store.get_run(args.run_id)
        state = RunState(row["state"])
        _echo(f"run        {row['run_id']}")
        _echo(f"state      {state.value} — {describe(state)}")
        _echo(f"detail     {row['state_detail'] or '-'}")
        _echo(f"brain      {row['brain']}")
        _echo(f"phase      {row['phase_id'] or '-'}")
        _echo(f"base       {row['base_commit'] or '-'}")
        _echo(f"candidate  {row['candidate_fingerprint'] or '-'}")
        _echo(f"approved   {row['approved_fingerprint'] or '-'}")
        _echo(f"policy     publication={row['publication_mode']}")
        holder = store.run_lock_holder(args.run_id)
        _echo(f"lock       {'pid ' + str(holder['owner_pid']) + ' on ' + holder['hostname'] if holder else 'none'}")

        tasks = store.get_tasks(args.run_id)
        if tasks:
            _echo("")
            _echo("tasks:")
            for task in tasks:
                _echo(f"  {task['task_id']:<8} {task['state']:<12} {task['role']:<13} "
                      f"repairs={task['repair_rounds']}  {task['state_detail'] or ''}")

        evidence = store.evidence_for(args.run_id)
        if evidence:
            _echo("")
            _echo("verification evidence (controller-executed):")
            for record in evidence[-30:]:
                _echo(f"  {record['verification_id']:<26} {record['outcome']:<18} "
                      f"{(record['detail'] or '')[:90]}")

        usage = store.usage_summary(args.run_id)
        cost = usage["cost_usd_known"]
        _echo("")
        _echo(f"usage      {usage['calls']} calls, {usage['input_tokens']}/"
              f"{usage['output_tokens']} tokens, cost "
              + (f"${cost:.4f}" if cost is not None else "unknown")
              + (f" ({usage['calls_without_cost']} without a reported cost)"
                 if usage["calls_without_cost"] else ""))
        return 0


# ----------------------------------------------------------------------- logs
def cmd_logs(args: argparse.Namespace) -> int:
    config = _config(args)
    with _store(config) as store:
        events = store.events(args.run_id, since=args.since, limit=args.limit)
        for event in events:
            task = f" [{event['task_id']}]" if event["task_id"] else ""
            _echo(f"{event['seq']:>5} {event['at'][11:19]} {event['kind']:<26}{task} "
                  f"{event['message']}")
            if args.verbose and event["payload"]:
                _echo(f"      {event['payload']}")
    return 0


# ------------------------------------------------------- interactive handoff
def cmd_plan_export(args: argparse.Namespace) -> int:
    config = _config(args)
    with _store(config) as store:
        row = store.latest_artifact(args.run_id, "plan_request")
        if row is None:
            _echo(f"{args.run_id} has no plan request; it was not started with "
                  f"--brain interactive")
            return 1
        _echo(row["path"])
    return 0


def cmd_plan_import(args: argparse.Namespace) -> int:
    config = _config(args)
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    with _store(config) as store:
        row = store.get_run(args.run_id)
        if RunState(row["state"]) is not RunState.WAITING_FOR_PLAN:
            _echo(f"{args.run_id} is {row['state']}, not WAITING_FOR_PLAN")
            return 1
        try:
            validate_artifact(document, "phase_spec/v1")
        except SchemaError as exc:
            _echo(str(exc))
            return 2
        if document["base_commit"] != row["base_commit"]:
            _echo(f"this specification is written against {document['base_commit'][:12]} but "
                  f"the run's base is {row['base_commit'][:12]}")
            return 2

        controller = Controller(config, store=store, run_id=args.run_id,
                                brain="automatic", reporter=_echo)
        controller.acquire()
        try:
            controller.base_commit = row["base_commit"]
            controller.discover()
            controller.validate(document)
            if args.plan_only:
                store.set_run_state(
                    args.run_id, RunState.VERIFIED_LOCAL,
                    "an operator-supplied specification was validated; nothing was implemented",
                    force=True,
                )
                _echo("specification accepted")
                return 0
            controller.implement()
            controller.integrate_and_verify()
            verdict = controller.review()
            if verdict is None:
                return 0
            state = controller.publish(verdict)
        finally:
            controller.release()
        return _report_end(config, store, args.run_id, state)


def cmd_review_export(args: argparse.Namespace) -> int:
    config = _config(args)
    with _store(config) as store:
        row = store.latest_artifact(args.run_id, "review_request")
        if row is None:
            _echo(f"{args.run_id} has no review request yet")
            return 1
        if args.out:
            destination = Path(args.out)
            destination.write_bytes(Path(row["path"]).read_bytes())
            _echo(str(destination))
        else:
            _echo(row["path"])
    return 0


def cmd_review_import(args: argparse.Namespace) -> int:
    """Import an operator-supplied verdict.

    The verdict is accepted only through this command, and only when it names
    the exact candidate the run is holding. An approval of a different tree is
    stale and refused here rather than at commit time.
    """
    config = _config(args)
    document = json.loads(Path(args.path).read_text(encoding="utf-8"))
    with _store(config) as store:
        row = store.get_run(args.run_id)
        if RunState(row["state"]) is not RunState.WAITING_FOR_REVIEW:
            _echo(f"{args.run_id} is {row['state']}, not WAITING_FOR_REVIEW")
            return 1
        try:
            validate_artifact(document, "review_findings/v1")
        except SchemaError as exc:
            _echo(str(exc))
            return 2

        problems = []
        if document["run_id"] != args.run_id:
            problems.append(f"run id {document['run_id']} ≠ {args.run_id}")
        if document["base_commit"] != row["base_commit"]:
            problems.append(
                f"base commit {document['base_commit'][:12]} ≠ {row['base_commit'][:12]}")
        if document["candidate_fingerprint"] != row["candidate_fingerprint"]:
            problems.append(
                f"candidate fingerprint {document['candidate_fingerprint'][:20]} ≠ "
                f"{(row['candidate_fingerprint'] or '')[:20]}")
        if document["spec_digest"] != row["spec_digest"]:
            problems.append(
                f"specification digest {document['spec_digest'][:12]} ≠ "
                f"{(row['spec_digest'] or '')[:12]}")
        if problems:
            _echo("this review does not describe the candidate this run is holding:")
            for problem in problems:
                _echo(f"  - {problem}")
            _echo("Re-export with `pw-dev review-export` and review the current tree.")
            return 2

        store.put_json_artifact(args.run_id, "review", document)
        blockers = [f for f in document["findings"]
                    if f["severity"] in ("blocker", "major") and f["kind"] != "preference"]
        if document["verdict"] != "APPROVE" or blockers:
            store.set_run_state(
                args.run_id, RunState.NEEDS_FIX,
                f"imported review: {document['verdict']} with {len(blockers)} blocking "
                f"finding(s); resume to repair", force=True,
            )
            _echo(f"recorded {document['verdict']} with {len(blockers)} blocking finding(s)")
            return 0

        store.update_run_fields(args.run_id, approved_fingerprint=row["candidate_fingerprint"])
        store.set_run_state(args.run_id, RunState.REVIEW, "imported an approval for this candidate",
                            force=True)
        controller = Controller(config, store=store, run_id=args.run_id, brain="interactive",
                                reporter=_echo)
        controller.acquire()
        try:
            controller.base_commit = row["base_commit"]
            controller.spec_digest = row["spec_digest"]
            controller.candidate_fingerprint = row["candidate_fingerprint"]
            spec_path = config.runs_dir() / args.run_id / "phase-spec.json"
            controller.spec = json.loads(spec_path.read_text(encoding="utf-8"))
            state = controller.publish(document)
        finally:
            controller.release()
        return _report_end(config, store, args.run_id, state)


# --------------------------------------------------------------------- resume
def cmd_resume(args: argparse.Namespace) -> int:
    config = _config(args)
    with _store(config) as store:
        report = reconcile(config, store, args.run_id)
        _echo(report.render())
        if not report.resumable:
            _echo("")
            _echo("this run cannot be resumed right now")
            return 1
        if args.dry_run:
            return 0

        # A resumed run is judged by the configuration it was started with.
        # Editing pw-dev.toml while it was paused must not widen its permissions
        # or relax its gates.
        row = store.get_run(args.run_id)
        frozen = Config.from_snapshot(json.loads(row["config_json"]))
        _echo("")
        _echo(f"resuming under the configuration this run was started with "
              f"(publication={frozen.publication.mode}, "
              f"profile={frozen.verification_profile})")

        controller = Controller(frozen, store=store, run_id=args.run_id,
                                brain=row["brain"], reporter=_echo)
        controller.acquire()
        try:
            state = controller.resume()
        finally:
            controller.release()
        return _report_end(frozen, store, args.run_id, state)


def cmd_cancel(args: argparse.Namespace) -> int:
    config = _config(args)
    with _store(config) as store:
        row = store.get_run(args.run_id)
        state = RunState(row["state"])
        if state in (RunState.COMPLETE, RunState.CANCELLED, RunState.FAILED):
            _echo(f"{args.run_id} is already {state.value}")
            return 0
        store.set_run_state(
            args.run_id, RunState.CANCELLED,
            "cancelled by the operator; worktrees and artifacts are preserved", force=True,
        )
        _echo(f"{args.run_id} cancelled. Worktrees and artifacts under "
              f"{config.runs_dir() / args.run_id} were preserved.")
    return 0


def cmd_checks(args: argparse.Namespace) -> int:
    from .verify.registry import Registry

    registry = Registry()
    for check_id, description in registry.describe():
        gate = " [gate]" if registry.get(check_id).gate else ""
        _echo(f"{check_id}{gate}\n    {description}")
    return 0


def cmd_schemas(args: argparse.Namespace) -> int:
    from .schemas import SCHEMA_IDS, schema_path

    for schema_id in sorted(SCHEMA_IDS):
        _echo(f"{schema_id}\n    {schema_path(schema_id)}")
    return 0


# ----------------------------------------------------------------- arg parser
def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="pw-dev",
        description="Pipewright's development orchestrator: an OpenAI planner and reviewer, "
                    "Claude implementers, and a deterministic controller that owns state, "
                    "verification and publication.",
    )
    parser.add_argument("--repo", help="repository root (default: the enclosing Git repository)")
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="report what this machine can actually do")
    doctor.add_argument("--probe", action="store_true",
                        help="make one small real call to each provider")
    doctor.add_argument("--probe-timeout", type=float, default=240.0)
    doctor.set_defaults(func=cmd_doctor)

    plan = sub.add_parser("plan", help="produce a phase specification and stop")
    plan.add_argument("--next", dest="phase", nargs="?", const=None, default=None,
                      help="plan the next eligible phase (default), or name one: --next 18")
    plan.add_argument("--phase", dest="phase", help="plan a specific phase")
    plan.add_argument("--brain", choices=("automatic", "interactive"), default="automatic")
    plan.add_argument("--show", action="store_true", help="print the full specification")
    plan.add_argument("--planner-model")
    plan.set_defaults(func=cmd_plan, publish="none")

    run = sub.add_parser("run", help="plan, implement, verify, review and publish one phase")
    run.add_argument("--next", dest="phase", nargs="?", const=None, default=None)
    run.add_argument("--phase", dest="phase")
    run.add_argument("--spec", help="use an existing phase specification instead of planning")
    run.add_argument("--brain", choices=("automatic", "interactive"), default="automatic")
    run.add_argument("--publish", choices=("none", "local", "feature-branch"), default="none")
    run.add_argument("--branch", help="publish to this existing branch (must be authorised)")
    run.add_argument("--max-workers", type=int)
    run.add_argument("--unattended", action="store_true",
                     help="no operator present; refused unless writes can be confined")
    run.add_argument("--planner-model")
    run.add_argument("--implementer-model")
    run.add_argument("--reviewer-model")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="show a run, or list runs")
    status.add_argument("run_id", nargs="?")
    status.add_argument("--limit", type=int, default=20)
    status.set_defaults(func=cmd_status)

    logs = sub.add_parser("logs", help="the append-only event log for a run")
    logs.add_argument("run_id")
    logs.add_argument("--since", type=int, default=0)
    logs.add_argument("--limit", type=int, default=500)
    logs.add_argument("--verbose", action="store_true")
    logs.set_defaults(func=cmd_logs)

    plan_export = sub.add_parser("plan-export", help="path to the planning packet for an interactive run")
    plan_export.add_argument("run_id")
    plan_export.set_defaults(func=cmd_plan_export)

    plan_import = sub.add_parser("plan-import", help="supply a specification for a waiting run")
    plan_import.add_argument("run_id")
    plan_import.add_argument("path")
    plan_import.add_argument("--plan-only", action="store_true")
    plan_import.add_argument("--publish", choices=("none", "local", "feature-branch"), default="none")
    plan_import.set_defaults(func=cmd_plan_import)

    review_export = sub.add_parser("review-export", help="export the review packet for a run")
    review_export.add_argument("run_id")
    review_export.add_argument("--out", help="write the packet here instead of printing its path")
    review_export.set_defaults(func=cmd_review_export)

    review_import = sub.add_parser("review-import", help="supply a review verdict for a waiting run")
    review_import.add_argument("run_id")
    review_import.add_argument("path")
    review_import.add_argument("--publish", choices=("none", "local", "feature-branch"), default="none")
    review_import.set_defaults(func=cmd_review_import)

    resume = sub.add_parser("resume", help="reconcile and continue a stopped run")
    resume.add_argument("run_id")
    resume.add_argument("--dry-run", action="store_true", help="reconcile and report only")
    resume.set_defaults(func=cmd_resume)

    cancel = sub.add_parser("cancel", help="stop a run, preserving its work")
    cancel.add_argument("run_id")
    cancel.set_defaults(func=cmd_cancel)

    checks = sub.add_parser("checks", help="list the verification registry")
    checks.set_defaults(func=cmd_checks)

    schemas = sub.add_parser("schemas", help="list the artifact schemas")
    schemas.set_defaults(func=cmd_schemas)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except PwDevError as error:
        print(f"pw-dev: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\npw-dev: interrupted; state is preserved and the run can be resumed",
              file=sys.stderr)
        return 130


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
