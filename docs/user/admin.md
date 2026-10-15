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

If Pipewright sits behind a proxy or load balancer, set `TRUSTED_PROXY_HOPS` to the number of proxies in front of it, so it reads each person's real address rather than the proxy's. Set it for the web too: it passes the address of each person viewing a shared or embedded dashboard on, so they are rate limited one by one.

### Embedded dashboards

A dashboard can be shown inside another site, such as a customer portal (see [embedding a dashboard](api.md#embedding-a-dashboard)). Only the sites listed in the web's `EMBED_ALLOWED_ORIGINS` may show it in a frame, separated by spaces: `https://portal.example.com https://*.partner.io`. With none listed, an embed link opens on its own but no other site can frame it. An address written wrongly is named on the dashboard's **Embed** panel.

## Plugins

A plugin adds tools to the Studio, functions to formulas, chart types to the chart builder and connectors to the catalogue, from outside Pipewright. **Admin → Plugins** lists every plugin installed on the server, what each adds and the checks it passed.

- **Installing.** Install the plugin's package where the gateway and the worker run (`pip install pipewright-plugin-acme`), or put its folder in one of the folders listed in `PLUGINS_PATH`.
- **Turning it on.** Name it in `PLUGINS_ENABLED` (`PLUGINS_ENABLED=acme,maps`) and restart the gateway and the worker. A plugin that is installed and not named is listed and never run.
- **Checked first.** Before anything of it is used, each thing a plugin adds passes the checks Pipewright's own pass: a tool its example, empty data and lineage; a function its examples, and an empty answer for an empty argument; a chart type a query it allows; a connector the conformance suite. One failure refuses the whole plugin, and the page says which check and why.
- **What it may not do.** A plugin's chart types are drawn by the web from what they declare, so no plugin code runs in anyone's browser. Its connectors say they are not yet tested, as any connector Pipewright has not run against the system it reaches does. Its functions run on the server, never in a database.
- **Trust.** A plugin is code that runs on the server with the server's permissions. Install only plugins from people you trust, as you would any package.

Writing one is in [Using the API](api.md#writing-a-plugin).

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

Each project chooses where its failures and reports go, under **Overview → Alerts**: an email address, a Slack channel or a webhook (signed JSON to your own systems, see [Using the API](api.md#webhooks)), and which events each hears about. Incidents and failed workflows can be sent there, as can a weekly summary of the project's runs, checks and incidents. Email needs the platform's mail settings (`EXTERNAL_NOTIFICATION_SMTP_*`).

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

**Reveal a token**, on the same page, turns a value a recipe replaced with **Replace with a reversible token** back into the value, for a platform admin only. Give the token and the key name the step used; each reveal is in the audit trail.

## Backups

`scripts/backup.sh` copies the database and the stored files. Run it with `--verify` to also restore the copy into a scratch database and count the rows: a backup nobody has restored is a hope, not a backup. Run it on a schedule.

## Languages

Pipewright is in English, with dates and numbers written the British way ("15 Oct 2026", "1,200"). The words of the top bar, the menus, the side navigation and every page's name, description and help come from one file, `apps/web/messages/en.json`; dates and numbers are written in one place, by the locale that file names. Another language would be a copy of that file with the same keys and a build that uses it. The rest of each page's words are still written in English in the code, so a full translation needs them moved into the file first.

## Settings reference

Set these in the gateway's environment unless they say the web. Changes take effect when it restarts.

| Setting | What it does |
| --- | --- |
| `SUPPORT_CONTACT` | An email address or web address shown under **Help → Contact support**. Unset, the menu points to [Getting help](index.md#getting-help). |
| `STORAGE_ENCRYPTION_KEY` | Encrypts stored files (uploads, datasets, versions) with AES-256. Make one with `openssl rand -base64 32`, keep it with your other secrets, and run `platform-encrypt-storage` once to encrypt files saved before it was set. Losing the key loses the files. |
| `APP_SECRET_ENCRYPTION_KEY` | Encrypts saved passwords and keys for connections, destinations and alert channels. |
| `TRUSTED_PROXY_HOPS` | How many proxies sit in front of the gateway (0 by default). Set the same for the web. |
| `WEB_BASE_URL` | Where people open Pipewright, such as `https://pipewright.example.com`, for links in emails and embedded dashboards. |
| `EMBED_ALLOWED_ORIGINS` | Set for the web: the sites that may show an embedded dashboard in a frame, separated by spaces. |
| `AUTH_ACCESS_TOKEN_EXP_MINUTES` | Minutes without use before a session ends. |
| `AUTH_SESSION_MAX_HOURS` | The longest any session lasts. |
| `OIDC_ISSUER`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REDIRECT_URI` | Single sign-on. The redirect address ends in `/api/v1/auth/sso/callback`. |
| `OIDC_GROUP_ROLE_MAP`, `OIDC_DEFAULT_ROLE`, `OIDC_ALLOW_JIT` | Which role a single sign-on group gets, the role for everyone else, and whether a first sign-in makes an account. |
| `EXTERNAL_NOTIFICATION_SMTP_HOST`, `_PORT`, `_FROM` | The mail server alerts are sent through. |
| `AUDIT_RETENTION_DAYS` | Delete audit entries older than this. 0 keeps them all. |
| `SERVER_FILES_ROOT` | The one folder on the server that server-folder sources and destinations may use. |
| `OUTBOUND_BLOCK_PRIVATE_NETWORKS` | Refuse connectors that reach addresses inside your network. |
| `OUTBOUND_ALLOW_LOOPBACK` | Allow connectors to reach the server itself. Off by default; for testing only. |
| `MAX_UPLOAD_SIZE_BYTES` | The largest file people can upload (200MB by default). Files over 25MB are read by the background worker, which needs about nine times the file's size in memory. |
| `STORAGE_BACKEND` | Where stored files live: `local` (the server's disk, the default) or `s3` (a bucket, so several servers share them), with `STORAGE_S3_BUCKET`, `_PREFIX`, `_ENDPOINT_URL`, `_REGION`, `_ACCESS_KEY_ID` and `_SECRET_ACCESS_KEY`. |
| `PROJECT_RUNS_AT_ONCE` | How many runs one project may have going at once (4): recipe runs, imports, deliveries and workflow runs together. A project's admin can set its own number under **Settings**. Queued work waits its turn; a run someone starts beyond it is refused with the reason. `WORKFLOW_MAX_RUNS_PER_PROJECT`, its name when it counted only workflow runs, is still read. |
| `RUN_MEMORY_LIMIT_MB` | The most memory one run's data may take (2048). A recipe whose data grows past it stops at the step that did it; a join that would is stopped before it is built. On Linux the background worker also limits its own address space to twice this plus 2GB, so a run that tries to take more fails by itself instead of taking the worker down; `WORKER_ADDRESS_SPACE_CAP=false` turns that off for a library that reserves far more memory than it uses. |
| `ENRICHMENT_ALLOWED_HOSTS` | The web services a recipe's **Look up each value in a web service** step may call, by host, separated by commas: `api.example.com,maps.example.org`. Unset, no recipe calls out. |
| `ENRICHMENT_SECRETS` | Keys those services need, as JSON of a name to a value: `{"maps": "…"}`. A recipe names the secret; its value never leaves the server's settings. |
| `GEOCODER_URL` | A Nominatim-style geocoding service for **Find places from addresses** and **Find addresses from places**, such as `https://nominatim.openstreetmap.org`; allow its host in `ENRICHMENT_ALLOWED_HOSTS` too. OpenStreetMap's own server is called at most once a second, as it asks. |
| `PLUGINS_ENABLED` | The plugins to load, by name, separated by commas. Unset, none load. Restart the gateway and the worker after changing it. |
| `PLUGINS_PATH` | Folders that hold folder plugins (each a folder with a `plugin.py`), separated by `:`. |
| `RECIPE_CACHE_MB`, `RECIPE_CACHE_MINUTES` | How much of what recent previews and runs made each server keeps (512MB) and for how long (30 minutes), so changing a recipe's later step does not run the earlier ones again. 0 keeps nothing. |
| `WORKFLOW_LEASE_SECONDS` | How long a run whose background worker stopped waits before it is marked failed and can be picked up (180, three minutes). A working worker renews it, however long the run. |
| `RATE_LIMITS_ENABLED` | Set to `false` only for a load test; sign-in and public addresses are limited otherwise. |
| `OTEL_ENABLED`, `OTEL_EXPORTER_OTLP_ENDPOINT` | Send traces of each request and its database statements to an OpenTelemetry collector. Off by default. |

The deployment guide in the repository covers installing, upgrading and sizing.
