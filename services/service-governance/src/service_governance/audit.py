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

import json
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
    # Answers with a fresh session token; it is called every hour of use.
    "/api/v1/auth/session/renew",
)

# POSTs that compute an answer and store nothing: previews, plans, parses and
# reads too large for a query string. They are reads in every sense an auditor
# cares about, and recording them buried real changes -- every keystroke in the
# chart builder or the Studio wrote a row. Matched on the route's skeleton
# (identifiers replaced), so a new route has to be added here deliberately; an
# unknown POST is audited, which is the safe direction to be wrong in.
READ_ONLY_POSTS = frozenset(
    {
        "/api/v1/projects/{id}/charts/preview",
        "/api/v1/projects/{id}/bundle/preview",
        "/api/v1/projects/{id}/datasets/{id}/deliver/preview",
        "/api/v1/projects/{id}/database-copies/plan",
        "/api/v1/projects/{id}/metrics/{id}/preview",
        "/api/v1/projects/{id}/datasets/{id}/pipelines/preview",
        "/api/v1/transformations/tools/preview",
        "/api/v1/transformations/tools/regex/test",
        "/api/v1/projects/{id}/pipelines/{id}/merge/preview",
        "/api/v1/projects/{id}/workflows/{id}/backfill/preview",
        "/api/v1/projects/{id}/extraction/connections/{id}/preview",
        "/api/v1/projects/{id}/workbench/preview",
        "/api/v1/projects/{id}/workbench/explain",
        "/api/v1/projects/{id}/workbench/completions/{id}",
        "/api/v1/workbench/recipe/yaml",
        "/api/v1/workbench/recipe/parse",
        "/api/v1/projects/{id}/datasets/analyze",
        "/api/v1/projects/{id}/datasets/{id}/versions/diff",
        "/api/v1/projects/{id}/datasets/{id}/versions/query",
        "/api/v1/projects/{id}/dashboards/{id}/data",
        "/api/v1/projects/{id}/pivot",
        "/api/v1/projects/{id}/datasets/{id}/impact",
        "/api/v1/projects/{id}/datasets/{id}/join-keys",
        "/api/v1/projects/{id}/datasets/{id}/duplicates",
        "/api/v1/projects/{id}/datasets/{id}/pii/mask",
        "/api/v1/projects/{id}/describe",
    }
)

# Read-only POSTs whose identifiers are names rather than UUIDs, so a skeleton
# cannot match them: everything under these prefixes computes and stores
# nothing.
READ_ONLY_POST_PREFIXES = ("/api/v1/transformations/templates/",)

# Writes to a working state that is not the thing itself (C2): a recipe's
# shared copy, changed several times a second while people edit together,
# and "I have this open", said every few seconds. Saving the recipe, a
# suggestion and discarding the copy are what the log records; these would
# be most of its rows and none of its answers.
_DRAFT_WRITES = (
    re.compile(r"^POST /api/v1/projects/\{id\}/pipelines/\{id\}/shared$"),
    re.compile(r"^POST /api/v1/projects/\{id\}/presence$"),
    re.compile(r"^DELETE /api/v1/projects/\{id\}/presence/[^/]+$"),
)

_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_PROJECT_PATTERN = re.compile(r"/projects/(" + _UUID_PATTERN.pattern + ")")


def route_skeleton(path: str) -> str:
    """The path with every identifier replaced by `{id}`."""
    return _UUID_PATTERN.sub("{id}", path.rstrip("/"))


def is_audited(method: str, path: str) -> bool:
    """Whether a request belongs in the audit log."""
    if method not in AUDITED_METHODS or path.startswith(SKIPPED_PREFIXES):
        return False
    if method == "POST" and (
        route_skeleton(path) in READ_ONLY_POSTS or path.startswith(READ_ONLY_POST_PREFIXES)
    ):
        return False
    if any(pattern.match(f"{method} {route_skeleton(path)}") for pattern in _DRAFT_WRITES):
        return False
    return True


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


#: The requests that make a project.
_MADE_PROJECT = re.compile(r"/api/v1/projects(/demo)?")

#: An answer this large is not a newly made thing's record; it is passed on unread.
CREATED_BODY_LIMIT = 1_000_000


