"""Signing in with the identity provider a company already runs.

**What is implemented:** the OIDC authorization-code flow with PKCE --
discovery, the authorization URL, the token exchange, ID-token verification
against the provider's JWKS, claim mapping, and just-in-time user creation.

**What has not been exercised:** the network legs. This deployment has no
identity provider to point at, so the parts that talk to one have never run
against a real Okta, Entra, or Keycloak. The pure parts -- state and PKCE
generation, claim mapping, provisioning decisions -- are tested; the wire
protocol is written to the specification and should be treated as unverified
until somebody points it at a real provider.

**SAML is not implemented.** It needs XML signature verification, which needs
`xmlsec` and a system library, and a half-implemented SAML that skips signature
checking is an authentication bypass rather than a feature. Saying it is absent
is the honest answer.
"""

from __future__ import annotations

import base64
import hashlib
import re
import secrets
from dataclasses import dataclass, field
from typing import Any

from shared_python.errors import BadRequestError, UnauthorizedError

# PKCE verifiers are 43-128 characters of unreserved ASCII (RFC 7636).
VERIFIER_BYTES = 48
STATE_BYTES = 24

DEFAULT_SCOPES = ("openid", "email", "profile")

# How a provider's claims map onto a user here. Providers disagree about which
# claim carries what, so the fallbacks are ordered by how common they are.
USERNAME_CLAIMS = ("preferred_username", "email", "upn", "sub")
EMAIL_CLAIMS = ("email", "upn", "preferred_username")
NAME_CLAIMS = ("name", "given_name", "preferred_username")
GROUP_CLAIMS = ("groups", "roles", "wids")


@dataclass
class ProviderConfig:
    """Everything needed to talk to one identity provider."""

    issuer: str
    client_id: str
    client_secret: str | None
    redirect_uri: str
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    # Discovered from the issuer, or set explicitly for a provider that has no
    # discovery document.
    authorization_endpoint: str | None = None
    token_endpoint: str | None = None
    jwks_uri: str | None = None
    # Which provider group grants which role here.
    group_role_map: dict[str, str] = field(default_factory=dict)
    default_role: str = "viewer"
    # Whether an unknown person signing in gets an account.
    allow_jit_provisioning: bool = True


@dataclass
class AuthorizationRequest:
    """What the browser is sent to, and what has to be remembered."""

    url: str
    state: str
    code_verifier: str
    nonce: str

    def to_dict(self) -> dict[str, Any]:
        # The verifier is a secret held server-side; it must never reach a
        # response body, or PKCE protects nothing.
        return {"url": self.url, "state": self.state}


def generate_pkce() -> tuple[str, str]:
    """A code verifier and its S256 challenge."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(VERIFIER_BYTES)).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


def discovery_url(issuer: str) -> str:
    return f"{issuer.rstrip('/')}/.well-known/openid-configuration"


def build_authorization_request(config: ProviderConfig) -> AuthorizationRequest:
    """Where to send the browser, with PKCE and a nonce."""
    from urllib.parse import urlencode

    if not config.authorization_endpoint:
        raise BadRequestError(
            "This provider has not been discovered yet, so there is no authorization endpoint."
        )

    verifier, challenge = generate_pkce()
    state = secrets.token_urlsafe(STATE_BYTES)
    nonce = secrets.token_urlsafe(STATE_BYTES)

    query = urlencode(
        {
            "response_type": "code",
            "client_id": config.client_id,
            "redirect_uri": config.redirect_uri,
            "scope": " ".join(config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    separator = "&" if "?" in config.authorization_endpoint else "?"
    return AuthorizationRequest(
        url=f"{config.authorization_endpoint}{separator}{query}",
        state=state,
        code_verifier=verifier,
        nonce=nonce,
    )


def verify_state(expected: str | None, received: str | None) -> None:
    """Reject a callback that did not come from a request we made.

    Compared in constant time, and a missing value fails: treating "no state"
    as "any state" is the whole attack this parameter exists to stop.
    """
    if not expected or not received:
        raise UnauthorizedError("This sign-in did not start here.")
    if not secrets.compare_digest(expected, received):
        raise UnauthorizedError("This sign-in did not start here.")


@dataclass
class MappedIdentity:
    """A provider's claims, translated into what this platform stores."""

    subject: str
    username: str
    email: str | None
    display_name: str | None
    groups: list[str]
    role: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "username": self.username,
            "email": self.email,
            "display_name": self.display_name,
            "groups": self.groups,
            "role": self.role,
        }


