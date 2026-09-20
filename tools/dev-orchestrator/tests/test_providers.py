"""Provider adapters, driven through real subprocesses.

The fakes here are executable scripts, not mocks: the adapter builds an argv,
the runner starts a process, and the script replays a recorded response. That
covers the parts a mock would skip — argument construction, the environment,
stdin binding, exit status, and the file `codex exec -o` writes.

Every fixture is a recording. None of them establishes that a live provider call
happened.
"""

from __future__ import annotations

import json
import stat
import sys
from pathlib import Path

import pytest

from pw_dev.config import ProviderConfig
from pw_dev.providers.base import FailureKind
from pw_dev.providers.claude_cli import ClaudeCliAdapter
from pw_dev.providers.codex_cli import CodexCliAdapter

FIXTURES = Path(__file__).parent / "fixtures"


def _script(path: Path, body: str) -> Path:
    """Write an executable stand-in for a provider CLI.

    The shebang is `/bin/sh` rather than the interpreter directly: this
    repository's checkout path contains a space, and the kernel splits a shebang
    on whitespace, so `#!<python>` would try to exec the first path segment and
    fail with ENOENT on the script itself.
    """
    source = path.with_suffix(".py")
    source.write_text(body, encoding="utf-8")
    path.write_text(
        f'#!/bin/sh\nexec "{sys.executable}" "{source}" "$@"\n', encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IRWXU)
    return path


@pytest.fixture
def fake_codex(tmp_path: Path):
    """A stand-in `codex` that replays a recorded event stream."""

    def build(fixture: str, *, last_message: str | None = None, exit_code: int = 0,
              record_argv: Path | None = None, sleep: float = 0.0) -> Path:
        events = (FIXTURES / f"{fixture}.jsonl").read_text(encoding="utf-8")
        body = f'''
import json, sys, time, os
argv = sys.argv[1:]
{f"open({str(record_argv)!r}, 'w').write(json.dumps(argv))" if record_argv else ""}
time.sleep({sleep})
sys.stdout.write({events!r})
sys.stdout.flush()
out = None
if "-o" in argv:
    out = argv[argv.index("-o") + 1]
last = {last_message!r}
if out and last is not None:
    open(out, "w").write(last)
sys.exit({exit_code})
'''
        return _script(tmp_path / "codex", body)

    return build


@pytest.fixture
def fake_claude(tmp_path: Path):
    """A stand-in `claude` that replays a recorded result envelope."""

    def build(fixture: str | None = None, *, raw: str | None = None, exit_code: int = 0,
              record_argv: Path | None = None, sleep: float = 0.0,
              write_file: tuple[str, str] | None = None) -> Path:
        payload = raw if raw is not None else (FIXTURES / f"{fixture}.json").read_text(encoding="utf-8")
        write_stanza = ""
        if write_file:
            target, content = write_file
            write_stanza = (
                f"import pathlib; p = pathlib.Path(os.getcwd()) / {target!r}; "
                f"p.parent.mkdir(parents=True, exist_ok=True); p.write_text({content!r})\n"
            )
        body = f'''
import json, sys, time, os
argv = sys.argv[1:]
{f"open({str(record_argv)!r}, 'w').write(json.dumps(argv))" if record_argv else ""}
{write_stanza}
time.sleep({sleep})
sys.stdout.write({payload!r})
sys.exit({exit_code})
'''
        return _script(tmp_path / "claude", body)

    return build


def _codex(path: Path, *, model: str | None = "test-model") -> CodexCliAdapter:
    return CodexCliAdapter(ProviderConfig(executable=str(path), model=model))


def _claude(path: Path, *, model: str | None = "test-model") -> ClaudeCliAdapter:
    return ClaudeCliAdapter(ProviderConfig(executable=str(path), model=model))


# ------------------------------------------------------------------- codex
def test_codex_parses_a_successful_structured_result(fake_codex, tmp_path):
    binary = fake_codex("codex_success", last_message='{"token":"PW_DEV_PROBE"}')
    result = _codex(binary).invoke(
        role="planner", prompt="hi", cwd=tmp_path, timeout=30,
        scratch_dir=tmp_path / "scratch",
    )
    assert result.ok
    assert result.text == '{"token":"PW_DEV_PROBE"}'
    assert result.usage.input_tokens == 14075
    assert result.usage.output_tokens == 17
    assert result.usage.cost_usd is None, "codex exec reports tokens, not dollars"
    assert result.usage.cost_known is False
    assert result.session_id == "01a0acea-6590-7ee1-95dd-2f7a6645a31c"


