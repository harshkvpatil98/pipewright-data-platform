"""OpenAI planner and reviewer, over `codex exec`.

Verified against codex-cli 0.149.1 on 2026-09-17. The flags used here were read
from `codex exec --help` on the installed build rather than from documentation:

* `--json` emits JSONL events (`thread.started`, `turn.started`,
  `item.completed`, `turn.completed`, `error`, `turn.failed`);
* `--output-schema FILE` constrains the final message to a JSON Schema;
* `-o FILE` writes that final message, which is how a *parsed final result* is
  told apart from the last thing that happened to appear on the stream;
* `-s read-only` is Codex's own sandbox for commands the model runs -- planning
  and review never write to the repository;
* `--ignore-user-config` and `--ignore-rules` keep the operator's plugins, MCP
  servers and execpolicy rules out of an orchestrated run. Authentication still
  resolves from `CODEX_HOME`, so this does not change the auth route.

Two behaviours are worth stating because they cost real debugging time:

1. `codex exec` reads stdin when stdin is a pipe, prints "Reading additional
   input from stdin..." and waits for EOF. Every invocation binds stdin.
2. A model name the installed CLI does not know fails at the API with HTTP 400,
   not at argument parsing. The operator's `~/.codex/config.toml` named
   `gpt-6-astra`, which this CLI rejects with "requires a newer version of
   Codex" -- which is exactly why the resolved model is recorded per run instead
   of assumed from configuration.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable

from ..config import ProviderConfig
from ..schemas import schema_path
from ..schemas.validate import SchemaError, validate_artifact
from ..util import proc
from ..util.redact import redact
from .base import FailureKind, ProviderResult, Usage

_AUTH_HINTS = re.compile(
    r"(?i)\b(not logged in|please run .?codex login|unauthori[sz]ed|401|"
    r"invalid[_ ]api[_ ]key|authentication)\b"
)
_RATE_HINTS = re.compile(r"(?i)\b(rate[_ ]?limit|429|quota|usage limit|too many requests)\b")
_MODEL_HINTS = re.compile(
    r"(?i)(model .* (not found|requires a newer version|is not available|does not exist)|"
    r"unknown model|model_not_found)"
)
_REFUSAL_HINTS = re.compile(
    r"(?i)\b(i (?:can't|cannot|won't) (?:help|assist|comply)|refus(?:e|ing|al))\b"
)


class CodexCliAdapter:
    """Drives `codex exec` for the planner and the reviewer roles."""

    name = "codex"

    def __init__(self, config: ProviderConfig, *, codex_home: Path | None = None) -> None:
        self.config = config
        self.codex_home = Path(codex_home) if codex_home else Path(os.path.expanduser("~/.codex"))

    # ------------------------------------------------------------------ calls
    def invoke(
        self,
        *,
        role: str,
        prompt: str,
        cwd: Path,
        timeout: float,
        schema_id: str | None = None,
        writable: bool = False,
        allowed_write_roots: list[Path] | None = None,
        max_output_bytes: int = 8 * 1024 * 1024,
        on_event: Callable[[dict], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
        system_prompt: str | None = None,
        scratch_dir: Path | None = None,
    ) -> ProviderResult:
        if writable:
            # The planner and reviewer are read-only with respect to application
            # code by design. A writable Codex role would be a different role.
            raise ValueError("the codex adapter is read-only; it never writes application code")

        scratch = Path(scratch_dir or (cwd / ".pw-dev-scratch"))
        scratch.mkdir(parents=True, exist_ok=True)
        last_message = scratch / f"codex-{role}-last.txt"
        if last_message.exists():
            last_message.unlink()

        argv = [
            self.config.executable, "exec",
            "--json",
            "--skip-git-repo-check",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "-s", "read-only",
            "-C", str(cwd),
            "-o", str(last_message),
            "--color", "never",
        ]
        if self.config.model:
            argv += ["-m", self.config.model]
        if self.config.reasoning_effort:
            argv += ["-c", f'model_reasoning_effort="{self.config.reasoning_effort}"']
        if schema_id:
            argv += ["--output-schema", str(schema_path(schema_id))]
        argv += list(self.config.extra_args)

        body = prompt if system_prompt is None else f"{system_prompt}\n\n---\n\n{prompt}"
        argv.append(body)

        env = proc.build_env(overrides={
            "CODEX_HOME": str(self.codex_home),
            # Codex writes scratch files; keep them inside the run's own area.
            "TMPDIR": str(scratch),
        })

        events: list[dict] = []

        def _line(line: str) -> None:
            line = line.strip()
            if not line or not line.startswith("{"):
                return
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                return
            events.append(event)
            if on_event is not None:
                on_event(event)

        # stdin is bound to /dev/null: a piped, never-closed stdin makes
        # `codex exec` block forever waiting for more of the prompt.
        result = proc.run(
            argv, cwd=cwd, env=env, timeout=timeout, stdin_data=None,
            max_output_bytes=max_output_bytes, on_stdout_line=_line,
            cancel_check=cancel_check,
        )
        return self._interpret(role, result, events, last_message, schema_id)

    # ------------------------------------------------------------ interpreting
    def _interpret(
        self, role: str, result: proc.ProcResult, events: list[dict],
        last_message: Path, schema_id: str | None,
    ) -> ProviderResult:
        usage = _usage_from_events(events, self.config.model)
        session_id = next(
            (e.get("thread_id") for e in events if e.get("type") == "thread.started"), None
        )
        base = dict(
            role=role, provider=self.name, raw_events=events, usage=usage,
            exit_status=result.returncode, duration_seconds=result.duration_seconds,
            argv=result.argv, stderr_tail=redact(result.stderr[-4000:]),
            session_id=session_id, resolved_model=self.config.model,
        )

        if result.cancelled:
            return ProviderResult(ok=False, failure_kind=FailureKind.CANCELLED, data=None,
                                  text=None, detail="cancelled by the controller", **base)
        if result.timed_out:
            return ProviderResult(
                ok=False, failure_kind=FailureKind.TIMEOUT, data=None, text=None,
                detail=(
                    f"no result within {result.duration_seconds:.0f}s; the process group was "
                    "terminated. Whether the provider did work before the timeout is unknown."
                ),
                **base,
            )

        # A reported error beats a zero exit status.
        errors = [
            e for e in events
            if e.get("type") in ("error", "turn.failed")
            or (e.get("item") or {}).get("type") == "error"
        ]
        stream_error = _first_error_text(errors)
        if stream_error:
            kind = _classify(stream_error)
            if kind == FailureKind.UNKNOWN:
                kind = (
                    FailureKind.EXIT_ZERO_ERROR if result.returncode == 0
                    else FailureKind.NONZERO_EXIT
                )
            return ProviderResult(ok=False, failure_kind=kind, data=None, text=None,
                                  detail=redact(stream_error)[:2000], **base)

        text: str | None = None
        if last_message.is_file():
            text = last_message.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            # Fall back to the last agent message on the stream, but only after
            # the dedicated output file came up empty -- a stream message is the
            # last thing that appeared, not a declared final result.
            for event in reversed(events):
                item = event.get("item") or {}
                if item.get("type") == "agent_message" and item.get("text"):
                    text = str(item["text"]).strip()
                    break

        if not text:
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
                    "the run produced no final message"
                    + (f" (exit {result.returncode})" if result.returncode else "")
                ),
                **base,
            )

        if _REFUSAL_HINTS.search(text) and schema_id is None:
            return ProviderResult(ok=False, failure_kind=FailureKind.REFUSAL, data=None,
                                  text=text, detail=redact(text)[:1000], **base)

        if schema_id is None:
            return ProviderResult(ok=True, failure_kind=FailureKind.NONE, data=None,
                                  text=text, detail="", **base)

        document = _extract_json(text)
        if document is None:
            return ProviderResult(
                ok=False, failure_kind=FailureKind.MALFORMED_OUTPUT, data=None, text=text,
                detail="the final message was not parseable JSON despite --output-schema",
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
        """A tiny, bounded live call. Separate from offline inspection on purpose."""
        import tempfile

        scratch = Path(scratch_dir or tempfile.mkdtemp(prefix="pw-dev-codex-probe-"))
        scratch.mkdir(parents=True, exist_ok=True)
        workdir = scratch / "wd"
        workdir.mkdir(exist_ok=True)
        schema = scratch / "probe.schema.json"
        schema.write_text(json.dumps({
            "type": "object",
            "properties": {"token": {"type": "string"}},
            "required": ["token"],
            "additionalProperties": False,
        }), encoding="utf-8")
        last = scratch / "probe-last.txt"

        argv = [
            self.config.executable, "exec", "--json", "--skip-git-repo-check",
            "--ignore-user-config", "--ignore-rules", "--ephemeral",
            "-s", "read-only", "-C", str(workdir), "-o", str(last),
            "--color", "never", "--output-schema", str(schema),
        ]
        if self.config.model:
            argv += ["-m", self.config.model]
        argv.append('Return a JSON object whose "token" field is exactly PW_DEV_PROBE.')

        env = proc.build_env(overrides={"CODEX_HOME": str(self.codex_home), "TMPDIR": str(scratch)})
        events: list[dict] = []

        def _line(line: str) -> None:
            line = line.strip()
            if line.startswith("{"):
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    pass

        try:
            result = proc.run(argv, cwd=workdir, env=env, timeout=timeout,
                              max_output_bytes=1 << 20, on_stdout_line=_line)
        except FileNotFoundError as exc:
            return ProviderResult(
                role="probe", provider=self.name, ok=False,
                failure_kind=FailureKind.EXECUTABLE_MISSING, data=None, text=None,
                detail=str(exc),
            )
        outcome = self._interpret("probe", result, events, last, None)
        if outcome.ok and outcome.text and "PW_DEV_PROBE" not in outcome.text:
            outcome.ok = False
            outcome.failure_kind = FailureKind.MALFORMED_OUTPUT
            outcome.detail = "the probe response did not contain the requested token"
        # Recover the model the CLI actually used, so `doctor` reports a real id.
        outcome.resolved_model = self.config.model or _resolved_model_from_session(self.codex_home)
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

    def auth_mode(self) -> str | None:
        """Read the auth *mode* from CODEX_HOME. Never reads a token value."""
        auth_file = self.codex_home / "auth.json"
        if not auth_file.is_file():
            return None
        try:
            document = json.loads(auth_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return "unreadable"
        if document.get("auth_mode"):
            return str(document["auth_mode"])
        if document.get("OPENAI_API_KEY"):
            return "api_key"
        if document.get("tokens"):
            return "chatgpt"
        return "unknown"


def _first_error_text(errors: list[dict]) -> str | None:
    for event in errors:
        for candidate in (
            event.get("message"),
            (event.get("error") or {}).get("message") if isinstance(event.get("error"), dict) else None,
            (event.get("item") or {}).get("message"),
        ):
            if candidate:
                return str(candidate)
    return None


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
    """Parse a JSON document, tolerating a fenced block around it."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 2:
            body = "\n".join(lines[1:])
            if body.rstrip().endswith("```"):
                body = body.rstrip()[: -3]
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


def _usage_from_events(events: list[dict], model: str | None) -> Usage:
    for event in reversed(events):
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            reported = event["usage"]
            return Usage(
                input_tokens=reported.get("input_tokens"),
                output_tokens=reported.get("output_tokens"),
                cached_input_tokens=reported.get("cached_input_tokens"),
                # codex exec reports tokens only. A dollar figure would be an
                # estimate, and an estimate is not a cost.
                cost_usd=None,
                model=model,
            )
    return Usage(model=model)


def _resolved_model_from_session(codex_home: Path) -> str | None:
    """Recover the model id from the most recent session rollout, if one exists."""
    sessions = codex_home / "sessions"
    if not sessions.is_dir():
        return None
    candidates = sorted(sessions.rglob("rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates[:3]:
        try:
            with path.open("r", encoding="utf-8") as handle:
                for _ in range(40):
                    line = handle.readline()
                    if not line:
                        break
                    try:
                        record = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    payload = record.get("payload") or {}
                    if isinstance(payload.get("model"), str):
                        return payload["model"]
        except OSError:
            continue
    return None
