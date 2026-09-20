from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.dependencies import build_current_user_dependency
from service_auth.schemas import (
    LoginRequest,
    PreferencesRead,
    PreferencesUpdate,
    TokenResponse,
    UserCreateRequest,
    UserListResponse,
    UserRead,
    UserUpdateRequest,
)
from service_auth.service import (
    authenticate_user,
    create_user,
    delete_user,
    get_preferences,
    list_users,
    set_preferences,
    update_user,
)
from shared_python.auth.security import create_access_token
from shared_python.errors import ForbiddenError


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
    def me(
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> UserRead:
        # Preferences ride along so the shell can paint the right theme
        # immediately instead of fetching them and flashing the wrong one.
        return user.model_copy(update={"preferences": get_preferences(db, user.id)})

    @router.get("/me/preferences", response_model=PreferencesRead)
    def read_preferences(
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> PreferencesRead:
        return get_preferences(db, user.id)

    @router.patch("/me/preferences", response_model=PreferencesRead)
    def update_preferences(
        payload: PreferencesUpdate,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> PreferencesRead:
        return set_preferences(db, user.id, payload)

    @router.get("/users", response_model=UserListResponse)
    def read_users(
        db: Session = Depends(get_db),
        _user: UserRead = Depends(current_user),
    ) -> UserListResponse:
        """Everyone with an account.

        Readable by any signed-in user: adding a colleague to a project means
        typing their username, and a picker that only admins can see would make
        that a guessing game. Only the username and status are exposed.
        """
        return UserListResponse(
            items=[UserRead.model_validate(row) for row in list_users(db)]
        )

    @router.post(
        "/users", response_model=UserRead, status_code=status.HTTP_201_CREATED
    )
    def add_user(
        payload: UserCreateRequest,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> UserRead:
        """Create an account for a colleague.

        Platform admins only. Project membership decides what someone may do
        inside a project; this decides whether they exist at all.
        """
        if actor.role != "admin":
            raise ForbiddenError("Only a platform admin can create accounts.")
        return UserRead.model_validate(create_user(db, payload))

    @router.patch("/users/{user_id}", response_model=UserRead)
    def change_user(
        user_id: uuid.UUID,
        payload: UserUpdateRequest,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> UserRead:
        """Deactivate an account, reactivate it, or change its platform role.

        Platform admins only, for the same reason creating one is: this decides
        whether somebody can reach the platform at all.

        Deactivating is the offboarding path. `is_active` was already checked on
        every login and every authenticated request, and nothing could set it --
        so an account, once created, could never be withdrawn.
        """
        if actor.role != "admin":
            raise ForbiddenError("Only a platform admin can change accounts.")
        return UserRead.model_validate(update_user(db, user_id, payload, actor))

    @router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_user(
        user_id: uuid.UUID,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> None:
        """Delete an account.

        Deactivation is usually the right call -- it keeps the person's name on
        the projects and runs they own. This refuses outright when deleting
        would strand something, rather than doing it quietly.
        """
        if actor.role != "admin":
            raise ForbiddenError("Only a platform admin can delete accounts.")
        delete_user(db, user_id, actor)

    @router.get("/protected", response_model=dict[str, str])
    def protected_example(user: UserRead = Depends(current_user)) -> dict[str, str]:
        return {"message": f"Authenticated as {user.username}."}

    return router
