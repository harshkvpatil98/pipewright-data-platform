"""Exception types the controller distinguishes between.

Every one of these maps to a different terminal state. `ProviderError` pauses a
run; `PolicyViolation` blocks it; `PublicationError` stops before anything
leaves the machine.
"""

from __future__ import annotations


class PwDevError(Exception):
    """Base class for every error this tool raises deliberately."""


class ConfigError(PwDevError):
    """The configuration or run policy is unusable."""


class PolicyViolation(PwDevError):
    """An agent asked for something the adopted policy forbids.

    Raised for path escapes, unknown verification IDs, writes outside a task's
    declared ownership, and attempts to touch controller state.
    """


class ProviderError(PwDevError):
    """A provider CLI failed in a way the controller can describe.

    `kind` is one of the values in `providers.base.FailureKind` so a caller can
    decide between retrying, escalating and stopping.
    """

    def __init__(self, message: str, *, kind: str = "unknown", detail: str | None = None) -> None:
        super().__init__(message)
        self.kind = kind
        self.detail = detail


class VerificationError(PwDevError):
    """A required check could not be executed at all."""


class PublicationError(PwDevError):
    """Publication was refused. Nothing was pushed."""


class StateError(PwDevError):
    """An illegal state transition, or a lost lock/lease."""


class LimitReached(PwDevError):
    """A configured budget was exhausted. The run pauses; it does not complete."""

    def __init__(self, message: str, *, limit: str) -> None:
        super().__init__(message)
        self.limit = limit