def test_codex_sends_a_read_only_sandbox_and_no_user_config(fake_codex, tmp_path):
    recorded = tmp_path / "argv.json"
    binary = fake_codex("codex_success", last_message="ok", record_argv=recorded)
    _codex(binary).invoke(role="planner", prompt="hi", cwd=tmp_path, timeout=30,
                          scratch_dir=tmp_path / "scratch")
    argv = json.loads(recorded.read_text())
    assert argv[0] == "exec"
    assert "--json" in argv
    assert argv[argv.index("-s") + 1] == "read-only"
    assert "--ignore-user-config" in argv, "the operator's plugins and MCP servers stay out"
    assert "--ignore-rules" in argv
    assert "-m" in argv and argv[argv.index("-m") + 1] == "test-model"


def test_codex_refuses_to_be_used_as_a_writing_role(fake_codex, tmp_path):
    binary = fake_codex("codex_success", last_message="ok")
    with pytest.raises(ValueError, match="read-only"):
        _codex(binary).invoke(role="planner", prompt="hi", cwd=tmp_path, timeout=30,
                              writable=True, scratch_dir=tmp_path / "s")


def test_codex_model_unavailable_is_classified_not_retried(fake_codex, tmp_path):
    """The real failure shape: exit 0, a 400 on the stream, model name rejected."""
    binary = fake_codex("codex_model_unavailable", exit_code=0)
    result = _codex(binary, model="gpt-6-astra").invoke(
        role="planner", prompt="hi", cwd=tmp_path, timeout=30, scratch_dir=tmp_path / "s",
    )
    assert not result.ok
    assert result.failure_kind == FailureKind.MODEL_UNAVAILABLE
    assert "gpt-6-astra" in result.detail


def test_codex_rate_limit_is_classified_as_retryable(fake_codex, tmp_path):
    binary = fake_codex("codex_rate_limited", exit_code=1)
    result = _codex(binary).invoke(role="planner", prompt="hi", cwd=tmp_path, timeout=30,
                                   scratch_dir=tmp_path / "s")
    assert result.failure_kind == FailureKind.RATE_LIMITED


def test_codex_auth_failure_is_classified(fake_codex, tmp_path):
    binary = fake_codex("codex_auth_failure", exit_code=1)
    result = _codex(binary).invoke(role="planner", prompt="hi", cwd=tmp_path, timeout=30,
                                   scratch_dir=tmp_path / "s")
    assert result.failure_kind == FailureKind.AUTH


def test_codex_exit_zero_with_no_final_message_is_not_success(fake_codex, tmp_path):
    binary = fake_codex("codex_truncated", exit_code=0)
    result = _codex(binary).invoke(role="planner", prompt="hi", cwd=tmp_path, timeout=30,
                                   scratch_dir=tmp_path / "s")
    assert not result.ok, "exit status zero alone is not a result"
    assert result.failure_kind == FailureKind.MALFORMED_OUTPUT


def test_codex_schema_violation_is_reported_with_every_error(fake_codex, tmp_path):
    binary = fake_codex("codex_success", last_message='{"schema_version":"phase_spec/v1"}')
    result = _codex(binary).invoke(
        role="planner", prompt="hi", cwd=tmp_path, timeout=30,
        schema_id="phase_spec/v1", scratch_dir=tmp_path / "s",
    )
    assert result.failure_kind == FailureKind.SCHEMA_INVALID
    assert "missing required property" in result.detail
    assert result.detail.count("missing required property") > 5, (
        "every missing field is reported, so one reprompt can fix all of them"
    )


def test_codex_unparseable_json_despite_a_schema_is_malformed(fake_codex, tmp_path):
    binary = fake_codex("codex_success", last_message="I decided to answer in prose instead.")
    result = _codex(binary).invoke(
        role="planner", prompt="hi", cwd=tmp_path, timeout=30,
        schema_id="phase_spec/v1", scratch_dir=tmp_path / "s",
    )
    assert result.failure_kind == FailureKind.MALFORMED_OUTPUT


def test_codex_timeout_is_reported_as_unknown_work_not_as_nothing(fake_codex, tmp_path):
    binary = fake_codex("codex_success", last_message="ok", sleep=10)
    result = _codex(binary).invoke(role="planner", prompt="hi", cwd=tmp_path, timeout=1,
                                   scratch_dir=tmp_path / "s")
    assert result.failure_kind == FailureKind.TIMEOUT
    assert "unknown" in result.detail.lower()


