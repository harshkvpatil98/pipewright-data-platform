from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import Cookie, Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_auth.service import get_user_by_id
from shared_python.auth.security import decode_access_token
from shared_python.errors import UnauthorizedError

bearer_scheme = HTTPBearer(auto_error=False)


def build_current_user_dependency(get_db: Callable[..., Session], settings) -> Callable[..., UserRead]:
    def get_current_user(
        credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
        access_token: str | None = Cookie(default=None, alias="idp_access_token"),
        db: Session = Depends(get_db),
    ) -> UserRead:
        token_value = credentials.credentials if credentials is not None else access_token
        if token_value is None:
            raise UnauthorizedError("Authentication required.")
        token = decode_access_token(
            token_value,
            secret_key=settings.auth_jwt_secret,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
        )
        user = get_user_by_id(db, uuid.UUID(token.sub))
        if user is None or not user.is_active:
            raise UnauthorizedError("Authenticated user is no longer available.")
        return UserRead.model_validate(user)

    return get_current_user
