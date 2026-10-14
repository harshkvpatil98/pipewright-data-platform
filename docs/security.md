# Security overview

How Pipewright handles accounts, sessions, networks, credentials, stored data
and the audit trail, written for a security review. It states what this
version does, with the setting or file behind each claim; where something is
not done or not proven, it says so.

The same answers in plain words, laid out like a security questionnaire, are
in the product under **Help → Security** ([docs/user/security.md](user/security.md)).

## Identity

- **Passwords** are stored as `scrypt` hashes (N=2¹⁴, r=8, p=1) with a
  16-byte random salt each. Plaintext passwords are never stored or logged.
- **One-time codes** (invitation and reset) are single use, expire in 30
  minutes, are bound to their purpose and are stored only as SHA-256 hashes.
  A new code of the same purpose cancels the previous one.
- **Two-factor authentication** (TOTP, RFC 6238) is opt-in per person. Once
  on, the password step returns a short-lived ticket with its own audience,
  and a session is issued only for a valid code or a one-time recovery code
  (stored hashed).
- **API tokens** are named, scoped (`read`, `write`, `admin`), shown once,
  stored as SHA-256 hashes and revocable. A `read` token cannot make any
  change, whatever its owner's role.
- **Single sign-on over OpenID Connect**: PKCE (S256), a one-time state, and
  an ID token verified against the provider's published keys for signature,
  issuer, audience, expiry and the nonce of the sign-in that started it. Only
  RSA signatures are accepted; a token naming `none` or an HMAC algorithm is
  refused. Group-to-role mapping on just-in-time provisioning; an existing
  person is never silently demoted. A batch job deactivates directory-managed
  accounts that have left the directory. Configuration is in
  [enterprise-identity.md](enterprise-identity.md).
- **SAML is not offered.** It needs XML signature verification, and a SAML
  implementation that skips it is an authentication bypass.

**Not proven yet: OIDC against a live provider.** The flow is tested with the
provider imitated, including real RS256 signatures against a matching key set.
It has not been run against a live Okta or Entra ID account for this version,
because this environment has none. `scripts/check-oidc.py` does that against
whatever provider the deployment configures: it checks the settings, the
discovery document, the signing keys and the client credentials, and with
`--sign-in` completes a real sign-in without writing to the database. The
script itself is tested against a provider served locally
(`apps/api-gateway/tests/test_check_oidc.py`). Run it before relying on SSO.

## Sessions

- Sessions are signed JWTs (HS256) carrying the person's `token_version`.
  A password change, an administrator's reset or **Sign out everywhere**
  raises that version, which ends every session issued before it.
- A session ends after `AUTH_ACCESS_TOKEN_EXP_MINUTES` without use (60 by
  default) and always after `AUTH_SESSION_MAX_HOURS` (12 by default), however
  active. A session in use renews itself up to that limit.
- Both limits are shown to each person under **Your settings** and to
  administrators under **System status** (`GET /api/v1/auth/session-policy`).

## Authorisation

- Every project request is authorised in one place: a gateway dependency
  reads the method and path and compares the role the route needs with the
  caller's role on the project in the path. Routes do not repeat the check,
  so a new route cannot forget it; an unrecognised write fails closed to the
  strictest sensible role.
- Platform administration needs the platform `admin` role. The last active
  administrator cannot be deactivated, demoted or deleted.
- Organisations are isolated at the same point: a person reaches only
  projects in their own organisation.
- **Row and column policies** apply on every read path that hands rows,
  values or column lists to a person: the dataset page (detail, preview,
  profile, versions, audit summary), SQL over a version, charts, pivots and
  dashboards (a public link reads as a viewer), the Studio preview and the
  datasets it joins, the assistant, comparisons and statistical tests,
  downloads, and every delivery and BI send.
  `apps/api-gateway/tests/test_policies_everywhere.py` calls each path as a
  restricted reader and fails if a hidden value, row or column name appears;
  a new read path belongs in that file. Column names still appear in lineage
  and recipe definitions, which describe the data's shape, not its values.

## Network

- **Allow-lists per organisation.** An organisation can list the addresses
  and ranges (IPv4 and IPv6) its people may connect from. From anywhere else,
  password sign-in, single sign-on, session renewal, every request on an
  existing session and every API token are refused with the reason. Saving a
  list that leaves out the saver's own address is refused.
  `apps/api-gateway/tests/test_network_allow_list.py` runs this through the
  HTTP stack.