# ------------------------------------------------------------------ claude
def test_claude_parses_a_successful_envelope_with_real_cost(fake_claude, tmp_path):
    binary = fake_claude("claude_success")
    result = _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                                    config_dir=tmp_path / "cfg")
    assert result.ok
    assert result.text == "PW_DEV_PROBE"
    assert result.usage.cost_known
    assert result.usage.cost_usd == pytest.approx(0.0358297)
    assert result.usage.model == "claude-sonnet-5"


def test_claude_not_logged_in_is_a_failure_despite_subtype_success(fake_claude, tmp_path):
    """The captured shape: exit 1, subtype "success", is_error true.

    Reading the exit status alone would call this a crash; reading `subtype`
    alone would call it a success. Only `is_error` is right.
    """
    binary = fake_claude("claude_not_logged_in", exit_code=1)
    result = _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                                    config_dir=tmp_path / "cfg")
    assert not result.ok
    assert result.failure_kind == FailureKind.AUTH
    assert "Not logged in" in result.detail


def test_claude_exit_zero_error_report_is_not_success(fake_claude, tmp_path):
    binary = fake_claude("claude_exit_zero_error", exit_code=0)
    result = _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                                    config_dir=tmp_path / "cfg")
    assert not result.ok
    assert result.failure_kind == FailureKind.EXIT_ZERO_ERROR


def test_claude_rate_limit_is_classified(fake_claude, tmp_path):
    binary = fake_claude("claude_rate_limited", exit_code=1)
    result = _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                                    config_dir=tmp_path / "cfg")
    assert result.failure_kind == FailureKind.RATE_LIMITED


def test_claude_refusal_without_a_schema_is_surfaced_as_text(fake_claude, tmp_path):
    binary = fake_claude("claude_refusal")
    result = _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                                    config_dir=tmp_path / "cfg")
    assert result.ok
    assert "can't help" in (result.text or "")


def test_claude_garbage_on_stdout_is_malformed_not_a_crash(fake_claude, tmp_path):
    binary = fake_claude(raw="not json at all\n", exit_code=0)
    result = _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                                    config_dir=tmp_path / "cfg")
    assert result.failure_kind == FailureKind.MALFORMED_OUTPUT


def test_claude_worker_cannot_delegate(fake_claude, tmp_path):
    """Delegation tools are removed so nested agents cannot evade the budget."""
    recorded = tmp_path / "argv.json"
    binary = fake_claude("claude_success", record_argv=recorded)
    _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                           writable=True, config_dir=tmp_path / "cfg")
    argv = json.loads(recorded.read_text())
    denied_at = argv.index("--disallowed-tools")
    denied = argv[denied_at + 1 : denied_at + 10]
    for tool in ("Task", "Agent", "WebFetch", "WebSearch"):
        assert tool in denied, f"{tool} must be denied to a worker"
    assert "--bare" not in argv, "--bare would silently switch to API authentication"


def test_a_writing_worker_runs_without_a_permission_prompt(fake_claude, tmp_path):
    """Deliberate, and the reasoning belongs next to the flag.

    This used to pin `acceptEdits` and assert `--dangerously-skip-permissions`
    was absent. The effect was a worker that could edit any file it owned and
    run nothing: `acceptEdits` sends every Bash command to the permission
    system, and headless -- with `--setting-sources ""`, so not one allow rule
    is loaded -- there is nobody to answer it. `Bash` sat in `WORKER_TOOLS`
    and returned "This command requires approval" every time, so workers wrote
    code they could not execute or test. Four repair rounds on one failing test
    each reasoned carefully to the wrong conclusion and said so honestly,
    because confirming it needed a single command.

    `bypassPermissions` is the same grant `--dangerously-skip-permissions`
    gives; naming it the other way would only hide it. What keeps a worker
    inside its worktree was never this flag -- it is the seatbelt profile the
    controller wraps the process in, which the worker cannot negotiate with,
    and `test_isolation.py` runs a real shell under it to show the repository
    and the operator's home still refusing writes.

    What this genuinely widens, stated rather than implied: a shell can reach
    the network whatever `WebFetch` is set to, can read anything the operator
    can read, and can start processes. That is the same boundary every
    verification evidence document already describes as "file writes, by
    path" -- it does not cover reads, network, or process control.
    """
    recorded = tmp_path / "argv.json"
    binary = fake_claude("claude_success", record_argv=recorded)
    _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                           writable=True, config_dir=tmp_path / "cfg")
    argv = json.loads(recorded.read_text())
    assert argv[argv.index("--permission-mode") + 1] == "bypassPermissions"
    assert "Bash" in argv, "a worker that cannot run anything cannot verify anything"


