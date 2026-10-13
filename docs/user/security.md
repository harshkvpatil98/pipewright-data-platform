# Security

The answers a security review asks for, each with where it is set or seen. This page describes what this version does; where something is not done, it says so.

## Identity

**How do people sign in?**
With a username and password, or with single sign-on over OpenID Connect (Okta, Entra ID, Google and others) when the deployment sets it up. SAML is not offered: every provider that speaks SAML also speaks OpenID Connect. Set up in the gateway's `OIDC_*` settings; see the [admin guide](admin.md#settings-reference).

**How are passwords stored?**
Never as written. Each is stored as an `scrypt` hash with its own random salt, and never logged.

**Is two-factor authentication available?**
Yes. Each person turns it on under **Your settings** with any authenticator app, and gets one-time recovery codes. Once on, a password alone does not sign them in.

**How are accounts added and removed?**
An administrator invites people under **Admin → Accounts**; each sets their own password with a one-time code that expires in 30 minutes. Turning an account off stops it signing in at once. With single sign-on, a first sign-in can make the account, with a role chosen by the person's group, and a job, given the directory's list of people, turns off the accounts that have left it.

**What can each person do?**
Each project gives every member one role: viewer, operator, editor or admin ([what each can do](admin.md#accounts)). Every request is checked against the role on the project it touches, in one place, so a new page cannot forget the check. Platform administration needs the platform administrator role.

**Has single sign-on been tested against a real provider?**
Not yet. The sign-in logic, the token checks and the account creation are tested automatically, with the provider's side imitated. Signing in through a live Okta or Entra ID account has not been tried for this version. `scripts/check-oidc.py` checks a configured provider end to end and should be run before relying on it.

## Sessions

**How long does a session last?**
A session ends after 60 minutes without use and always after 12 hours, whatever happens. While in use it renews itself. Both limits are set by the deployment (`AUTH_ACCESS_TOKEN_EXP_MINUTES`, `AUTH_SESSION_MAX_HOURS`); each person sees them under **Your settings**, and administrators under **System status**.

**Can a session be ended?**
Changing a password, a password reset by an administrator, or **Sign out everywhere** ends every session the person has, at once.

**How do scripts sign in?**
With an API token made under **Your settings**. Each token has a name and a scope (read, write or admin), is shown once, is stored only as a hash, and can be withdrawn at any time. A read token cannot change anything, even if its owner can. See [Using the API](api.md).

## Network

**Can access be limited to our network?**
Yes. Each organisation can list the addresses and ranges people may connect from, under **Admin → Organisations**. From anywhere else, signing in, existing sessions and API tokens are all refused, with the reason. See [network access](admin.md#network-access).

**Is traffic encrypted?**
The supplied deployments (the Caddy setup and the Helm chart) serve Pipewright over HTTPS. Pipewright itself does not handle certificates; whatever sits in front of it must.

**Can Pipewright be made to reach places it should not?**
Connectors refuse the cloud metadata service and the server itself, and can be told to refuse every address inside your network (`OUTBOUND_BLOCK_PRIVATE_NETWORKS`). Server-folder sources and destinations stay inside one folder the deployment chooses (`SERVER_FILES_ROOT`).

**Does the web app set browser security headers?**
Yes: pages cannot be framed by other sites, browsers may not guess content types, and addresses are not leaked to other sites when a link is followed.

## Encryption

**Are stored files encrypted?**
When the deployment sets `STORAGE_ENCRYPTION_KEY`, every file Pipewright stores (uploads, datasets and their versions) is encrypted with AES-256-GCM before it is written. Files saved before the key was set are encrypted by running `platform-encrypt-storage` once. **System status** shows whether it is on. Without a key, files rely on the disk's own encryption.

**Are saved passwords and keys encrypted?**
Yes, always. Passwords and keys for connections, destinations and alert channels are encrypted with the deployment's own key (`APP_SECRET_ENCRYPTION_KEY`). They can instead live in HashiCorp Vault, AWS Secrets Manager or Azure Key Vault, with only a reference stored.

**Is the database encrypted?**
Pipewright stores its records (projects, recipes, run history, audit) in PostgreSQL and does not encrypt the database itself. Use the database's or the disk's encryption, as most managed databases do by default.

## Audit

**What is recorded?**
Every change anyone makes, in every project, with who, what, when and whether it worked, including attempts that were refused. Entries read as sentences: "Ann deleted the dashboard Weekly sales". Looking at data is not recorded; changing anything is. The content of requests is never recorded, so no password or data reaches the log.

**Where is it seen, and for how long is it kept?**
Each project's log is under **Trust → Audit log**; administrators see every project under **Admin → Audit (all projects)** and can export it. Entries are kept until `AUDIT_RETENTION_DAYS` says otherwise.

## Data handling

**Can people be kept from some rows or columns?**
Yes. Policies hide rows or columns from a role, or mask a column. They apply everywhere rows reach a person: the dataset page, charts, dashboards and their public links, the Studio, SQL, the assistant, comparisons, downloads and deliveries. See [policies](trust.md#policies).

**Can one person's data be found and removed?**
Yes. Erasure, under **Trust → Policies**, corrects or removes one person's data everywhere it appears and reports anything it could not do. Retention settings delete old runs, history and versions.

**Is data sent to an AI model?**
No. The assistant's findings come from rules applied to the data, and each says what it is based on.

**Is data backed up?**
`scripts/backup.sh` copies the database and the stored files, and with `--verify` restores the copy to prove it works. Running it on a schedule is the deployment's job.

## Reporting a problem

Report a security problem privately, as the repository's security policy describes, not in a public issue.
