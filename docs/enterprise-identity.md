# Enterprise identity

How Pipewright authenticates people beyond its own username/password: a second
factor, single sign-on over either protocol, per-tenant session length, and
directory-driven offboarding. Written to be honest about what is verified and
what is not.

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

The preferred protocol. SAML is below, for providers that offer nothing else.

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

## SAML 2.0

For the identity providers that speak SAML and nothing else. Where a provider
offers both, prefer OIDC above — it is the better protocol and the simpler
integration. SAML is here so "we only do SAML" is not a reason this platform
cannot be adopted.

| Variable | Meaning |
| --- | --- |
| `SAML_IDP_ENTITY_ID` | The provider's entity ID, matched against the assertion's `Issuer`. |
| `SAML_IDP_SSO_URL` | Where the browser is sent to sign in (HTTP-Redirect binding). |
| `SAML_IDP_X509_CERT` | The provider's signing certificate. A PEM block, or the bare base64 that federation metadata carries — both are accepted. |
| `SAML_SP_ENTITY_ID` | What this deployment calls itself, matched against `AudienceRestriction`. |
| `SAML_SP_ACS_URL` | Must point at `…/api/v1/auth/saml/acs`. Checked against `Destination` and `Recipient`. |
| `SAML_GROUP_ROLE_MAP` | JSON, e.g. `{"data-admins": "admin"}`. |

`OIDC_DEFAULT_ROLE` and `OIDC_ALLOW_JIT` govern provisioning for **both**
protocols: the role a new person gets should not depend on which one they
arrived by.

Three routes. `GET /auth/saml/metadata` returns the service-provider metadata
an administrator uploads to the provider. `GET /auth/saml/start` builds a
deflated `AuthnRequest`, stores its id, and redirects.
`POST /auth/saml/acs` is where the provider posts the assertion back.

### What is checked before anybody is signed in

Each of these is a way into someone's account if it were skipped, so each is a
hard failure rather than a warning:

- the assertion's **XML signature**, against the configured certificate — never
  against a certificate carried inside the response it is verifying;
- the response **status**, the **issuer**, and the **audience**;
- **`InResponseTo`** on both the response and the subject confirmation, against
  a request this deployment actually made and has not already spent;
- the **recipient**, against this deployment's ACS URL;
- three separate **expiry windows** (the conditions' `NotBefore` and
  `NotOnOrAfter`, and the subject confirmation's), with sixty seconds of clock
  skew.

**Every claim comes from the subtree whose signature verified.** That is the
defence against XML signature wrapping — appending an unsigned assertion beside
a signed one and waiting for the reader to pick the wrong one. The verifier
hands back the signed subtree and the reader never re-reads the document it
parsed, so there is no second copy to confuse. A response carrying more than
one assertion is refused outright rather than disambiguated.

Replay is prevented by the same row that binds the request: it is deleted the
moment it is spent, whether the sign-in succeeded or failed.

### Scope, stated plainly

- **Service-provider-initiated only.** An unsolicited assertion has no request
  of ours to bind to, and accepting one means accepting anything the provider's
  signing key has ever produced. Provider-initiated sign-in is refused by name.
- **Requests are not signed by us.** Okta and Entra do not require it, and this
  deployment holds no service-provider key. The metadata says
  `AuthnRequestsSigned="false"` so an administrator cannot configure the
  provider to expect something this SP cannot do.
- **Encrypted assertions are refused by name**, not ignored. Turn off assertion
  encryption for the application, or use OIDC.

### The signature library

Signatures are verified by [`signxml`](https://pypi.org/project/signxml/), pure
Python over `lxml` and `cryptography`, installed as an ordinary dependency of
`service-enterprise`. The plan for this phase named `python-xmlsec`; that needs
the `libxmlsec1` system library, which would make a native package a
prerequisite of `npm run setup` and of CI for everyone, including the majority
who never turn SAML on. What matters is that the signature is verified by a real
implementation rather than by hand — both satisfy that, and only one installs
from a wheel. Hand-rolling XMLDSig was never on the table: it is the single most
reliable way to ship an authentication bypass.

If the package is somehow absent, `GET /auth/sso/status` reports SAML as
implemented-but-unavailable and names the package to install. It never degrades
into skipping the signature check.

**Verification status.** The signature path is genuinely exercised: the tests
mint an RSA key, sign assertions with it, and verify them through the same code
the product runs — including tamper, wrong-key, unsigned, wrapped, expired,
wrong-audience and wrong-recipient rejections. The **network legs have not been
run against a live Okta or Entra tenant** in this environment. The assertions
under test are built to the shapes those two providers emit, from their
documented claim names, rather than captured from them.

## Session length, per organisation

A deployment sets one session lifetime (`AUTH_ACCESS_TOKEN_EXP_MINUTES`). An
organisation may set its own, between 5 minutes and 30 days, under
**Organisations → Settings**. Empty means "follow the deployment default", which
is a different thing from "set to the same number as the default" — a tenant
that has never chosen a policy does not acquire one.

Every token this platform mints goes through one place, so the policy applies
whichever way somebody signs in: password, second factor, one-time code, OIDC
or SAML. `service_auth` does not import `service_enterprise` to find the
policy — tenancy registers a resolver, the same way it makes access checks
organisation-aware — so a single-tenant install behaves exactly as it did
before this existed, and a resolver that fails falls back to the deployment
default rather than blocking sign-in.

It applies **from the next sign-in**. A token already issued carries its own
expiry and there is no session table to shorten; ending current sessions now is
what sign-out-everywhere does.

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
