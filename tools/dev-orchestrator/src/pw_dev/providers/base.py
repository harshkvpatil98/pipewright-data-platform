"""What every adapter returns, and the failure taxonomy the controller acts on."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol


class FailureKind:
    """Why a provider call did not produce a usable result.

    The controller behaves differently for each: `RATE_LIMITED` and `TIMEOUT`
    are retried with backoff, `AUTH` and `MODEL_UNAVAILABLE` stop the run
    immediately because retrying cannot fix them, `REFUSAL` is escalated to a
    person, and `MALFORMED_OUTPUT` gets one reprompt before it counts as a
    failed round.
    """

    NONE = "none"
    AUTH = "auth"
    MODEL_UNAVAILABLE = "model_unavailable"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    REFUSAL = "refusal"
    MALFORMED_OUTPUT = "malformed_output"
    SCHEMA_INVALID = "schema_invalid"
    NONZERO_EXIT = "nonzero_exit"
    EXIT_ZERO_ERROR = "exit_zero_error"
    EXECUTABLE_MISSING = "executable_missing"
    TRANSPORT = "transport"
    UNKNOWN = "unknown"


#: Retrying these can plausibly succeed. Everything else is reported, not retried.
RETRYABLE = frozenset({FailureKind.RATE_LIMITED, FailureKind.TIMEOUT, FailureKind.TRANSPORT})

#: These end the run rather than consuming repair rounds against a wall.
FATAL = frozenset({
    FailureKind.AUTH, FailureKind.MODEL_UNAVAILABLE, FailureKind.EXECUTABLE_MISSING,
})


@dataclass(frozen=True)
class Usage:
    """Reported usage. `cost_usd` is None when the provider does not supply one.

    `codex exec` reports tokens and no dollar figure; `claude -p` reports both.
    Filling a missing cost with 0.0 would turn "unknown" into "free", so it
    stays None all the way to the status line.
    """

    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_input_tokens: int | None = None
    cost_usd: float | None = None
    model: str | None = None

    @property
    def cost_known(self) -> bool:
        return self.cost_usd is not None


@dataclass
class ProviderResult:
    """One provider invocation, fully described.

    `ok` is not `exit_status == 0`. Both CLIs can exit zero having reported an
    error inside their structured output, and `claude -p` exits 1 while still
    emitting a well-formed result object saying it is not logged in. The
    controller reads the structured result; the exit status is corroboration.
    """

    role: str
    provider: str
    ok: bool
    failure_kind: str
    data: Any | None
    text: str | None
    raw_events: list[dict] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    exit_status: int | None = None
    duration_seconds: float = 0.0
    argv: list[str] = field(default_factory=list)
    stderr_tail: str = ""
    detail: str = ""
    session_id: str | None = None
    resolved_model: str | None = None

    def summary(self) -> str:
        if self.ok:
            return f"{self.provider}/{self.role} ok in {self.duration_seconds:.1f}s"
        return f"{self.provider}/{self.role} failed ({self.failure_kind}): {self.detail}"


class ProviderAdapter(Protocol):
    """A provider the controller can ask for one structured answer."""

    name: str

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
        on_event: Any = None,
        cancel_check: Any = None,
        system_prompt: str | None = None,
    ) -> ProviderResult: ...

    def probe(self, *, timeout: float = 120.0) -> ProviderResult: ...

    def version(self) -> str | None: ...
