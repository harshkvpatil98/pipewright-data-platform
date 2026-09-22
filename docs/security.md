# Security overview

A short, honest summary of how Pipewright handles accounts, credentials and
data — written for a buyer's security review. It states what is implemented
today and, where something is planned rather than present, says so plainly.

## Authentication

- **Password login** with salted, key-stretched hashes (`scrypt`,
  N=2¹⁴, r=8, p=1; 16-byte random salt per password). Plaintext passwords are
  never stored or logged.
- **Session tokens** are short-lived signed JWTs (HS256), carrying a per-user
  `token_version`. Changing a password, an admin-forced reset, or an explicit
  "sign out everywhere" bumps that version, which immediately invalidates every
  token issued before it — a stateless sign-out-everywhere with no session
  table to fall out of sync.
- **One-time codes** (activation and reset) are single use, expire in 30
  minutes, are bound to their purpose, and are stored only as SHA-256 hashes.
  Issuing a new code of the same purpose invalidates the previous one.
- **API tokens** for scripts and integrations are named, scoped
  (`read` / `write` / `admin`) and revocable, shown once at creation and
  stored only as a SHA-256 hash. A `read` token cannot perform any mutating
  request even if its owner is an admin.

**Planned, not yet present:** SSO (OIDC then SAML) and MFA (TOTP). These are
scheduled and are not claimed as available. SAML will verify signatures — an
unsigned-assertion shortcut will not be shipped.

## Authorisation

- Every project-scoped request is authorised in **one place**, a gateway
  dependency that reads the HTTP method and path and compares the required role
  with the caller's role on the project named in the path. Individual routes do
  not re-implement this, so a new route cannot forget the check — an
  unrecognised write path fails closed to the strictest sensible role.
- Platform administration (creating and disabling accounts, managing tenants)
  requires the platform `admin` role. The last active admin cannot be
  deactivated, demoted or deleted, so an install cannot be locked out of its
  own administration.
- Multi-tenant isolation is enforced at the same choke point: a user only
  reaches projects in their organisation.

## Data protection

- **Secrets at rest** (connection credentials, BI and webhook secrets) are
  encrypted with a Fernet key (`APP_SECRET_ENCRYPTION_KEY`), generated per
  deployment and never committed.
- **Audit log**: every mutating request is recorded — actor, method, path,
  outcome, timestamp — including refused ones. Request bodies are never logged;
  the endpoints whose bodies or responses carry secrets (login, password
  change, code redemption, token creation) are excluded from body-free path
  logging only where a secret could otherwise be inferred.
- **Backups**: `scripts/backup.sh` performs database and artifact backups;
  `--verify` runs a real restore drill.

## Reporting a vulnerability

Email the maintainer (see the repository owner) with details and a proof of
concept. Please do not open a public issue for an unpatched vulnerability.

---

*This document tracks the implemented product. When a planned item above ships,
move it out of "planned" and note the change in `docs/HANDOFF.md`.*
