from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from service_auth.codes import DEFAULT_TTL_MINUTES, RESET, issue_code
from service_auth.dependencies import build_current_user_dependency
from service_auth import mfa as mfa_service
from service_auth.schemas import (
    ApiTokenCreate,
    ApiTokenCreatedResponse,
    ApiTokenListResponse,
    ApiTokenRead,
    InviteRequest,
    LoginRequest,
    LoginResult,
    MfaActivateRequest,
    MfaDisableRequest,
    MfaEnrollResponse,
    MfaLoginRequest,
    MfaRecoveryCodesResponse,
    MfaStatusResponse,
    OneTimeCodeResponse,
    PasswordChangeRequest,
    PreferencesRead,
    PreferencesUpdate,
    ProfileUpdate,
    RedeemCodeRequest,
    TokenResponse,
    UserCreateRequest,
    UserListResponse,
    UserRead,
    UserUpdateRequest,
)
from service_auth.service import (
    authenticate_user,
    change_password,
    create_user,
    delete_user,
    get_preferences,
    get_user_by_id,
    deliver_one_time_code,
    invite_user,
    list_users,
    set_password_with_code,
    set_preferences,
    sign_out_everywhere,
    update_profile,
    update_user,
)
from service_auth.tokens import (
    create_api_token,
    list_api_tokens,
    revoke_api_token,
)
from shared_python.auth.security import create_access_token
from shared_python.errors import ForbiddenError


