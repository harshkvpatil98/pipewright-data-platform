# Enterprise identity

How Pipewright authenticates people beyond its own username/password: a second
factor, single sign-on, and directory-driven offboarding. Written to be honest
about what is verified and what is not.

## Two-factor authentication (TOTP)

On by opt-in, per user, under **Settings → Two-factor authentication**.

- Enrolment shows a QR (and the secret to type by hand) and takes effect only
  after a live 6-digit code confirms the authenticator — a mistyped setup never
  locks the owner out.
- Login becomes two steps once a factor is on: the password step returns a
  short-lived, distinct-audience ticket instead of a session, and a second step
  exchanges the ticket plus a TOTP **or** a one-time recovery code for the
  session.
- Recovery codes are shown once and stored hashed. An admin can clear a
  locked-out account at `POST /auth/users/{id}/mfa/reset`.

TOTP is implemented directly against RFC 6238 and tested against the RFC's own
vectors — no third-party TOTP dependency.

## Single sign-on (OIDC)

Configured per deployment by environment variables; unset means the platform's
own login is the only way in. The login screen shows **Continue with SSO** only
when a provider is configured (`GET /auth/v1/auth/sso/status` reports this).

| Variable | Meaning |
| --- | --- |
| `OIDC_ISSUER` | The provider's issuer URL (discovery is fetched from it). |
| `OIDC_CLIENT_ID` / `OIDC_CLIENT_SECRET` | The registered client. |
| `OIDC_REDIRECT_URI` | Must point at `…/api/v1/auth/sso/callback`. |
| `OIDC_SCOPES` | Space-separated; default `openid email profile`. |
| `OIDC_GROUP_ROLE_MAP` | JSON, e.g. `{"data-admins": "admin"}`. |
| `OIDC_DEFAULT_ROLE` | Role for a provisioned user no group maps. Default `viewer`. |
| `OIDC_ALLOW_JIT` | When false, an unknown identity is refused, not created. |
| `WEB_BASE_URL` | Where the callback sends the browser after sign-in. |

Flow: `/auth/sso/start` discovers the provider, builds a PKCE request, stores a
one-time state, and redirects; `/auth/sso/callback` verifies the state,
exchanges the code, verifies the ID token against the provider's JWKS, maps the
claims, provisions the user just-in-time, and sets the session cookie.
Group→role mapping is applied on provisioning; an existing person is never
silently demoted to the default role.

**Session cookie note.** The callback sets the `idp_access_token` cookie on the
gateway's host. The gateway and web app must share a host (or a parent cookie
domain) for the session to carry across — the standard reverse-proxy layout
where the web serves `/` and proxies `/api` to the gateway satisfies this.

**Verification status.** The pure logic (PKCE, state, ID-token verification,
claim mapping) and the provisioning are unit-tested, including the RS256
signature path against a matching JWKS. The **network legs have not been run
against a live Okta/Entra/Auth0 tenant** in this environment — point it at a
real provider to confirm the wire protocol before relying on it.

## SAML

Not supported, deliberately. SAML needs XML signature verification (the
`xmlsec` native library); a SAML implementation that skips signature checking is
an authentication bypass, not a feature. `GET /auth/sso/status` returns this
plainly. Every provider that speaks SAML also speaks OIDC — use that.

## SCIM-lite: deactivate on absence

Full SCIM is a provisioning API the identity provider pushes to. Pipewright
ships the offboarding half as a batch **job**: give it the set of people still
in the directory and it deactivates the directory-managed accounts that are no
longer among them.

```
directory-export | scim-sync --stdin        # deactivate absentees
scim-sync --file present-users.txt --dry-run # report only, change nothing
```

Two invariants keep it safe to run from cron:

- **Only `auth_source = "sso"` accounts are ever touched.** A local admin
  created here is never in the directory and is never swept for it.
- **The platform is never left without an active admin.** Deactivating the last
  active admin is skipped and reported instead.

It deactivates rather than deletes and bumps the user's token version so live
sessions end at once. An account that returns to the directory is reactivated on
its next SSO sign-in; owned projects and the audit trail survive in the interim.

*Not implemented:* the inbound SCIM 2.0 push API (create/update from the IdP).
The deactivate-on-absence pull job is the piece that matters most for security
and is the one shipped here.