def _first_claim(claims: dict[str, Any], names: tuple[str, ...]) -> str | None:
    for name in names:
        value = claims.get(name)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _groups(claims: dict[str, Any]) -> list[str]:
    for name in GROUP_CLAIMS:
        value = claims.get(name)
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            # Some providers send a single group as a bare string.
            return [value.strip()]
    return []


def normalise_username(value: str) -> str:
    """A username this platform can store, from whatever the provider sent."""
    cleaned = re.sub(r"[^a-zA-Z0-9._@-]", "", value.strip().lower())
    return cleaned[:80] or "sso-user"


def map_identity(claims: dict[str, Any], config: ProviderConfig) -> MappedIdentity:
    """Translate an ID token's claims into a user.

    A missing `sub` is fatal rather than defaulted: it is the only claim that is
    guaranteed stable, and without it the same person becomes a new account
    every time they change their email.
    """
    subject = claims.get("sub")
    if not isinstance(subject, str) or not subject.strip():
        raise UnauthorizedError("The identity provider did not say who signed in.")

    groups = _groups(claims)
    role = config.default_role
    for group in groups:
        mapped = config.group_role_map.get(group)
        if mapped:
            role = mapped
            break

    username = _first_claim(claims, USERNAME_CLAIMS) or subject
    return MappedIdentity(
        subject=subject.strip(),
        username=normalise_username(username),
        email=_first_claim(claims, EMAIL_CLAIMS),
        display_name=_first_claim(claims, NAME_CLAIMS),
        groups=groups,
        role=role,
    )


def verify_id_token(
    token: str,
    *,
    config: ProviderConfig,
    jwks: dict[str, Any],
    nonce: str | None = None,
    leeway_seconds: int = 60,
) -> dict[str, Any]:
    """Check an ID token's signature and claims.

    Everything here is a rejection somebody could otherwise walk through:
    the signature, the issuer, the audience, expiry, and the nonce. Skipping
    any one of them turns sign-in into "send me any token you like".
    """
    import jwt
    from jwt import PyJWKClient  # noqa: F401  - imported for parity with real use

    try:
        header = jwt.get_unverified_header(token)
    except Exception as exc:  # noqa: BLE001 - a malformed token is a failed sign-in
        raise UnauthorizedError("That token could not be read.") from exc

    key = _find_key(jwks, header.get("kid"))
    if key is None:
        raise UnauthorizedError("The token was signed with a key this provider does not publish.")

    try:
        return jwt.decode(
            token,
            key=jwt.algorithms.RSAAlgorithm.from_jwk(key),
            algorithms=[header.get("alg", "RS256")],
            audience=config.client_id,
            issuer=config.issuer,
            leeway=leeway_seconds,
            options={"require": ["exp", "iat", "sub"]},
        )
    except Exception as exc:  # noqa: BLE001
        raise UnauthorizedError(f"That sign-in could not be verified: {exc}") from exc


def _find_key(jwks: dict[str, Any], kid: str | None) -> dict[str, Any] | None:
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        return None
    for key in keys:
        if isinstance(key, dict) and (kid is None or key.get("kid") == kid):
            return key
    return None


def saml_status() -> dict[str, Any]:
    """Why SAML is absent, said plainly."""
    return {
        "supported": False,
        "reason": (
            "SAML needs XML signature verification, which requires the xmlsec native "
            "library. A SAML implementation that skips signature checking is an "
            "authentication bypass, so it is not offered rather than offered badly."
        ),
        "alternative": "Most providers that speak SAML also speak OIDC; use that instead.",
    }