def test_a_read_only_worker_still_gets_no_such_grant(fake_claude, tmp_path):
    """The widening is for workers that write; analysis roles keep the old posture."""
    recorded = tmp_path / "argv.json"
    binary = fake_claude("claude_success", record_argv=recorded)
    _claude(binary).invoke(role="analysis", prompt="hi", cwd=tmp_path, timeout=30,
                           writable=False, config_dir=tmp_path / "cfg")
    argv = json.loads(recorded.read_text())
    assert argv[argv.index("--permission-mode") + 1] == "manual"
    assert "Bash" not in argv[argv.index("--tools") + 1: argv.index("--disallowed-tools")]


def test_claude_worker_loads_no_settings_plugins_or_mcp(fake_claude, tmp_path):
    recorded = tmp_path / "argv.json"
    binary = fake_claude("claude_success", record_argv=recorded)
    _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                           writable=True, config_dir=tmp_path / "cfg")
    argv = json.loads(recorded.read_text())
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert "--strict-mcp-config" in argv
    assert argv[argv.index("--mcp-config") + 1] == '{"mcpServers":{}}'
    assert "--disable-slash-commands" in argv


def test_claude_receives_a_sanitised_environment(fake_claude, tmp_path, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-must-not-travel")
    monkeypatch.setenv("CLAUDECODE", "1")
    dumped = tmp_path / "env.json"
    binary = _script(tmp_path / "claude", f'''
import json, os, sys
open({str(dumped)!r}, "w").write(json.dumps(dict(os.environ)))
sys.stdout.write(open({str(FIXTURES / "claude_success.json")!r}).read())
''')
    _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                           config_dir=tmp_path / "cfg")
    child_env = json.loads(dumped.read_text())
    assert "ANTHROPIC_API_KEY" not in child_env
    assert "CLAUDECODE" not in child_env
    assert child_env["CLAUDE_CONFIG_DIR"].endswith("cfg")


def test_claude_timeout_says_the_worktree_may_hold_partial_work(fake_claude, tmp_path):
    binary = fake_claude("claude_success", sleep=10)
    result = _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=1,
                                    config_dir=tmp_path / "cfg")
    assert result.failure_kind == FailureKind.TIMEOUT
    assert "partial" in result.detail


def test_a_missing_executable_is_its_own_failure_kind(tmp_path):
    adapter = ClaudeCliAdapter(ProviderConfig(executable="not-a-real-claude-xyz", model="m"))
    result = adapter.probe(timeout=5, scratch_dir=tmp_path / "probe")
    assert result.failure_kind == FailureKind.EXECUTABLE_MISSING


def test_the_schema_handed_to_claude_carries_no_meta_schema_declaration():
    """`claude --json-schema` rejects a `$schema` it does not have registered.

        Error: --json-schema is not a valid JSON Schema: no schema with key or
        ref "https://json-schema.org/draft/2020-12/schema"

    It exits 1 with empty stdout, so the failure looks like a crash rather than
    an argument problem. The document on disk keeps its declaration; the copy
    sent to the CLI does not.
    """
    from pw_dev.providers.claude_cli import _inline_schema
    from pw_dev.schemas import SCHEMA_IDS, load_schema

    for schema_id in SCHEMA_IDS:
        assert "$schema" in load_schema(schema_id), "the file keeps its declaration"
        inlined = json.loads(_inline_schema(schema_id))
        assert "$schema" not in inlined
        assert "$id" not in inlined
        assert inlined["type"] == "object"
        assert inlined["required"]


def test_claude_is_given_the_stripped_schema_on_the_command_line(fake_claude, tmp_path):
    recorded = tmp_path / "argv.json"
    binary = fake_claude("claude_success", record_argv=recorded)
    _claude(binary).invoke(role="worker", prompt="hi", cwd=tmp_path, timeout=30,
                           schema_id="worker_report/v1", config_dir=tmp_path / "cfg")
    argv = json.loads(recorded.read_text())
    schema = json.loads(argv[argv.index("--json-schema") + 1])
    assert "$schema" not in schema
