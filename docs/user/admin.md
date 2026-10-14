# Admin guide

For the people who run Pipewright for others: accounts, organisations, sign-in rules, the background work, and keeping it all healthy. Everything here needs the platform administrator role.

## Accounts

**Admin → Accounts** lists everyone who can sign in.

- **Invite** someone by name, with an optional email address and a starting role. Pipewright makes a one-time code; send it to them and they choose their own password with it. The code works once and expires after 30 minutes.
- **Reset a password** the same way: a new one-time code, which signs the person out everywhere once used.
- **Turn an account off** to stop someone signing in without deleting what they made. The last active administrator cannot be turned off, so nobody can lock the platform out of its own administration.

An account's platform role is either **Platform administrator** (can manage accounts, organisations and the whole platform) or **Member**. What a member can do inside a project is set in that project, under **Overview → People**, with one of four roles:

| Role | Can |
| --- | --- |
| Viewer | Look at data, charts and runs |
| Operator | Also run imports, recipes, workflows and deliveries |
| Editor | Also change recipes, checks, workflows and destinations |
| Admin | Also manage the project's people and settings |

## Organisations

Organisations keep separate groups of people and projects apart: someone in one organisation never sees another's projects. A single team usually needs none.

### Network access

An organisation can be limited to its own networks. Under **Admin → Organisations**, open one and list the addresses or ranges people may connect from, such as `10.0.0.0/8` or `203.0.113.7`. From anywhere else, signing in, every request on an existing session and every API token are refused, with the reason.

The page shows the address you are connecting from. A list that leaves out your own address is refused, because saving it would sign you out for good. Clear the list to allow any network again.

If Pipewright sits behind a proxy or load balancer, set `TRUSTED_PROXY_HOPS` to the number of proxies in front of it, so it reads each person's real address rather than the proxy's.

## Connectors

**Admin → Connectors** lists every kind of source Pipewright can connect to, and how each is tested.

- **Tested** connectors run in Pipewright's own tests every time it changes: databases against a real server, apps and APIs against a test server that answers the way the vendor documents. **Tested live** means against a real account with the vendor.
- **Available on request** connectors are written from the vendor's documentation and have not been run in those tests yet. They can be used now. Each is marked **Not yet tested** wherever it appears, including on the imports it makes, so look over the rows its first import brings in.

To have one tested, ask through your support contact. A test is written for it and runs on every change from then on; once it passes, the connector shows as Tested.

Some connectors need a package the server does not have. The page lists each missing package and how many connectors it would unlock, for whoever runs the server.

## Sign-in rules

- **Sessions** end after a period of no use (`AUTH_ACCESS_TOKEN_EXP_MINUTES`, 60 by default) and always after a fixed length (`AUTH_SESSION_MAX_HOURS`, 12 by default), however busy. A session in use renews itself until that limit. Each person sees both figures under **Your settings**.
- **Two-factor authentication** is turned on by each person under **Your settings**, with any authenticator app. Recovery codes are shown once.
- **Single sign-on** over OpenID Connect is set with the `OIDC_*` settings below. The sign-in page shows **Continue with SSO** only when it is configured. SAML is not offered.

## Alerts

Each project chooses where its failures and reports go, under **Overview → Alerts**: an email address or a Slack channel, and which events each hears about. Incidents and failed workflows can be sent there, as can a weekly summary of the project's runs, checks and incidents. Email needs the platform's mail settings (`EXTERNAL_NOTIFICATION_SMTP_*`).

Each person also chooses, in the bell's settings, whether they want each message as it happens, a daily or weekly summary, or nothing.

## System status

**Admin → System status** is the first place to look when runs or schedules seem stuck. It shows:

- whether the **background worker** (runs workflows and long jobs) and the **schedule ticker** (starts scheduled runs) are running, and when each last checked in;
- how much work is waiting;
- the platform's **security settings**: whether stored files are encrypted and where they are kept, the session limits, how many organisations have a network list, and whether single sign-on is set up;
- the **limits** this server enforces: the largest upload and when the background worker takes over, preview and import rows, rows a delivery writes while you wait, copy and SQL rows, workflow runs at once, task tries, notebook limits, sign-in attempts and shared links.

