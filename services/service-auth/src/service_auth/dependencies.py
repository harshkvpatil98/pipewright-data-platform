from __future__ import annotations

import os
import uuid
from collections.abc import Callable

from fastapi import Cookie, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from service_auth.network_gate import check_network
from service_auth.schemas import UserRead
from service_auth.service import get_user_by_id
from service_auth.tokens import (
    authenticate_api_token,
    limited_refusal,
    looks_like_api_token,
    scope_allows,
    token_projects,
)
from shared_python.auth.security import decode_access_token
from shared_python.errors import ForbiddenError, UnauthorizedError
from shared_python.network import client_address

bearer_scheme = HTTPBearer(auto_error=False)


def request_address(request: Request, settings=None) -> str:
    """The address this request came from, as far as the deployment can trust.

    Without a settings object (a service router that is not handed one), the
    same TRUSTED_PROXY_HOPS environment variable the settings read is used."""
    hops = getattr(settings, "trusted_proxy_hops", None)
    if hops is None:
        hops = os.environ.get("TRUSTED_PROXY_HOPS", "0")
    return client_address(
        request.client.host if request.client else None,
        request.headers.get("x-forwarded-for"),
        int(hops or 0),
    )


def build_current_user_dependency(get_db: Callable[..., Session], settings) -> Callable[..., UserRead]:
    def get_current_user(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        access_token: str | None = Cookie(default=None, alias="idp_access_token"),
        db: Session = Depends(get_db),
    ) -> UserRead:
        token_value = credentials.credentials if credentials is not None else access_token
        if token_value is None:
            raise UnauthorizedError("Authentication required.")

        # A `pw_` credential is a long-lived API token, resolved against the
        # token table; anything else is a login JWT.
        if looks_like_api_token(token_value):
            user, api_token = authenticate_api_token(db, token_value)
            scope = api_token.scope
            # Who it was, for the audit log, refused or not: an API token is not
            # a JWT the log can read for itself (A8, Y6), and which token is
            # part of the answer (X2).
            request.state.audit_actor = (user.id, user.username)
            request.state.audit_credential = f"API token “{api_token.name}” ({api_token.prefix})"[:160]
            if not scope_allows(scope, request.method):
                raise ForbiddenError(
                    f"This API token is {scope}-scoped and cannot make a "
                    f"{request.method} request."
                )
            projects = token_projects(api_token)
            if projects is not None:
                refusal = limited_refusal(projects, request.method, request.url.path)
                if refusal:
                    raise ForbiddenError(refusal)
            # An organisation's network list covers scripts as well as people.
            check_network(db, user, request_address(request, settings))
            read = UserRead.model_validate(user)
            return read.model_copy(update={"token_project_ids": sorted(projects)}) if projects is not None else read

        token = decode_access_token(
            token_value,
            secret_key=settings.auth_jwt_secret,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
        )
        user = get_user_by_id(db, uuid.UUID(token.sub))
        if user is None or not user.is_active:
            raise UnauthorizedError("Authenticated user is no longer available.")
        # A session that predates a password change, forced reset or
        # sign-out-everywhere carries an older version and is refused, even
        # though its signature is still valid and unexpired.
        if token.ver != user.token_version:
            raise UnauthorizedError("This session has ended. Sign in again.")
        check_network(db, user, request_address(request, settings))
        request.state.audit_actor = (user.id, user.username)
        return UserRead.model_validate(user)

    return get_current_user