def build_router(get_db: Callable[..., Session], settings, email_sender=None) -> APIRouter:
    """`email_sender` (optional, injected by the gateway) sends invitation and
    reset emails; without it the one-time codes are returned to the admin."""
    router = APIRouter(prefix="/auth", tags=["auth"])
    current_user = build_current_user_dependency(get_db, settings)

    def _issue_token(user) -> TokenResponse:
        token, expires_in = create_access_token(
            user_id=str(user.id),
            username=user.username,
            secret_key=settings.auth_jwt_secret,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            expires_minutes=settings.auth_access_token_exp_minutes,
            token_version=user.token_version,
        )
        return TokenResponse(
            access_token=token, expires_in=expires_in, user=UserRead.model_validate(user)
        )

    def _require_admin(actor: UserRead, verb: str) -> None:
        if actor.role != "admin":
            raise ForbiddenError(f"Only a platform admin can {verb}.")

    def _ok_result(user) -> LoginResult:
        issued = _issue_token(user)
        return LoginResult(
            status="ok",
            access_token=issued.access_token,
            expires_in=issued.expires_in,
            user=issued.user,
        )

    @router.post("/login", response_model=LoginResult, status_code=status.HTTP_200_OK)
    def login(payload: LoginRequest, db: Session = Depends(get_db)) -> LoginResult:
        user = authenticate_user(db, payload.username, payload.password)
        # A password alone is not enough once a second factor is on: hand back a
        # short-lived ticket instead of a session, and demand the code next.
        if mfa_service.is_active(db, user.id):
            return LoginResult(
                status="mfa_required",
                mfa_ticket=mfa_service.mint_mfa_ticket(user_id=user.id, settings=settings),
            )
        return _ok_result(user)

    @router.post("/login/mfa", response_model=LoginResult, status_code=status.HTTP_200_OK)
    def login_mfa(payload: MfaLoginRequest, db: Session = Depends(get_db)) -> LoginResult:
        """Second step: exchange the ticket plus a TOTP or recovery code for a
        session. The ticket proves the password already passed."""
        user_id = mfa_service.verify_mfa_ticket(payload.mfa_ticket, settings=settings)
        user = get_user_by_id(db, user_id)
        if user is None or not user.is_active:
            raise ForbiddenError("This account cannot sign in.")
        if not mfa_service.verify_second_factor(db, user_id=user_id, code=payload.code):
            raise ForbiddenError("That code is not right.")
        return _ok_result(user)

    @router.get("/me", response_model=UserRead)
    def me(db: Session = Depends(get_db), user: UserRead = Depends(current_user)) -> UserRead:
        # Preferences ride along so the shell paints the right theme at once.
        return user.model_copy(update={"preferences": get_preferences(db, user.id)})

    @router.patch("/me", response_model=UserRead)
    def edit_profile(
        payload: ProfileUpdate,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> UserRead:
        return UserRead.model_validate(
            update_profile(
                db, user_id=user.id, display_name=payload.display_name, email=payload.email
            )
        )

    @router.patch("/me/password", status_code=status.HTTP_204_NO_CONTENT)
    def change_own_password(
        payload: PasswordChangeRequest,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> None:
        change_password(
            db, user_id=user.id, current=payload.current_password, new=payload.new_password
        )

    @router.post("/me/sign-out-everywhere", status_code=status.HTTP_204_NO_CONTENT)
    def sign_out_all(
        db: Session = Depends(get_db), user: UserRead = Depends(current_user)
    ) -> None:
        sign_out_everywhere(db, user_id=user.id)

    # ---- second-factor authentication (TOTP) ----

    @router.get("/me/mfa", response_model=MfaStatusResponse)
    def mfa_status(
        db: Session = Depends(get_db), user: UserRead = Depends(current_user)
    ) -> MfaStatusResponse:
        state = mfa_service.status(db, user.id)
        return MfaStatusResponse(
            enrolled=state["enrolled"],
            active=state["active"],
            recovery_codes_remaining=mfa_service.remaining_recovery_codes(db, user.id),
        )

    @router.post("/me/mfa/enroll", response_model=MfaEnrollResponse, status_code=status.HTTP_201_CREATED)
    def mfa_enroll(
        db: Session = Depends(get_db), user: UserRead = Depends(current_user)
    ) -> MfaEnrollResponse:
        challenge = mfa_service.begin_enrollment(db, user=user, issuer=settings.auth_jwt_issuer)
        return MfaEnrollResponse(**challenge.to_dict())

    @router.post("/me/mfa/activate", response_model=MfaRecoveryCodesResponse)
    def mfa_activate(
        payload: MfaActivateRequest,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> MfaRecoveryCodesResponse:
        codes = mfa_service.activate(db, user_id=user.id, code=payload.code)
        return MfaRecoveryCodesResponse(recovery_codes=codes)

    @router.post("/me/mfa/recovery-codes", response_model=MfaRecoveryCodesResponse)
    def mfa_regenerate_recovery(
        payload: MfaDisableRequest,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> MfaRecoveryCodesResponse:
        # A live factor is required to mint a fresh set, so a walked-up-to
        # session cannot rotate someone else's recovery codes.
        if not mfa_service.verify_second_factor(db, user_id=user.id, code=payload.code):
            raise ForbiddenError("That code is not right.")
        return MfaRecoveryCodesResponse(
            recovery_codes=mfa_service.regenerate_recovery_codes(db, user_id=user.id)
        )

    @router.post("/me/mfa/disable", status_code=status.HTTP_204_NO_CONTENT)
    def mfa_disable(
        payload: MfaDisableRequest,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> None:
        if not mfa_service.verify_second_factor(db, user_id=user.id, code=payload.code):
            raise ForbiddenError("That code is not right.")
        mfa_service.disable(db, user_id=user.id)

    @router.post("/redeem-code", response_model=TokenResponse)
    def redeem_code_route(payload: RedeemCodeRequest, db: Session = Depends(get_db)) -> TokenResponse:
        """Set a password from a one-time activation or reset code, then sign in.

        Public by design: the whole point is that the person cannot sign in yet.
        """
        user = set_password_with_code(db, code=payload.code, new=payload.new_password)
        return _issue_token(user)

    @router.get("/me/preferences", response_model=PreferencesRead)
    def read_preferences(
        db: Session = Depends(get_db), user: UserRead = Depends(current_user)
    ) -> PreferencesRead:
        return get_preferences(db, user.id)

    @router.patch("/me/preferences", response_model=PreferencesRead)
    def update_preferences(
        payload: PreferencesUpdate,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> PreferencesRead:
        return set_preferences(db, user.id, payload)

    # ---- API tokens (self-service) ----

    @router.get("/tokens", response_model=ApiTokenListResponse)
    def list_tokens(
        db: Session = Depends(get_db), user: UserRead = Depends(current_user)
    ) -> ApiTokenListResponse:
        return ApiTokenListResponse(
            items=[ApiTokenRead.model_validate(t) for t in list_api_tokens(db, user_id=user.id)]
        )

    @router.post("/tokens", response_model=ApiTokenCreatedResponse, status_code=status.HTTP_201_CREATED)
    def create_token(
        payload: ApiTokenCreate,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> ApiTokenCreatedResponse:
        record, secret = create_api_token(
            db, user_id=user.id, name=payload.name, scope=payload.scope
        )
        return ApiTokenCreatedResponse(token=ApiTokenRead.model_validate(record), secret=secret)

    @router.delete("/tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
    def revoke_token(
        token_id: uuid.UUID,
        db: Session = Depends(get_db),
        user: UserRead = Depends(current_user),
    ) -> None:
        revoke_api_token(db, user_id=user.id, token_id=token_id)

    # ---- account administration (platform admins) ----

    @router.get("/users", response_model=UserListResponse)
    def read_users(
        db: Session = Depends(get_db), _user: UserRead = Depends(current_user)
    ) -> UserListResponse:
        """Everyone with an account. Readable by any signed-in user, because
        inviting a colleague to a project means typing their username."""
        return UserListResponse(items=[UserRead.model_validate(row) for row in list_users(db)])

    @router.post("/users", response_model=UserRead, status_code=status.HTTP_201_CREATED)
    def add_user(
        payload: UserCreateRequest,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> UserRead:
        _require_admin(actor, "create accounts")
        return UserRead.model_validate(create_user(db, payload))

    @router.post("/invite", response_model=OneTimeCodeResponse, status_code=status.HTTP_201_CREATED)
    def invite(
        payload: InviteRequest,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> OneTimeCodeResponse:
        """Create an inactive account and a one-time activation code.

        In a deployment with email configured the code is emailed; here it is
        handed back so an admin can pass it on.
        """
        _require_admin(actor, "invite people")
        user, code = invite_user(db, payload)
        return deliver_one_time_code(
            user=user, code=code, purpose="activation",
            expires_in_minutes=DEFAULT_TTL_MINUTES,
            web_base_url=getattr(settings, "web_base_url", ""),
            email_sender=email_sender,
        )

    @router.patch("/users/{user_id}", response_model=UserRead)
    def change_user(
        user_id: uuid.UUID,
        payload: UserUpdateRequest,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> UserRead:
        _require_admin(actor, "change accounts")
        return UserRead.model_validate(update_user(db, user_id, payload, actor))

    @router.post("/users/{user_id}/mfa/reset", status_code=status.HTTP_204_NO_CONTENT)
    def reset_user_mfa(
        user_id: uuid.UUID,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> None:
        """Clear a locked-out person's second factor so they can sign in with
        their password and re-enrol. An admin action, distinct from self-disable
        so the audit trail records who did it."""
        _require_admin(actor, "reset two-factor")
        mfa_service.admin_reset(db, user_id=user_id)

    @router.post(
        "/users/{user_id}/reset-code",
        response_model=OneTimeCodeResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def issue_reset_code(
        user_id: uuid.UUID,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> OneTimeCodeResponse:
        """Give an admin a one-time code to hand a locked-out colleague."""
        _require_admin(actor, "reset passwords")
        target = get_user_by_id(db, user_id)
        if target is None:
            raise ForbiddenError("User not found.")
        code = issue_code(db, user_id=user_id, purpose=RESET)
        return deliver_one_time_code(
            user=target, code=code, purpose="reset",
            expires_in_minutes=DEFAULT_TTL_MINUTES,
            web_base_url=getattr(settings, "web_base_url", ""),
            email_sender=email_sender,
        )

    @router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
    def remove_user(
        user_id: uuid.UUID,
        db: Session = Depends(get_db),
        actor: UserRead = Depends(current_user),
    ) -> None:
        _require_admin(actor, "delete accounts")
        delete_user(db, user_id, actor)

    @router.get("/protected", response_model=dict[str, str])
    def protected_example(user: UserRead = Depends(current_user)) -> dict[str, str]:
        return {"message": f"Authenticated as {user.username}."}

    return router
