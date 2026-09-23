"""The public HTTP endpoints for OIDC single sign-on.

Three routes, all unauthenticated by design (a person signing in has no session
yet): a status the login screen reads to decide whether to offer SSO, the start
that redirects to the provider, and the callback that turns a provider's code
into a session cookie and drops the browser back into the app. Errors redirect
to the login screen with a message rather than showing a raw JSON error to
someone mid-sign-in.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from api_gateway import sso_flow
from service_enterprise.sso import saml_status
from shared_python.auth.security import create_access_token
from shared_python.errors import ApplicationError
from shared_python.logging import get_logger

logger = get_logger(__name__)

# The session cookie the web app reads (see apps/web .../auth/session.ts). The
# SSO callback sets the same cookie the password flow's client code sets, so a
# browser arriving from the provider lands already signed in.
ACCESS_TOKEN_COOKIE = "idp_access_token"


def _safe_next(raw: str | None) -> str:
    # Only same-site relative paths: an open redirect through `next` would let a
    # crafted link bounce a freshly-signed-in user to an attacker's page.
    if raw and raw.startswith("/") and not raw.startswith("//"):
        return raw
    return "/"


def build_router(get_db: Callable[..., Session], settings) -> APIRouter:
    router = APIRouter(prefix="/auth/sso", tags=["auth"])

    def _login_redirect(message: str) -> RedirectResponse:
        query = urlencode({"sso_error": message})
        return RedirectResponse(f"{settings.web_base_url}/login?{query}", status_code=303)

    @router.get("/status")
    def sso_status() -> dict:
        """Whether SSO is available, and the plain truth about SAML."""
        return {
            "oidc_configured": sso_flow.is_configured(settings),
            "saml": saml_status(),
        }

    @router.get("/start")
    def sso_start(
        next: str = Query(default="/"),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        try:
            sso_flow.sweep_expired_states(db)
            url = sso_flow.begin_login(db, settings=settings, next_path=_safe_next(next))
        except ApplicationError as exc:
            return _login_redirect(str(exc))
        except Exception:  # noqa: BLE001 - a provider we cannot reach is a sign-in failure
            logger.exception("sso_start_failed")
            return _login_redirect("Could not reach the identity provider.")
        return RedirectResponse(url, status_code=302)

    @router.get("/callback")
    def sso_callback(
        db: Session = Depends(get_db),
        code: str | None = Query(default=None),
        state: str | None = Query(default=None),
        error: str | None = Query(default=None),
    ) -> RedirectResponse:
        if error:
            return _login_redirect(f"The identity provider refused the sign-in: {error}.")
        if not code or not state:
            return _login_redirect("The sign-in response was incomplete.")
        try:
            user, next_path = sso_flow.complete_login(
                db, settings=settings, code=code, state=state
            )
        except ApplicationError as exc:
            return _login_redirect(str(exc))
        except Exception:  # noqa: BLE001 - any failure here is a failed sign-in
            logger.exception("sso_callback_failed")
            return _login_redirect("That sign-in could not be completed.")

        token, expires_in = create_access_token(
            user_id=str(user.id),
            username=user.username,
            secret_key=settings.auth_jwt_secret,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            expires_minutes=settings.auth_access_token_exp_minutes,
            token_version=user.token_version,
        )
        response = RedirectResponse(f"{settings.web_base_url}{next_path}", status_code=303)
        # Same cookie the password flow sets: the web reads it both server-side
        # (SSR) and client-side. Not http-only, matching the existing scheme
        # where client requests read the token from this cookie.
        response.set_cookie(
            ACCESS_TOKEN_COOKIE,
            token,
            max_age=expires_in,
            path="/",
            samesite="lax",
        )
        return response

    return router