- **Client addresses** are read from the connection unless
  `TRUSTED_PROXY_HOPS` says how many proxies sit in front, in which case that
  many entries are taken from the right of `X-Forwarded-For`. A forwarded
  header from an untrusted client is ignored.
- **Transport encryption** is the deployment's: the supplied Caddy setup and
  Helm ingress terminate TLS. The gateway and web app do not handle
  certificates.
- **Browser headers.** Every web page is sent with `X-Frame-Options:
  SAMEORIGIN`, `X-Content-Type-Options: nosniff`, `Referrer-Policy:
  strict-origin-when-cross-origin` and a `Permissions-Policy` that turns off
  camera, microphone and location; every API answer with `nosniff`,
  `X-Frame-Options: DENY` and `Referrer-Policy: no-referrer`. On HTTPS the
  session cookie is set `Secure`. A content security policy is left to the
  proxy, which knows the deployment's own addresses.
- **Rate limits.** Password sign-in is limited per account and address (10
  in 5 minutes per account, 60 a minute per address), as are one-time code
  redemption, public dashboard links and inbound webhooks. Counts are kept in
  the database (`rate_limit_windows`, migration 0052) so every gateway shares
  them; a refusal is HTTP 429 with `Retry-After`. `shared_python/rate_limit.py`;
  `apps/api-gateway/tests/test_rate_limits.py` runs them through the HTTP
  stack.
- **Outbound requests.** Connectors that fetch web addresses refuse the cloud
  metadata service and, unless `OUTBOUND_ALLOW_LOOPBACK` is set, the server
  itself; `OUTBOUND_BLOCK_PRIVATE_NETWORKS` also refuses private ranges.
  Server-folder sources and destinations are confined to `SERVER_FILES_ROOT`.

## Data protection

- **Stored files.** With `STORAGE_ENCRYPTION_KEY` set (32 bytes, base64),
  every file written to storage (uploads, datasets, versions) is encrypted
  with AES-256-GCM, a fresh 12-byte nonce per file and a header that marks it.
  Files without the header still read, so a key can be added to a running
  deployment; `platform-encrypt-storage` encrypts the files saved before it.
  System status shows whether encryption is on. Losing the key loses the
  files; keep it with the other secrets. With `STORAGE_BACKEND=s3` the files
  live in a bucket, encrypted before they are sent when a key is set
  (`test_two_gateways.py` checks the bucket holds only encrypted bytes).
- **Credentials.** Passwords and keys for connections, destinations, BI tools
  and alert channels are encrypted with a Fernet key
  (`APP_SECRET_ENCRYPTION_KEY`), or held in HashiCorp Vault, AWS Secrets
  Manager or Azure Key Vault with only a reference stored.
- **The database** (PostgreSQL) is not encrypted by Pipewright. Use the
  database's or the disk's encryption.
- **Retention and erasure.** Retention settings delete old runs, history and
  versions. Erasure corrects or removes one person's data wherever it appears
  and reports anything it could not do.
- **No AI model** sees the data: the assistant's findings come from rules.
- **Backups**: `scripts/backup.sh` copies the database and stored files;
  `--verify` restores the copy into a scratch database and counts rows.

## Audit

- Every mutating request is recorded, including refused ones: who, what,
  when, the outcome and the request's correlation id (`X-Request-ID`, also in
  its log lines and, with `OTEL_ENABLED`, its trace). Request bodies are
  never recorded. (Until A7 the correlation id was read from a header no
  request carried, so entries before then have none.)
- Entries read as sentences ("Ann deleted the dashboard Weekly sales"),
  naming what was touched while it still exists. Each project has its own
  log; administrators see every project in one place and can export it.
- `AUDIT_RETENTION_DAYS` deletes entries older than that many days; 0 (the
  default) keeps everything.

## Not done yet

- OIDC against a live provider (above).
- A content security policy (left to the proxy, above).

## Reporting a vulnerability

Report it privately through GitHub's advisory form, as described in the
repository's [security policy](../SECURITY.md). Please do not open a public
issue for an unpatched vulnerability.

---

*This document tracks the implemented product. When something listed under
"Not done yet" ships, move it up and note the change in `docs/HANDOFF.md`.*
