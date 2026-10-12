# Security policy

Pipewright holds credentials for other people's databases and SaaS accounts,
runs SQL and Python that users write, and — through write-back — changes rows
in tables it does not own. A way around any of the controls that keep those
three things contained is treated as a security defect, not as a bug.

The controls themselves are described in [docs/security.md](docs/security.md)
(accounts, credentials, audit) and
[docs/enterprise-identity.md](docs/enterprise-identity.md) (MFA, SSO, SCIM-lite).

## Supported versions

There are no tagged releases yet. Only `main` is supported, and fixes land
there.

## Reporting a vulnerability

**Do not open a public issue.** Report privately through GitHub:
[Security → Report a vulnerability](https://github.com/harshkvpatil98/pipewright-data-platform/security/advisories/new).
The report is visible only to the maintainer until an advisory is published.

Include:

- what you found, and which control it gets around (one of the areas below, a
  rule in [CONTRIBUTING.md](CONTRIBUTING.md#invariants), or a claim in
  [docs/security.md](docs/security.md));
- the smallest reproduction you have: a request sequence (`curl` is ideal), a
  pipeline or notebook cell, or a failing test;
- the commit you tested (`git rev-parse HEAD`) and how you ran it (local
  `make dev`, `docker compose`, or the Helm chart).

**Redact before you send.** No real connection strings, passwords, API tokens
(`pw_…`), JWT secrets, `APP_SECRET_ENCRYPTION_KEY` values, OIDC client secrets,
webhook URLs or `.env` contents. If a finding depends on one, describe its shape
(`postgresql+psycopg://<user>:<password>@<host>/<db>`) instead.

The maintainer aims to acknowledge a report within seven days, and will tell
you whether it is accepted, what the fix is, and when it lands. Credit is given
in the advisory unless you ask otherwise.

## In scope

| Area | Examples |
|---|---|
| **Access control and tenancy** | Any request that succeeds without the project role the central check in `service_access/permissions.py` should demand; a write path that is not refused for a `viewer`; reaching a project, dataset or audit entry in another organisation; a `read` API token that can perform a mutating request; a token that still works after sign-out-everywhere, a password change or revocation |
| **Authentication** | Bypassing the TOTP step or reusing a recovery code; forging or replaying the MFA ticket; OIDC state, PKCE or ID-token verification that can be skipped; a one-time activation or reset code that can be reused or guessed |
| **Connector credentials** | A saved credential or secret reference returned by any API response, export, audit entry or error message; credentials stored unencrypted; a connector request that sends the credential to a host other than the configured one (for example through a paginated `next_url`) |
| **Write-back to source systems** | A change set that commits without its dry run, writes rows other than the ones it names, bypasses the stale-row (concurrency) check, or runs in a governed project without approval |
| **SQL injection** | User input — a column name, filter value, formula, transformation step or pushed-down predicate — that reaches a source database as SQL it did not intend; a statement that gets past the workbench's read-only policy (data-modifying CTEs, `EXPLAIN ANALYZE` of a write, multiple statements) |
| **Sandboxed cell execution** | A notebook Python cell that imports a refused module, reads or writes a file, opens a socket, starts a process, or sees the gateway's state; a cell that runs where the capability probe should have disabled cells |
| **Public endpoints** | Reading data through `/public/dashboards/{token}` beyond the shared results, or after the link is revoked; injecting into a stream through `/api/v1/hooks/{token}` without the token |
| **Secrets in logs** | A password, token, connection string or decrypted secret written to an application log, the slow-query log, the audit trail, a run's warnings, a report delivery record, or a process's argv |
| **CI and supply chain** | A workflow that runs untrusted code with write permissions or a credential; a published image that contains a secret |

## Out of scope

- **Gaps the documentation already states.** [docs/HANDOFF.md §7](docs/HANDOFF.md#7-known-gaps--stated-not-hidden)
  lists them: SAML is absent by design, the OIDC network legs have not been run
  against a live identity provider, Python cells are disabled on macOS, and 161
  of the 211 connectors are tier 4 ("Unverified", written from vendor
  documentation). A report that restates one of these is not a vulnerability;
  a concrete exploit that depends on one is.
- A tier-4 connector that does not work against the vendor's real API. That is
  a bug — open a public issue.
- Attacks that need an already-compromised host, database superuser access, or
  a platform `admin` account acting within its documented powers.
- Missing hardening on the development stack (`docker-compose.yml`, the
  default `platform/platform` credentials in `.env.example`), which is not
  meant to be exposed.
- Vulnerabilities in third-party dependencies, unless Pipewright's use of them
  makes the problem worse. The [dependency audit](.github/workflows/dependency-audit.yml)
  runs `pip-audit` and `npm audit` weekly; report upstream issues to their
  maintainers.

## Testing

There is no shared hosted instance to test against. Run your own copy — the
[README](README.md#quick-start) quick start, or the Helm chart in
[deploy/helm/pipewright](deploy/helm/pipewright/README.md) — and never test
against a deployment or a connected database you do not own.

Good-faith research that follows this policy, stays within your own
installation and does not touch anyone else's data will not be pursued by the
maintainer.