def created_resource(path: str, body: bytes) -> tuple[str | None, str | None]:
    """The kind and id of what a 201 answer says was made, if it says.

    The request's path cannot name it (it did not exist yet), so without this
    the log said "created a recipe" with the dataset it was made on as its
    subject (A8, Y6). An upload's answer carries the dataset it made.
    """
    try:
        answer = json.loads(body)
    except ValueError:
        return None, None
    if not isinstance(answer, dict):
        return None, None
    made = answer.get("id")
    kind: str | None = None
    if made is None and isinstance(answer.get("dataset"), dict):
        made, kind = answer["dataset"].get("id"), "dataset"
    if not isinstance(made, str) or not _UUID_PATTERN.fullmatch(made):
        return None, None
    if kind is None:
        nouns = [segment for segment in path.split("/") if segment and not _UUID_PATTERN.fullmatch(segment)]
        kind = nouns[-1].rstrip("s") if nouns else None
    return kind, made


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
        if not is_audited(request.method, request.url.path):
            return await call_next(request)

        # What a deletion removes cannot be named once it has gone, so its
        # name is read first (A8, Y6: "deleted a dataset", but which?).
        name_before = self._name_before(request.url.path) if request.method == "DELETE" else None

        started = time.perf_counter()
        response = await call_next(request)
        duration_ms = int((time.perf_counter() - started) * 1000)

        created: tuple[str | None, str | None] = (None, None)
        if (
            request.method == "POST"
            and response.status_code == 201
            and "json" in response.headers.get("content-type", "")
            and int(response.headers.get("content-length") or 0) <= CREATED_BODY_LIMIT
        ):
            # Read the answer to learn what was made, then pass the same bytes on.
            body = b"".join([chunk async for chunk in response.body_iterator])  # type: ignore[attr-defined]
            created = created_resource(request.url.path, body)
            passed_on = Response(content=body, status_code=response.status_code, background=response.background)
            passed_on.raw_headers = list(response.raw_headers)
            response = passed_on

        try:
            self._record(request, response, duration_ms, created=created, name_before=name_before)
        except Exception:  # noqa: BLE001 - a log must never break the request
            logger.exception("audit_write_failed path=%s", request.url.path)

        return response

    def _name_before(self, path: str) -> str | None:
        return _name_before_lookup(self._session_factory, path)

    def _record(
        self,
        request: Request,
        response: Response,
        duration_ms: int,
        *,
        created: tuple[str | None, str | None] = (None, None),
        name_before: str | None = None,
    ) -> None:
        path = request.url.path
        kind, resource_id = resource_hint(path)
        project_id = project_id_from(path)
        if created[1] is not None:
            kind, resource_id = created
            # A new project's own making belongs to it, so its activity and
            # audit log start there (A9: the demo's began with its first run).
            if project_id is None and _MADE_PROJECT.fullmatch(path.rstrip("/")):
                project_id, kind = uuid.UUID(created[1]), "project"
        actor_id, actor_name = _actor(request)

        session = self._session_factory()
        try:
            session.add(  # type: ignore[attr-defined]
                AuditEntry(
                    project_id=project_id,
                    actor_user_id=actor_id,
                    actor_username=actor_name,
                    method=request.method,
                    path=path[:500],
                    action=describe_action(request.method, path)[:120],
                    resource_type=kind,
                    resource_id=resource_id,
                    status_code=response.status_code,
                    outcome=outcome_for(response.status_code),
                    # The header CorrelationIdMiddleware sets; this read a
                    # header nothing set, so no entry had its id (found in A7).
                    correlation_id=response.headers.get("x-request-id"),
                    duration_ms=duration_ms,
                    object_name=name_before[:200] if name_before else None,
                )
            )
            session.commit()  # type: ignore[attr-defined]
        finally:
            session.close()  # type: ignore[attr-defined]


def _name_before_lookup(session_factory: Callable[[], object], path: str) -> str | None:
    from service_governance.audit_words import current_name

    session = session_factory()
    try:
        return current_name(session, path)  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001 - a name is a courtesy; the log is not
        logger.exception("audit_name_lookup_failed path=%s", path)
        return None
    finally:
        session.close()  # type: ignore[attr-defined]


def _actor(request: Request) -> tuple[uuid.UUID | None, str | None]:
    """Who made the request: as the sign-in check found them, or else read from
    the token without verifying it.

    The sign-in check notes the person it accepted, a session or an API token
    alike. For a request refused before that, recording the claimed identity
    is more useful than recording nobody.
    """
    found = getattr(request.state, "audit_actor", None)
    if isinstance(found, tuple) and len(found) == 2:
        return found
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
