"""The one place a write is authorised.

A permission system spread across a hundred call sites is a permission system
with a hole in it. This is a single FastAPI dependency mounted on the whole API
router: it looks at the request's method and path, works out the role that
combination needs, and compares it with the caller's role on the project named
in the path.

Two properties matter more than the rule table itself:

* **It cannot be forgotten.** A new project-scoped route is covered the moment
  it is mounted, and an unrecognised write path requires an editor rather than
  falling through to allowed.
* **It never forces authentication.** Requests without a token fall straight
  through, so the route's own auth dependency produces the 401. Otherwise
  mounting this would have made ``/auth/login`` require a login.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from shared_python.auth.security import decode_access_token
from shared_python.errors import ForbiddenError
from shared_python.logging import get_logger

from service_access.permissions import evaluate, review_refusal
from service_access.resolver import role_for

logger = get_logger(__name__)


def _bearer_token(request: Request) -> str | None:
    header = request.headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return request.cookies.get("idp_access_token")


def build_project_guard(get_db: Callable[..., Session], settings) -> Callable[..., None]:
    """A dependency that authorises project-scoped requests."""

    def guard(request: Request, db: Session = Depends(get_db)) -> None:
        raw_project_id = request.path_params.get("project_id")
        if raw_project_id is None:
            return  # Not project-scoped; nothing for this rule to say.

        token_value = _bearer_token(request)
        if token_value is None:
            return  # Let the route's own auth dependency answer with a 401.

        try:
            token = decode_access_token(
                token_value,
                secret_key=settings.auth_jwt_secret,
                issuer=settings.auth_jwt_issuer,
                audience=settings.auth_jwt_audience,
            )
            user_id = uuid.UUID(token.sub)
            project_id = uuid.UUID(str(raw_project_id))
        except Exception:  # noqa: BLE001 - a bad token is the auth layer's problem
            return

        role = role_for(db, project_id, user_id)
        if role is None:
            # No access at all reads as "not found" everywhere else, and this
            # must not become the one endpoint that confirms a project exists.
            return

        if _requires_approval(db, project_id):
            refusal = review_refusal(request.method, request.url.path)
            if refusal is not None:
                raise ForbiddenError(refusal)

        decision = evaluate(method=request.method, path=request.url.path, role=role)
        if not decision.allowed:
            logger.info(
                "access_denied method=%s path=%s role=%s required=%s",
                request.method,
                request.url.path,
                decision.actual_role,
                decision.required_role,
            )
            raise ForbiddenError(decision.reason)

    return guard


def _requires_approval(db: Session, project_id: uuid.UUID) -> bool:
    from service_projects.models import Project

    project = db.get(Project, project_id)
    return bool(project is not None and getattr(project, "requires_approval", False))
