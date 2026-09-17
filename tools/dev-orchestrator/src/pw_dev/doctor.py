"""`pw-dev doctor`: what this machine can actually do.

Two sections, kept apart on purpose:

* **offline inspection** — executables, versions, configured models, repository
  state, isolation mechanism, whether an auth *file* or keychain entry exists.
  All of it is free and none of it proves anything about entitlement;
* **live probe** — a tiny, bounded, real call to each provider. Only this
  section can say a model is reachable. An installed CLI does not establish
  authentication, an authenticated CLI does not establish access to a specific
  model, and neither is inferred here.

`gpt-6-astra` is the working example: it is what the operator's Codex config
names, and `codex exec` on the installed CLI rejects it with an HTTP 400 saying
it needs a newer build. Reported from configuration alone it would look fine.
"""

from __future__ import annotations

import os
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path

from .config import Config
from .providers.claude_cli import ClaudeCliAdapter
from .providers.codex_cli import CodexCliAdapter
from .schemas.validate import validator_backend
from .verify.registry import Registry
from .workspace import git
from .workspace.sandbox import detect_sandbox_support, resolve_mode


@dataclass
class Finding:
    name: str
    status: str            # ok | warn | fail | unknown
    detail: str

    def render(self) -> str:
        mark = {"ok": "ok  ", "warn": "warn", "fail": "FAIL", "unknown": "?   "}[self.status]
        return f"  [{mark}] {self.name}: {self.detail}"


@dataclass
class DoctorReport:
    offline: list[Finding] = field(default_factory=list)
    live: list[Finding] = field(default_factory=list)
    live_probed: bool = False

    @property
    def ok(self) -> bool:
        return not any(f.status == "fail" for f in (*self.offline, *self.live))

    def render(self) -> str:
        lines = ["Offline inspection (no provider calls):"]
        lines += [f.render() for f in self.offline]
        lines.append("")
        if self.live_probed:
            lines.append("Live provider probe (a real, bounded call to each provider):")
            lines += [f.render() for f in self.live]
        else:
            lines.append(
                "Live provider probe: not run. Pass --probe to make a real bounded call.\n"
                "  Until then, nothing here establishes authentication, entitlement, or that\n"
                "  a configured model is available."
            )
        return "\n".join(lines)


