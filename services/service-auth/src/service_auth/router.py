from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.dependencies import build_current_user_dependency
from service_auth.schemas import LoginRequest, TokenResponse, UserRead
from service_auth.service import authenticate_user
from shared_python.auth.security import create_access_token


def build_router(get_db: Callable[..., Session], settings) -> APIRouter:
    router = APIRouter(prefix="/auth", tags=["auth"])
    current_user = build_current_user_dependency(get_db, settings)

    @router.post("/login", response_model=TokenResponse, status_code=status.HTTP_200_OK)
    def login(payload: LoginRequest, db: Session = Depends(get_db)) -> TokenResponse:
        user = authenticate_user(db, payload.username, payload.password)
        token, expires_in = create_access_token(
            user_id=str(user.id),
            username=user.username,
            secret_key=settings.auth_jwt_secret,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            expires_minutes=settings.auth_access_token_exp_minutes,
        )
        return TokenResponse(
            access_token=token,
            expires_in=expires_in,
            user=UserRead.model_validate(user),
        )

    @router.get("/me", response_model=UserRead)
    def me(user: UserRead = Depends(current_user)) -> UserRead:
        return user

    @router.get("/protected", response_model=dict[str, str])
    def protected_example(user: UserRead = Depends(current_user)) -> dict[str, str]:
        return {"message": f"Authenticated as {user.username}."}

    return router