A worker that stops opens an incident by itself. Work it was doing is marked failed, with that reason, when its time runs out; a workflow run can then be picked up from where it failed.

## Audit

**Admin → Audit (all projects)** is every change in every project, as sentences, with filters and an export for an auditor. Refused attempts are recorded too. Each project also has its own audit log under Trust. Set `AUDIT_RETENTION_DAYS` to delete entries older than that many days; it keeps everything by default.

## Backups

`scripts/backup.sh` copies the database and the stored files. Run it with `--verify` to also restore the copy into a scratch database and count the rows: a backup nobody has restored is a hope, not a backup. Run it on a schedule.

## Settings reference

Set these in the gateway's environment. Changes take effect when the gateway restarts.

| Setting | What it does |
| --- | --- |
| `SUPPORT_CONTACT` | An email address or web address shown under **Help → Contact support**. Unset, the menu points to [Getting help](index.md#getting-help). |
| `STORAGE_ENCRYPTION_KEY` | Encrypts stored files (uploads, datasets, versions) with AES-256. Make one with `openssl rand -base64 32`, keep it with your other secrets, and run `platform-encrypt-storage` once to encrypt files saved before it was set. Losing the key loses the files. |
| `APP_SECRET_ENCRYPTION_KEY` | Encrypts saved passwords and keys for connections, destinations and alert channels. |
| `TRUSTED_PROXY_HOPS` | How many proxies sit in front of the gateway (0 by default). |
| `AUTH_ACCESS_TOKEN_EXP_MINUTES` | Minutes without use before a session ends. |
| `AUTH_SESSION_MAX_HOURS` | The longest any session lasts. |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` | Single sign-on. The redirect address ends in `/api/v1/auth/sso/callback`. |
| `OIDC_GROUP_ROLE_MAP`, `OIDC_DEFAULT_ROLE`, `OIDC_ALLOW_JIT` | Which role a single sign-on group gets, the role for everyone else, and whether a first sign-in makes an account. |
| `EXTERNAL_NOTIFICATION_SMTP_HOST`, `_PORT`, `_FROM` | The mail server alerts are sent through. |
| `AUDIT_RETENTION_DAYS` | Delete audit entries older than this. 0 keeps them all. |
| `SERVER_FILES_ROOT` | The one folder on the server that server-folder sources and destinations may use. |
| `OUTBOUND_BLOCK_PRIVATE_NETWORKS` | Refuse connectors that reach addresses inside your network. |
| `OUTBOUND_ALLOW_LOOPBACK` | Allow connectors to reach the server itself. Off by default; for testing only. |
| `MAX_UPLOAD_SIZE_BYTES` | The largest file people can upload (100MB by default). Files over 25MB are read by the background worker, which needs about twenty times the file's size in memory. |
| `STORAGE_BACKEND` | Where stored files live: `local` (the server's disk, the default) or `s3` (a bucket, so several servers share them), with `STORAGE_S3_BUCKET`, `_PREFIX`, `_ENDPOINT_URL`, `_REGION`, `_ACCESS_KEY_ID` and `_SECRET_ACCESS_KEY`. |
| `WORKFLOW_MAX_RUNS_PER_PROJECT` | How many workflow runs one project may have going at once (3); more wait their turn. |
| `WORKFLOW_LEASE_SECONDS` | How long a run whose background worker stopped waits before it is marked failed and can be picked up (900, 15 minutes). |
| `RATE_LIMITS_ENABLED` | Set to `false` only for a load test; sign-in and public addresses are limited otherwise. |
| `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT` | Send traces of each request and its database statements to an OpenTelemetry collector. Off by default. |

The deployment guide in the repository covers installing, upgrading and sizing.