def run_doctor(config: Config, *, probe: bool = False, probe_timeout: float = 240.0) -> DoctorReport:
    report = DoctorReport()
    add = report.offline.append

    add(Finding("python", "ok" if sys.version_info >= (3, 11) else "fail",
                f"{sys.version.split()[0]} at {sys.executable} "
                f"(this tool requires 3.11+, matching the repository)"))
    add(Finding("schema validation", "ok",
                f"{validator_backend()} "
                f"({'reference implementation' if validator_backend() == 'jsonschema' else 'bundled stdlib validator'})"))

    for role, provider in (("planner", config.planner), ("implementer", config.implementer),
                           ("reviewer", config.reviewer)):
        path = shutil.which(provider.executable)
        if path is None:
            add(Finding(f"{role} executable", "fail",
                        f"{provider.executable!r} is not on PATH"))
            continue
        adapter = (
            ClaudeCliAdapter(provider) if provider.executable.endswith("claude")
            else CodexCliAdapter(provider)
        )
        version = adapter.version() or "unknown"
        add(Finding(f"{role} executable", "ok", f"{provider.executable} {version} at {path}"))
        add(Finding(
            f"{role} model", "ok" if provider.model else "warn",
            f"configured as {provider.model!r}" if provider.model else
            "not configured; the CLI's own default will be used and recorded per run",
        ))

    codex = CodexCliAdapter(config.planner)
    auth_mode = codex.auth_mode()
    if auth_mode is None:
        add(Finding("codex authentication", "fail",
                    f"no auth file under {codex.codex_home}; run `codex login`"))
    elif auth_mode == "api_key":
        add(Finding("codex authentication", "ok",
                    "an API key is stored (billable API route). No key value is read here."))
    else:
        add(Finding("codex authentication", "ok",
                    f"auth mode {auth_mode!r} (subscription/OAuth). No token value is read here."))

    claude_home = Path(os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude")))
    has_api_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    add(Finding(
        "claude authentication route", "ok",
        (
            "subscription/OAuth via the interactive login. This tool does not pass --bare, "
            "which the current documentation describes as an API-key route that never reads "
            "the subscription login; switching to it would silently move the run onto "
            "billable API authentication."
            + (" ANTHROPIC_API_KEY is set in this environment and is deliberately stripped "
               "from worker environments." if has_api_key else "")
        ),
    ))
    add(Finding("claude config directory", "ok" if claude_home.exists() else "warn",
                f"{claude_home}" + ("" if claude_home.exists() else " (missing)")))

    support = detect_sandbox_support(probe=True)
    try:
        mode = resolve_mode(config.isolation.mode, support)
    except RuntimeError as exc:
        mode = "unavailable"
        add(Finding("isolation", "fail", str(exc)))
    else:
        status = "ok" if mode in ("enforced", "off") else "warn"
        add(Finding("isolation", status, f"mode={mode}; {support.describe()}"))
        if mode == "supervised":
            add(Finding(
                "unattended execution", "warn",
                "refused on this host: writes cannot be confined, so a worker is not "
                "prevented from writing outside its checkout. Supervised runs are supported; "
                "set isolation.allow_supervised_unattended to override after reading what "
                "that means.",
            ))

    add(Finding("git worktrees", "ok" if _worktrees_supported(config.repo_root) else "fail",
                "supported" if _worktrees_supported(config.repo_root) else
                "`git worktree` is unavailable in this repository"))

    try:
        state = git.capture_state(config.repo_root)
    except Exception as exc:  # noqa: BLE001 - reported rather than raised
        add(Finding("repository", "fail", f"could not read: {exc}"))
    else:
        add(Finding("repository", "ok",
                    f"{config.repo_root} at {state.head_sha[:12]} on {state.branch}"))
        dirt = len(state.dirty_paths) + len(state.untracked_paths)
        add(Finding(
            "working tree", "ok" if dirt == 0 else "warn",
            "clean" if dirt == 0 else
            f"{len(state.dirty_paths)} modified, {len(state.untracked_paths)} untracked. "
            f"These are recorded and left alone; runs work from the committed base.",
        ))
        remote = state.remotes.get(config.publication.remote)
        add(Finding(f"remote {config.publication.remote!r}", "ok" if remote else "warn",
                    remote or "not configured; publication would be refused"))

        from .publish.identity import inspect_identity

        identity = inspect_identity(
            config.repo_root, expected_name=config.publication.author_name,
            expected_email=config.publication.author_email,
        )
        add(Finding(
            "git identity", "ok" if identity.ok else "warn",
            f"{identity.local_name} <{identity.local_email}>" if identity.ok else
            "; ".join(identity.problems),
        ))
        if identity.env_overrides:
            add(Finding(
                "git identity environment", "warn",
                f"{sorted(identity.env_overrides)} are set in this shell. They are stripped "
                f"from every child process and overridden explicitly on commit, so they "
                f"cannot re-author a commit made by this tool.",
            ))
        if identity.signing_required:
            add(Finding("commit signing", "ok" if not identity.problems else "fail",
                        f"required ({identity.signing_format}); key "
                        f"{identity.signing_key or 'not configured'}"))

    registry = Registry()
    venv = config.repo_root / ".venv" / "bin" / "python"
    node_modules = config.repo_root / "node_modules"
    add(Finding("python venv", "ok" if venv.exists() else "warn",
                str(venv) if venv.exists() else
                f"missing at {venv}; python checks would record 'not_run', not 'pass'"))
    add(Finding("node_modules", "ok" if node_modules.is_dir() else "warn",
                str(node_modules) if node_modules.is_dir() else
                f"missing at {node_modules}; web checks would record 'not_run', not 'pass'"))
    add(Finding("verification registry", "ok",
                f"{len(registry.ids())} checks, {len(registry.gates())} of them gates"))

    add(Finding("publication policy", "ok",
                f"mode={config.publication.mode}, remote={config.publication.remote}, "
                f"branch prefix={config.publication.branch_prefix!r}, protected="
                f"{list(config.publication.protected_branches)}"))
    add(Finding("limits", "ok",
                f"{config.limits.max_parallel_workers} parallel workers, "
                f"{config.limits.per_task_seconds}s/task, {config.limits.total_run_seconds}s/run, "
                f"{config.limits.repair_rounds_per_task} repair rounds"))

    if not probe:
        return report

    report.live_probed = True
    import tempfile

    with tempfile.TemporaryDirectory(prefix="pw-dev-doctor-") as scratch:
        base = Path(scratch)
        codex_result = CodexCliAdapter(config.planner).probe(
            timeout=probe_timeout, scratch_dir=base / "codex",
        )
        report.live.append(Finding(
            "codex live call", "ok" if codex_result.ok else "fail",
            (
                f"answered in {codex_result.duration_seconds:.1f}s; model "
                f"{codex_result.resolved_model or 'the CLI default'}; "
                f"tokens in/out {codex_result.usage.input_tokens}/"
                f"{codex_result.usage.output_tokens}; cost not reported by this provider"
            ) if codex_result.ok else
            f"{codex_result.failure_kind}: {codex_result.detail}",
        ))

        claude_result = ClaudeCliAdapter(config.implementer).probe(
            timeout=probe_timeout, scratch_dir=base / "claude",
        )
        report.live.append(Finding(
            "claude live call", "ok" if claude_result.ok else "fail",
            (
                f"answered in {claude_result.duration_seconds:.1f}s; model "
                f"{claude_result.usage.model or claude_result.resolved_model}; "
                f"tokens in/out {claude_result.usage.input_tokens}/"
                f"{claude_result.usage.output_tokens}; cost "
                + (f"${claude_result.usage.cost_usd:.4f}" if claude_result.usage.cost_known
                   else "not reported")
            ) if claude_result.ok else
            f"{claude_result.failure_kind}: {claude_result.detail}",
        ))
    return report


def _worktrees_supported(repo_root: Path) -> bool:
    try:
        git.git(repo_root, ["worktree", "list"], check=False, timeout=60)
    except Exception:  # noqa: BLE001
        return False
    return True
