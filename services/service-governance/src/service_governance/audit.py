"""The audit log, written by the gateway rather than by each service.

"Who changed what, when" is only worth having if it is complete, and a log
written by hand at each call site is complete right up until somebody adds a
route and forgets. So this is middleware: every request that could change
something produces a row, including the ones that were refused.

It records the *request*, not the domain object. That is a deliberate limit --
the before/after of a pipeline lives in version history, which knows what a
pipeline is. What this adds is coverage: nothing gets through unlogged.

The write happens on its own session, after the response. The handler's
transaction may have rolled back, and the attempt still happened.
"""

from __future__ import annotations

import re
import time
import uuid
from collections.abc import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from shared_python.logging import get_logger

from service_governance.models import AuditEntry

logger = get_logger(__name__)

# Reads are not audited: they would be 95% of the rows and none of the answers.
AUDITED_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

# Paths whose bodies are credentials. The log records that a login happened,
# never the attempt's contents.
SKIPPED_PREFIXES = (
    # Only the endpoints whose request or response carries a secret. The
    # middleware logs method + path, never bodies, so admin account actions
    # (deactivate, delete, role change, invite, reset-code) are safe — and
    # important — to record; they are deliberately no longer skipped.
    "/api/v1/auth/login",
    "/api/v1/auth/me/password",
    "/api/v1/auth/redeem-code",
    "/api/v1/auth/tokens",
)

_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_PROJECT_PATTERN = re.compile(r"/projects/(" + _UUID_PATTERN.pattern + ")")


def describe_action(method: str, path: str) -> str:
    """A short phrase for the log, derived from the route.

    Identifiers are stripped so that a thousand edits to a thousand workflows
    group into one readable action rather than a thousand unique strings.
    """
    skeleton = _UUID_PATTERN.sub("{id}", path)
    skeleton = skeleton.replace("/api/v1", "").strip("/")
    verb = {"POST": "create", "PUT": "replace", "PATCH": "update", "DELETE": "delete"}.get(
        method, method.lower()
    )

    segments = [segment for segment in skeleton.split("/") if segment and segment != "{id}"]
    if not segments:
        return verb
    tail = segments[-1]
    # A trailing verb-ish segment is the action itself: ".../workflows/{id}/run".
    if tail in {
        "run",
        "backfill",
        "cancel",
        "resolve",
        "acknowledge",
        "reopen",
        "assign",
        "approve",
        "reject",
        "restore",
        "promote",
        "withdraw",
        "capture",
        "check",
        "comments",
        # Write-back: the action is the last segment, and "create commit" would
        # be both wrong and unsearchable.
        "commit",
        "discard",
        "plan",
        # Analytical POSTs: they compute an answer and store nothing.
        "preview",
    }:
        subject = segments[-2] if len(segments) > 1 else "resource"
        return f"{tail} {subject.rstrip('s')}"
    return f"{verb} {tail.rstrip('s')}"


def resource_hint(path: str) -> tuple[str | None, str | None]:
    """The kind and id of the thing being acted on, as far as the path says."""
    skeleton = [segment for segment in path.split("/") if segment]
    ids = _UUID_PATTERN.findall(path)
    kind: str | None = None
    for index, segment in enumerate(skeleton):
        if _UUID_PATTERN.fullmatch(segment) and index > 0:
            candidate = skeleton[index - 1]
            if candidate != "projects":
                kind = candidate.rstrip("s")
    return kind, (ids[-1] if ids else None)


def project_id_from(path: str) -> uuid.UUID | None:
    match = _PROJECT_PATTERN.search(path)
    if match is None:
        return None
    try:
        return uuid.UUID(match.group(1))
    except ValueError:
        return None


def outcome_for(status_code: int) -> str:
    if status_code in (401, 403):
        return "denied"
    if status_code >= 400:
        return "failed"
    return "succeeded"


class AuditMiddleware(BaseHTTPMiddleware):
    """Record every mutating request."""

    def __init__(self, app, *, session_factory: Callable[[], object]) -> None:
        super().__init__(app)
        self._session_factory = session_factory

    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method not in AUDITED_METHODS or request.url.path.startswith(SKIPPED_PREFIXES):
            return await call_next(request)

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)

        try:
            self._record(request, response, duration_ms)
        except Exception:  # noqa: BLE001 - a log must never break the request
            logger.exception("audit_write_failed path=%s", request.url.path)

        return response

    def _record(self, request: Request, response: Response, duration_ms: int) -> None:
        path = request.url.path
        kind, resource_id = resource_hint(path)
        actor_id, actor_name = _actor(request)

        session = self._session_factory()
        try:
            session.add(  # type: ignore[attr-defined]
                AuditEntry(
                    project_id=project_id_from(path),
                    actor_user_id=actor_id,
                    actor_username=actor_name,
                    method=request.method,
                    path=path[:500],
                    action=describe_action(request.method, path)[:120],
                    resource_type=kind,
                    resource_id=resource_id,
                    status_code=response.status_code,
                    outcome=outcome_for(response.status_code),
                    correlation_id=response.headers.get("x-correlation-id"),
                    duration_ms=duration_ms,
                )
            )
            session.commit()  # type: ignore[attr-defined]
        finally:
            session.close()  # type: ignore[attr-defined]


def _actor(request: Request) -> tuple[uuid.UUID | None, str | None]:
    """Who made the request, read from the token without verifying it.

    The signature was already checked by the auth dependency for anything that
    reached a handler; for a request that was rejected, recording the claimed
    identity is more useful than recording nobody.
    """
    token = request.headers.get("authorization", "")
    if token.lower().startswith("bearer "):
        token = token[7:].strip()
    else:
        token = request.cookies.get("idp_access_token") or ""
    if not token:
        return None, None

    try:
        import base64
        import json

        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        subject = claims.get("sub")
        return (uuid.UUID(subject) if subject else None), claims.get("username")
    except Exception:  # noqa: BLE001 - an unreadable token means an unknown actor
        return None, None
