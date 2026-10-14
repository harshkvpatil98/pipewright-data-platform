#!/usr/bin/env python
"""Set up a Keycloak identity provider to sign in to Pipewright with.

Keycloak is a real OpenID Connect provider that runs in a container, so single
sign-on can be tried, and is tested in CI, against a live provider rather
than an imitation:

    docker run -d --name pw-keycloak -p 18080:8080 \\
      -e KC_BOOTSTRAP_ADMIN_USERNAME=admin -e KC_BOOTSTRAP_ADMIN_PASSWORD=keycloak-admin \\
      quay.io/keycloak/keycloak:26.0 start-dev
    .venv/bin/python scripts/sso-test-provider.py \\
      --redirect http://localhost:8000/api/v1/auth/sso/callback --web http://localhost:3000

It makes a realm `pipewright`, a confidential client with PKCE, a
`data-editors` group sent in a `groups` claim, and one person in that group,
then prints the gateway settings to use. For trying and testing only: the
passwords are fixed and written here.
"""

from __future__ import annotations

import argparse
import sys

import httpx

REALM = "pipewright"
CLIENT_ID = "pipewright"
CLIENT_SECRET = "kc-test-client-secret"
GROUP = "data-editors"
USERNAME = "sso-ann"
PASSWORD = "ann-sso-password"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--keycloak", default="http://127.0.0.1:18080", help="Keycloak's address")
    parser.add_argument("--admin-password", default="keycloak-admin")
    parser.add_argument("--redirect", required=True, help="the gateway's .../api/v1/auth/sso/callback address")
    parser.add_argument("--web", required=True, help="the web app's address")
    args = parser.parse_args()
    keycloak = args.keycloak.rstrip("/")

    token = httpx.post(
        f"{keycloak}/realms/master/protocol/openid-connect/token",
        data={"grant_type": "password", "client_id": "admin-cli", "username": "admin", "password": args.admin_password},
    ).raise_for_status().json()["access_token"]
    admin = httpx.Client(base_url=f"{keycloak}/admin/realms", headers={"Authorization": f"Bearer {token}"})

    def made(response: httpx.Response, what: str) -> None:
        if response.status_code not in (201, 204, 409):  # 409: already there from an earlier run
            sys.exit(f"Could not create the {what}: {response.status_code} {response.text}")

    made(admin.post("", json={"realm": REALM, "enabled": True}), "realm")
    made(
        admin.post(f"/{REALM}/clients", json={
            "clientId": CLIENT_ID, "enabled": True, "protocol": "openid-connect", "publicClient": False,
            "secret": CLIENT_SECRET, "standardFlowEnabled": True, "directAccessGrantsEnabled": False,
            "redirectUris": [args.redirect], "webOrigins": [args.web.rstrip("/")],
            "attributes": {"pkce.code.challenge.method": "S256"},
            "protocolMappers": [{
                "name": "groups", "protocol": "openid-connect", "protocolMapper": "oidc-group-membership-mapper",
                "config": {"claim.name": "groups", "full.path": "false", "id.token.claim": "true",
                           "access.token.claim": "true", "userinfo.token.claim": "true"},
            }],
        }),
        "client",
    )
    made(admin.post(f"/{REALM}/groups", json={"name": GROUP}), "group")
    group_id = next(group["id"] for group in admin.get(f"/{REALM}/groups").json() if group["name"] == GROUP)
    made(
        admin.post(f"/{REALM}/users", json={
            "username": USERNAME, "email": "ann@example.com", "firstName": "Ann", "lastName": "Example",
            "enabled": True, "emailVerified": True,
            "credentials": [{"type": "password", "value": PASSWORD, "temporary": False}],
        }),
        "person",
    )
    user_id = admin.get(f"/{REALM}/users", params={"username": USERNAME}).json()[0]["id"]
    made(admin.put(f"/{REALM}/users/{user_id}/groups/{group_id}"), "group membership")

    print(f"Signed-in person: {USERNAME} / {PASSWORD} (group {GROUP})\n")
    print("Gateway settings:")
    print(f"OIDC_ISSUER={keycloak}/realms/{REALM}")
    print(f"OIDC_CLIENT_ID={CLIENT_ID}")
    print(f"OIDC_CLIENT_SECRET={CLIENT_SECRET}")
    print(f"OIDC_REDIRECT_URI={args.redirect}")
    print(f"OIDC_GROUP_ROLE_MAP={{\"{GROUP}\": \"admin\"}}")
    print(f"WEB_BASE_URL={args.web.rstrip('/')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
