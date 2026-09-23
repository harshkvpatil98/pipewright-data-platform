"""The two requests that turn SAML's pure logic into a sign-in.

`service_enterprise.saml` holds everything that can be decided without a
database or a network: building the authentication request, verifying an
assertion's signature, and checking its conditions. This composes those with the
two things that touch state -- remembering the request id between the redirect
and the assertion, and provisioning the person the assertion describes.

Provisioning is deliberately *not* reimplemented here. `sso_flow.provision_user`
already decides how an identity becomes a user, including the rule that an
existing person is never silently demoted, and a second copy of that decision
would be a second place for the rules to drift. SAML maps its assertion into the
same claim shape OIDC produces, so the same mapper and the same provisioner run
for both protocols.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from api_gateway.sso_flow import provision_user
from service_auth.models import User
from service_enterprise.models import SamlLoginState
from service_enterprise.saml import (
    build_authn_request,
    config_from_settings,
    is_configured,
    saml_status,
    sp_metadata_xml,
    unverified_in_response_to,
    verify_response,
)
from service_enterprise.sso import map_identity
from shared_python.errors import BadRequestError, UnauthorizedError
from shared_python.logging import get_logger

logger = get_logger(__name__)

# The window between being sent to the provider and coming back. Longer than the
# OIDC equivalent because a SAML sign-in often includes a fresh password prompt
# and a second factor at the provider.
REQUEST_TTL = timedelta(minutes=15)


def configured(settings) -> bool:
    return is_configured(config_from_settings(settings))


def status(settings) -> dict[str, Any]:
    return saml_status(config_from_settings(settings))


def metadata(settings) -> str:
    config = config_from_settings(settings)
    if not is_configured(config):
        raise BadRequestError("SAML is not configured on this deployment.")
    return sp_metadata_xml(config)


def begin_login(
    db: Session,
    *,
    settings,
    next_path: str = "/",
    now: datetime | None = None,
) -> str:
    """Build the redirect to the identity provider and remember the request."""
    config = config_from_settings(settings)
    if not is_configured(config):
        raise BadRequestError("SAML single sign-on is not configured on this deployment.")

    request = build_authn_request(config, now=now)
    moment = now or datetime.now(UTC)
    db.add(
        SamlLoginState(
            request_id=request.request_id,
            next_path=next_path if next_path.startswith("/") else "/",
            expires_at=moment + REQUEST_TTL,
        )
    )
    db.commit()
    return request.url


def complete_login(
    db: Session,
    *,
    settings,
    saml_response: str,
    now: datetime | None = None,
) -> tuple[User, str]:
    """Verify an assertion and return (user, next_path).

    The remembered request is consumed before the identity is provisioned, so
    replaying the same assertion finds nothing to bind to and is refused -- the
    same one-time rule the OIDC state follows.
    """
    config = config_from_settings(settings)
    if not is_configured(config):
        raise BadRequestError("SAML single sign-on is not configured on this deployment.")

    moment = now or datetime.now(UTC)
    request_id = unverified_in_response_to(saml_response)
    row = db.scalar(select(SamlLoginState).where(SamlLoginState.request_id == request_id))
    if row is None:
        # No row means we never sent this request, or it has already been spent.
        raise UnauthorizedError("This sign-in did not start here.")

    expires = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=UTC)
    next_path = row.next_path
    # One-time: spend the row before verifying, so a response that fails
    # verification cannot be retried against the same request either.
    db.delete(row)
    db.commit()

    if expires < moment:
        raise UnauthorizedError("This sign-in took too long. Start again.")

    claims = verify_response(
        saml_response, config=config, expected_request_id=request_id, now=moment
    )
    identity = map_identity(claims, config)
    # `provision_user` reads the two OIDC provisioning knobs by name, and SAML
    # shares them on purpose (see `config_from_settings`).
    user = provision_user(db, identity, settings=settings)
    return user, next_path


def sweep_expired_states(db: Session, *, now: datetime | None = None) -> int:
    """Delete stale request rows. Called opportunistically on start."""
    moment = now or datetime.now(UTC)
    rows = list(db.scalars(select(SamlLoginState).where(SamlLoginState.expires_at < moment)).all())
    for row in rows:
        db.delete(row)
    if rows:
        db.commit()
    return len(rows)
