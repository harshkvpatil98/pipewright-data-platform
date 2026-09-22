from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Cookie, Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_auth.service import get_user_by_id
from service_auth.tokens import authenticate_api_token, looks_like_api_token, scope_allows
from shared_python.auth.security import decode_access_token
from shared_python.errors import ForbiddenError, UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False)


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
            user, scope = authenticate_api_token(db, token_value)
            if not scope_allows(scope, request.method):
                raise ForbiddenError(
                    f"This API token is {scope}-scoped and cannot make a "
                    f"{request.method} request."
                )
            return UserRead.model_validate(user)

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
        return UserRead.model_validate(user)

    return get_current_user
