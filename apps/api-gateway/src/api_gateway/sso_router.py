"""The public HTTP endpoints for single sign-on, OIDC and SAML.

All of these are unauthenticated by design -- a person signing in has no session
yet. For each protocol there is a start that redirects to the provider and a
return leg that turns the provider's answer into a session cookie; SAML adds a
metadata document an administrator uploads to the provider, and one shared
status the login screen reads to decide what to offer. Errors redirect to the
login screen with a message rather than showing a raw JSON error to someone
mid-sign-in.
"""

from __future__ import annotations

from collections.abc import Callable
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, Query
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from api_gateway import saml_flow, sso_flow
from service_auth.contracts import session_minutes_for
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
    # The prefix is `/auth` rather than `/auth/sso` so SAML's routes can live
    # beside OIDC's; every OIDC path below keeps the URL it already had.
    router = APIRouter(prefix="/auth", tags=["auth"])

    def _login_redirect(message: str) -> RedirectResponse:
        query = urlencode({"sso_error": message})
        return RedirectResponse(f"{settings.web_base_url}/login?{query}", status_code=303)

    def _signed_in(db: Session, user, next_path: str) -> RedirectResponse:
        """Issue the session and drop the browser back into the app.

        Shared by both protocols, so the session a SAML sign-in produces is the
        same session in every respect -- including the organisation's session
        policy, which would be easy to apply to one flow and forget in the
        other if this were written twice.
        """
        token, expires_in = create_access_token(
            user_id=str(user.id),
            username=user.username,
            secret_key=settings.auth_jwt_secret,
            issuer=settings.auth_jwt_issuer,
            audience=settings.auth_jwt_audience,
            expires_minutes=session_minutes_for(
                db, user.id, default=settings.auth_access_token_exp_minutes
            ),
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

    # ---- shared status ----

    @router.get("/sso/status")
    def sso_status() -> dict:
        """What sign-in methods this deployment actually offers."""
        return {
            "oidc_configured": sso_flow.is_configured(settings),
            "saml_configured": saml_flow.configured(settings),
            "saml": saml_flow.status(settings),
        }

    # ---- OIDC ----

    @router.get("/sso/start")
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

    @router.get("/sso/callback")
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
        return _signed_in(db, user, next_path)

    # ---- SAML ----

    @router.get("/saml/metadata")
    def saml_metadata() -> Response:
        """The service-provider metadata an administrator uploads to the IdP."""
        try:
            xml = saml_flow.metadata(settings)
        except ApplicationError as exc:
            # Not a browser mid-sign-in, so this one answers plainly.
            return Response(content=str(exc), status_code=404, media_type="text/plain")
        return Response(content=xml, media_type="application/samlmetadata+xml")

    @router.get("/saml/start")
    def saml_start(
        next: str = Query(default="/"),
        db: Session = Depends(get_db),
    ) -> RedirectResponse:
        try:
            saml_flow.sweep_expired_states(db)
            url = saml_flow.begin_login(db, settings=settings, next_path=_safe_next(next))
        except ApplicationError as exc:
            return _login_redirect(str(exc))
        except Exception:  # noqa: BLE001 - any failure here is a failed sign-in
            logger.exception("saml_start_failed")
            return _login_redirect("Could not start a SAML sign-in.")
        return RedirectResponse(url, status_code=302)

    @router.post("/saml/acs")
    def saml_acs(
        db: Session = Depends(get_db),
        SAMLResponse: str = Form(default=""),  # noqa: N803 - the binding names this field
        RelayState: str | None = Form(default=None),  # noqa: N803 - likewise
    ) -> RedirectResponse:
        """The assertion consumer service: the POST binding's landing point."""
        if not SAMLResponse:
            return _login_redirect("The sign-in response was incomplete.")
        try:
            user, next_path = saml_flow.complete_login(
                db, settings=settings, saml_response=SAMLResponse
            )
        except ApplicationError as exc:
            return _login_redirect(str(exc))
        except Exception:  # noqa: BLE001 - any failure here is a failed sign-in
            logger.exception("saml_acs_failed")
            return _login_redirect("That sign-in could not be completed.")
        return _signed_in(db, user, next_path)

    return router
