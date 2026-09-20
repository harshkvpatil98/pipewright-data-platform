"""Claude implementation workers, over `claude -p`.

Verified against Claude Code 2.1.231 on 2026-09-17, from `claude --help` on the
installed build:

* `--output-format json` returns one result object; `--json-schema` constrains
  its `result` field;
* `--tools` selects from the built-in set, and `--disallowed-tools` removes
  specific ones. Delegation tools are removed for every worker: a worker that
  can spawn its own agents evades the controller's concurrency and budget
  limits, which is exactly what those limits exist to prevent;
* `--setting-sources ""` stops user, project and local settings from loading, so
  an orchestrated worker does not silently inherit hooks or plugins that the
  operator enabled for interactive use;
* `--strict-mcp-config` with an empty `--mcp-config` disables MCP entirely;
* `--permission-mode acceptEdits` lets a worker edit files without turning off
  permission checks. `--dangerously-skip-permissions` is never passed.

Authentication: this adapter uses the interactive subscription route (OAuth,
resolved through the OS keychain on macOS). It deliberately does *not* pass
`--bare`, which the current documentation describes as an API-key route that
never reads the subscription login -- passing it would silently move the run onto
billable API authentication.

Two observed behaviours the controller depends on:

1. `claude -p` can exit **1** while writing a complete, well-formed result
   object -- "Not logged in · Please run /login" arrives that way, with
   `subtype: "success"` and `is_error: true`. Reading `is_error` matters more
   than reading the exit status.
2. The child needs `USER`, `LOGNAME` and `SHELL` in its environment as well as
   `HOME`; with only `PATH` and `HOME` the keychain lookup fails and it reports
   itself as logged out.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from ..config import ProviderConfig
from ..schemas import load_schema
from ..schemas.validate import SchemaError, validate_artifact
from ..util import proc
from ..util.redact import redact
from .base import FailureKind, ProviderResult, Usage

#: Where Claude Code keeps its configuration by default. The *account* file is
#: `~/.claude.json`, one level above this directory.
DEFAULT_CONFIG_DIR = Path(os.path.expanduser("~/.claude"))

#: Tools an implementation worker gets. `Task`/`Agent` are absent on purpose:
#: nested agents would spawn outside the controller's accounting.
WORKER_TOOLS = ("Read", "Write", "Edit", "Glob", "Grep", "Bash", "NotebookEdit", "TodoWrite")

#: Tools a read-only worker (analysis, context gathering) gets.
READONLY_TOOLS = ("Read", "Glob", "Grep")

#: Removed from every worker regardless of the selected set.
DENIED_TOOLS = (
    "Task", "Agent", "WebFetch", "WebSearch", "Artifact",
    "SlashCommand", "KillShell", "BashOutput",
)

_AUTH_HINTS = re.compile(
    r"(?i)(not logged in|please run /login|invalid api key|authentication_error|"
    r"unauthori[sz]ed|oauth token (?:has )?expired|401)"
)
_RATE_HINTS = re.compile(
    r"(?i)(rate[_ ]?limit|429|usage limit reached|quota exceeded|overloaded_error|529)"
)
_MODEL_HINTS = re.compile(
    r"(?i)(model .* (?:not found|not available|unavailable)|unknown model|"
    r"not_found_error.*model|does not have access to (?:the )?model)"
)


class ClaudeCliAdapter:
    """Drives `claude -p` for implementation, verification and repair workers."""

    name = "claude"

    def __init__(self, config: ProviderConfig) -> None:
        self.config = config

    def invoke(
        self,
        *,
        role: str,
        prompt: str,
        cwd: Path,
        timeout: float,
        schema_id: str | None = None,
        writable: bool = True,
        allowed_write_roots: list[Path] | None = None,
        max_output_bytes: int = 8 * 1024 * 1024,
        on_event: Callable[[dict], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        system_prompt: str | None = None,
        config_dir: Path | None = None,
        sandbox_wrapper: Callable[[list[str]], list[str]] | None = None,
        max_budget_usd: float | None = None,
        tmp_dir: Path | None = None,
    ) -> ProviderResult:
        cwd = Path(cwd)
        # The operator's real configuration directory by default: subscription
        # login does not resolve through a fresh one. The caller is responsible
        # for confining what a worker may change inside it.
        config_dir = Path(
            config_dir or os.environ.get("CLAUDE_CONFIG_DIR", os.path.expanduser("~/.claude"))
        )
        config_dir.mkdir(parents=True, exist_ok=True)
        scratch = cwd / ".pw-dev-scratch"
        scratch.mkdir(parents=True, exist_ok=True)

        tools = WORKER_TOOLS if writable else READONLY_TOOLS
        argv = [
            self.config.executable, "-p",
            "--output-format", "json",
            # `acceptEdits` auto-accepts file edits and still sends every Bash
            # command to the permission system. Claude Code waves through what
            # it can prove is read-only -- `cat`, `echo` -- and asks for the
            # rest, which is exactly the set a worker needs: running a test is
            # arbitrary execution. Headless, there is nobody to ask, so the
            # answer was always "This command requires approval" and `Bash`
            # was a tool workers held and could not use.
            #
            # The boundary is not this flag. It is the seatbelt profile the
            # controller wraps the whole process in, which a worker cannot
            # negotiate with: `test_isolation.py` runs a real shell under it
            # and shows the repository and the operator's home still refusing
            # writes. A worker that may edit a file it cannot run is not safer,
            # only blinder -- it edits code it cannot test and reports guesses.
            "--permission-mode", "bypassPermissions" if writable else "manual",
            "--tools", *tools,
            "--disallowed-tools", *DENIED_TOOLS,
            # No user/project/local settings: no inherited hooks, plugins or
            # permission grants the controller did not account for.
            "--setting-sources", "",
            "--strict-mcp-config",
            "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands",
            "--no-session-persistence",
            "--exclude-dynamic-system-prompt-sections",
        ]
        if self.config.model:
            argv += ["--model", self.config.model]
        if self.config.reasoning_effort:
            argv += ["--effort", self.config.reasoning_effort]
        if schema_id:
            argv += ["--json-schema", _inline_schema(schema_id)]
        if system_prompt:
            argv += ["--append-system-prompt", system_prompt]
        for root in allowed_write_roots or []:
            if Path(root).resolve() != cwd.resolve():
                argv += ["--add-dir", str(root)]
        if max_budget_usd is not None:
            argv += ["--max-budget-usd", str(max_budget_usd)]
        argv += list(self.config.extra_args)
        argv.append(prompt)

        if sandbox_wrapper is not None:
            argv = sandbox_wrapper(argv)

        temp_dir = Path(tmp_dir) if tmp_dir else (scratch / "tmp")
        temp_dir.mkdir(parents=True, exist_ok=True)
        overrides = {"TMPDIR": str(temp_dir)}
        # Only set CLAUDE_CONFIG_DIR when it is *not* the default location.
        # Setting it explicitly changes where the account file is looked for --
        # `$CLAUDE_CONFIG_DIR/.claude.json` rather than `~/.claude.json`, which
        # is one level up -- and the CLI then reports "Not logged in" even
        # though nothing about the login changed.
        if config_dir.resolve() != DEFAULT_CONFIG_DIR.resolve():
            overrides["CLAUDE_CONFIG_DIR"] = str(config_dir)
        env = proc.build_env(overrides=overrides)

        result = proc.run(
            argv, cwd=cwd, env=env, timeout=timeout, stdin_data=None,
            max_output_bytes=max_output_bytes, cancel_check=cancel_check,
        )
        return self._interpret(role, result, schema_id, on_event)

    # ------------------------------------------------------------ interpreting
    def _interpret(
        self, role: str, result: proc.ProcResult, schema_id: str | None,
        on_event: Callable[[dict], None] | None,
    ) -> ProviderResult:
        base = dict(
            role=role, provider=self.name, exit_status=result.returncode,
            duration_seconds=result.duration_seconds, argv=result.argv,
            stderr_tail=redact(result.stderr[-4000:]),
            resolved_model=self.config.model,
        )

        if result.cancelled:
            return ProviderResult(ok=False, failure_kind=FailureKind.CANCELLED, data=None,
                                  text=None, detail="cancelled by the controller", **base)
        if result.timed_out:
            return ProviderResult(
                ok=False, failure_kind=FailureKind.TIMEOUT, data=None, text=None,
                detail=(
                    f"no result within {result.duration_seconds:.0f}s; the process group was "
                    "terminated. The worktree may already contain partial edits and is "
                    "reconciled rather than assumed untouched."
                ),
                **base,
            )

        envelope = _parse_envelope(result.stdout)
        if envelope is None:
            combined = f"{result.stdout}\n{result.stderr}"
            kind = _classify(combined)
            if kind == FailureKind.UNKNOWN:
                kind = (
                    FailureKind.MALFORMED_OUTPUT if result.returncode == 0
                    else FailureKind.NONZERO_EXIT
                )
            return ProviderResult(
                ok=False, failure_kind=kind, data=None, text=None,
                detail=(
                    f"no parseable result object on stdout (exit {result.returncode}); "
                    f"first bytes: {redact(result.stdout[:400])!r}"
                ),
                **base,
            )
        if on_event is not None:
            on_event(envelope)

        usage = _usage_from_envelope(envelope, self.config.model)
        base["usage"] = usage
        base["session_id"] = envelope.get("session_id")
        base["raw_events"] = [_strip_envelope(envelope)]
        if usage.model:
            base["resolved_model"] = usage.model

        text = envelope.get("result")
        if not isinstance(text, str):
            text = None

        # `is_error` is authoritative, and it does not track the exit status:
        # the "Not logged in" envelope arrives with exit 1, subtype "success"
        # and is_error true.
        if envelope.get("is_error") or envelope.get("subtype") in ("error_during_execution",
                                                                   "error_max_turns"):
            message = text or str(envelope.get("subtype") or "the worker reported an error")
            kind = _classify(message + " " + str(envelope.get("terminal_reason", "")))
            if kind == FailureKind.UNKNOWN:
                kind = (
                    FailureKind.EXIT_ZERO_ERROR if result.returncode == 0
                    else FailureKind.NONZERO_EXIT
                )
            return ProviderResult(ok=False, failure_kind=kind, data=None, text=text,
                                  detail=redact(message)[:2000], **base)

        denials = envelope.get("permission_denials") or []
        if denials and not text:
            return ProviderResult(
                ok=False, failure_kind=FailureKind.REFUSAL, data=None, text=None,
                detail=f"the worker produced nothing and was denied {len(denials)} tool calls",
                **base,
            )

        if result.returncode not in (0, None):
            return ProviderResult(
                ok=False, failure_kind=FailureKind.NONZERO_EXIT, data=None, text=text,
                detail=f"exit {result.returncode} with no reported error in the result object",
                **base,
            )

        if text is None:
            return ProviderResult(ok=False, failure_kind=FailureKind.MALFORMED_OUTPUT,
                                  data=None, text=None,
                                  detail="the result object carried no result text", **base)

        if schema_id is None:
            return ProviderResult(ok=True, failure_kind=FailureKind.NONE, data=None,
                                  text=text, detail="", **base)

        document = _extract_json(text)
        if document is None:
            return ProviderResult(
                ok=False, failure_kind=FailureKind.MALFORMED_OUTPUT, data=None, text=text,
                detail="the result was not parseable JSON despite --json-schema",
                **base,
            )
        try:
            validate_artifact(document, schema_id)
        except SchemaError as exc:
            return ProviderResult(ok=False, failure_kind=FailureKind.SCHEMA_INVALID,
                                  data=document, text=text, detail=str(exc)[:4000], **base)
        return ProviderResult(ok=True, failure_kind=FailureKind.NONE, data=document,
                              text=text, detail="", **base)

    # ------------------------------------------------------------------ probe
    def probe(self, *, timeout: float = 180.0, scratch_dir: Path | None = None) -> ProviderResult:
        import tempfile

        scratch = Path(scratch_dir or tempfile.mkdtemp(prefix="pw-dev-claude-probe-"))
        workdir = scratch / "wd"
        workdir.mkdir(parents=True, exist_ok=True)
        config_dir = scratch / "config"
        config_dir.mkdir(parents=True, exist_ok=True)
        tmp = scratch / "tmp"
        tmp.mkdir(parents=True, exist_ok=True)

        argv = [
            self.config.executable, "-p",
            "--output-format", "json",
            "--tools", "",
            "--permission-mode", "manual",
            "--setting-sources", "",
            "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}',
            "--disable-slash-commands", "--no-session-persistence",
        ]
        if self.config.model:
            argv += ["--model", self.config.model]
        # The prompt is positional and goes last, after every flag.
        argv.append("Reply with exactly: PW_DEV_PROBE")

        # The probe intentionally uses the real config directory: a fresh
        # CLAUDE_CONFIG_DIR reports "Not logged in" even when the operator is
        # signed in, so probing a throwaway directory would answer the wrong
        # question.
        env = proc.build_env(overrides={"TMPDIR": str(tmp)})
        try:
            result = proc.run(argv, cwd=workdir, env=env, timeout=timeout,
                              max_output_bytes=1 << 20)
        except FileNotFoundError as exc:
            return ProviderResult(
                role="probe", provider=self.name, ok=False,
                failure_kind=FailureKind.EXECUTABLE_MISSING, data=None, text=None,
                detail=str(exc),
            )
        outcome = self._interpret("probe", result, None, None)
        if outcome.ok and outcome.text and "PW_DEV_PROBE" not in outcome.text:
            outcome.ok = False
            outcome.failure_kind = FailureKind.MALFORMED_OUTPUT
            outcome.detail = "the probe response did not contain the requested token"
        return outcome

    def version(self) -> str | None:
        try:
            result = proc.run(
                [self.config.executable, "--version"], cwd=Path.cwd(),
                env=proc.build_env(), timeout=60, max_output_bytes=1 << 16,
            )
        except (FileNotFoundError, OSError):
            return None
        return (result.stdout or result.stderr).strip() or None


def _inline_schema(schema_id: str) -> str:
    """Render a schema for `--json-schema`, without its meta-schema declaration.

    Claude Code validates the supplied schema against its own registry and
    rejects `$schema: "https://json-schema.org/draft/2020-12/schema"` outright:

        Error: --json-schema is not a valid JSON Schema: no schema with key or
        ref "https://json-schema.org/draft/2020-12/schema"

    The declaration is only useful to a human reading the file, so it and `$id`
    are dropped on the way to the CLI. The document on disk keeps both.
    """
    schema = {k: v for k, v in load_schema(schema_id).items() if k not in ("$schema", "$id")}
    return json.dumps(schema, separators=(",", ":"))


def _parse_envelope(stdout: str) -> dict | None:
    """Find the single result object `--output-format json` writes."""
    stdout = stdout.strip()
    if not stdout:
        return None
    try:
        document = json.loads(stdout)
    except json.JSONDecodeError:
        # Tolerate a leading banner: take the last complete JSON object.
        start = stdout.find("{")
        while start != -1:
            try:
                document = json.loads(stdout[start:])
            except json.JSONDecodeError:
                start = stdout.find("{", start + 1)
                continue
            break
        else:
            return None
    if isinstance(document, list):
        document = next((d for d in reversed(document) if isinstance(d, dict)
                         and d.get("type") == "result"), None)
    if not isinstance(document, dict):
        return None
    return document


def _strip_envelope(envelope: dict) -> dict:
    """The envelope minus its body, for the event log."""
    return {
        key: envelope.get(key)
        for key in ("type", "subtype", "is_error", "num_turns", "duration_ms",
                    "duration_api_ms", "terminal_reason", "session_id", "permission_denials")
        if key in envelope
    }


def _usage_from_envelope(envelope: dict, configured_model: str | None) -> Usage:
    usage = envelope.get("usage") or {}
    model_usage = envelope.get("modelUsage") or {}
    # A session touches more than one model: a small one handles routing while
    # the configured one does the work. Reporting whichever emitted the most
    # tokens picks the router on a short answer, so the configured model wins
    # whenever it appears -- that is the one the run was configured to use, and
    # the one a person means by "which model ran this".
    model = configured_model
    if isinstance(model_usage, dict) and model_usage:
        alias = (configured_model or "").lower()
        matched = next(
            (name for name in model_usage
             if alias and (alias in name.lower()
                           or alias in str((model_usage[name] or {}).get("canonicalModel", "")).lower())),
            None,
        )
        model = matched or max(
            model_usage.items(),
            key=lambda item: (item[1] or {}).get("outputTokens", 0) if isinstance(item[1], dict) else 0,
        )[0]
    cost = envelope.get("total_cost_usd")
    return Usage(
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
        cached_input_tokens=usage.get("cache_read_input_tokens"),
        cost_usd=float(cost) if isinstance(cost, (int, float)) and cost > 0 else None,
        model=model,
    )


def _classify(text: str) -> str:
    if not text:
        return FailureKind.UNKNOWN
    if _MODEL_HINTS.search(text):
        return FailureKind.MODEL_UNAVAILABLE
    if _AUTH_HINTS.search(text):
        return FailureKind.AUTH
    if _RATE_HINTS.search(text):
        return FailureKind.RATE_LIMITED
    return FailureKind.UNKNOWN


def _extract_json(text: str) -> Any | None:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            body = "\n".join(lines[1:])
            if body.rstrip().endswith("```"):
                body = body.rstrip()[:-3]
            text = body.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            return None
    return None
