#!/usr/bin/env python
"""Check single sign-on against the identity provider this deployment names.

The OIDC logic is tested automatically with the provider imitated; this is
the check against a real one (Okta, Entra ID, Google, Auth0 and so on). Run it
from the repository root with the gateway's settings in place:

    .venv/bin/python scripts/check-oidc.py               # settings and network
    .venv/bin/python scripts/check-oidc.py --sign-in     # and a real sign-in

Without --sign-in it checks the settings, fetches the provider's discovery
document and signing keys, and makes a token request with a made-up code: a
provider that answers "invalid_grant" has accepted the client id and secret.

With --sign-in it also prints an address to open in a browser. Sign in there;
the provider sends the browser back to the redirect address, where the
gateway refuses it (it did not start this sign-in, so the code stays unused).
Paste that full address here and the script exchanges the code, verifies the
ID token against the provider's keys and this sign-in's nonce, and shows the
account and role Pipewright would give. Nothing is written to the database.

Exit status is 0 when every check passed, 1 otherwise.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
for source in [ROOT / "apps/api-gateway/src", *ROOT.glob("services/*/src"), ROOT / "packages/shared-python/src"]:
    sys.path.insert(0, str(source))

import httpx  # noqa: E402

from api_gateway import sso_flow  # noqa: E402
from api_gateway.config import get_settings  # noqa: E402
from service_enterprise.sso import (  # noqa: E402
    RSA_ALGORITHMS,
    build_authorization_request,
    map_identity,
    verify_id_token,
)

CALLBACK_SUFFIX = "/api/v1/auth/sso/callback"


class Report:
    def __init__(self) -> None:
        self.failed = 0

    def ok(self, text: str) -> None:
        print(f"  ✓ {text}")

    def fail(self, text: str) -> None:
        self.failed += 1
        print(f"  ✗ {text}")

    def note(self, text: str) -> None:
        print(f"    {text}")


def check_settings(settings, report: Report) -> bool:
    print("Settings")
    missing = [
        name
        for name, value in (
            ("OIDC_ISSUER", settings.oidc_issuer),
            ("OIDC_CLIENT_ID", settings.oidc_client_id),
            ("OIDC_REDIRECT_URI", settings.oidc_redirect_uri),
        )
        if not value
    ]
    if missing:
        report.fail(f"Not set: {', '.join(missing)}. Single sign-on is off until they are.")
        return False
    report.ok(f"Provider {settings.oidc_issuer}, client {settings.oidc_client_id}")
    if not settings.oidc_client_secret:
        report.note("No client secret: fine for a public client, refused by most providers otherwise.")
    if settings.oidc_redirect_uri.rstrip("/").endswith(CALLBACK_SUFFIX):
        report.ok(f"Redirect address {settings.oidc_redirect_uri}")
    else:
        report.fail(f"OIDC_REDIRECT_URI should end in {CALLBACK_SUFFIX}; it is {settings.oidc_redirect_uri}")
    try:
        sso_flow._group_role_map(settings)
        report.ok(f"Group to role map read; everyone else gets {settings.oidc_default_role}")
    except Exception as exc:  # noqa: BLE001
        report.fail(f"OIDC_GROUP_ROLE_MAP could not be read: {exc}")
    return True


def check_provider(settings, report: Report) -> dict | None:
    print("Provider")
    try:
        discovery = sso_flow.fetch_discovery(settings.oidc_issuer)
    except Exception as exc:  # noqa: BLE001
        report.fail(f"The discovery document could not be fetched: {exc}")
        return None
    report.ok("Discovery document fetched")
    if discovery.get("issuer") != settings.oidc_issuer:
        report.fail(
            f"The provider calls itself {discovery.get('issuer')!r}, not {settings.oidc_issuer!r}. "
            "ID tokens are checked against OIDC_ISSUER, so they must match exactly."
        )
    else:
        report.ok("Issuer matches")
    for field in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not discovery.get(field):
            report.fail(f"The discovery document has no {field}")
    if "S256" in (discovery.get("code_challenge_methods_supported") or ["S256"]):
        report.ok("Supports PKCE with S256")
    else:
        report.fail("The provider does not list S256 for PKCE")

    try:
        jwks = sso_flow.fetch_jwks(discovery["jwks_uri"])
        keys = [key for key in jwks.get("keys", []) if key.get("kty") == "RSA"]
        if keys:
            report.ok(f"Signing keys fetched: {len(keys)} RSA")
        else:
            report.fail("The provider publishes no RSA signing key; Pipewright verifies RSA signatures only")
        signing = set(discovery.get("id_token_signing_alg_values_supported") or ["RS256"])
        if not signing & RSA_ALGORITHMS:
            report.fail(f"ID tokens are signed with {sorted(signing)}; Pipewright accepts {sorted(RSA_ALGORITHMS)}")
    except Exception as exc:  # noqa: BLE001
        report.fail(f"The signing keys could not be fetched: {exc}")

    # A made-up code: "invalid_grant" means the client was accepted and only
    # the code refused; "invalid_client" means the id or secret is wrong.
    try:
        response = httpx.post(
            discovery["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": "pipewright-check-not-a-real-code",
                "redirect_uri": settings.oidc_redirect_uri,
                "client_id": settings.oidc_client_id,
                "client_secret": settings.oidc_client_secret or "",
                "code_verifier": "pipewright-check-" + "x" * 30,
            },
            timeout=sso_flow.HTTP_TIMEOUT,
        )
        error = (response.json() if "json" in response.headers.get("content-type", "") else {}).get("error")
        if error == "invalid_grant":
            report.ok("Client id and secret accepted (the made-up code was refused, as it should be)")
        elif error == "invalid_client" or response.status_code == 401:
            report.fail("The provider refused the client: check OIDC_CLIENT_ID and OIDC_CLIENT_SECRET")
        else:
            report.note(f"The token request answered {response.status_code} {error or response.text[:120]}; "
                        "run with --sign-in to settle it")
    except Exception as exc:  # noqa: BLE001
        report.fail(f"The token address could not be reached: {exc}")
    return discovery


def check_sign_in(settings, discovery: dict, report: Report) -> None:
    print("Sign-in")
    config = sso_flow._config_from_settings(settings, discovery)
    request = build_authorization_request(config)
    print("\n  Open this address in a browser and sign in:\n")
    print(f"  {request.url}\n")
    print("  The browser comes back to the redirect address. The page there will refuse the")
    print("  sign-in, which is expected. Copy the full address from the address bar and paste it:\n")
    returned = input("  > ").strip()
    query = parse_qs(urlparse(returned).query)
    if "error" in query:
        report.fail(f"The provider refused the sign-in: {query['error'][0]} {query.get('error_description', [''])[0]}")
        return
    code, state = query.get("code", [None])[0], query.get("state", [None])[0]
    if not code or state != request.state:
        report.fail("That address does not carry this sign-in's code and state")
        return
    try:
        tokens = sso_flow.exchange_code(
            token_endpoint=config.token_endpoint,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": config.redirect_uri,
                "client_id": config.client_id,
                "client_secret": config.client_secret or "",
                "code_verifier": request.code_verifier,
            },
        )
        report.ok("Code exchanged for tokens")
        claims = verify_id_token(
            tokens["id_token"], config=config, jwks=sso_flow.fetch_jwks(config.jwks_uri), nonce=request.nonce
        )
        report.ok("ID token verified: signature, issuer, audience, expiry and nonce")
        identity = map_identity(claims, config)
        report.ok(
            f"Signs in as {identity.username} ({identity.email or 'no email'}), "
            f"groups {identity.groups or 'none'}, role {identity.role}"
        )
    except Exception as exc:  # noqa: BLE001
        report.fail(f"The sign-in could not be completed: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check single sign-on against the configured provider.")
    parser.add_argument("--sign-in", action="store_true", help="also complete a real sign-in in a browser")
    arguments = parser.parse_args()

    settings = get_settings()
    report = Report()
    if check_settings(settings, report):
        discovery = check_provider(settings, report)
        if discovery and arguments.sign_in and not report.failed:
            check_sign_in(settings, discovery, report)
    print()
    if report.failed:
        print(f"{report.failed} check{'s' if report.failed != 1 else ''} failed.")
        return 1
    print("Every check passed." if arguments.sign_in else "Every check passed. Run with --sign-in for a real sign-in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
