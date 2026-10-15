# Deployment guide

How to run Pipewright on your own servers: on one host with Docker Compose,
or on Kubernetes with the Helm chart. Upgrading, backups, scaling and sizing
are in [operations.md](operations.md); what it is built for, and the sizes it
is tested at, are in [positioning.md](positioning.md).

## What runs

| Part | What it does |
| --- | --- |
| Web | The pages people use (Next.js, port 3000) |
| Gateway | The API (FastAPI, port 8000), under `/api` |
| Worker | Workflows and long work: uploads over 25MB, large deliveries, database copies |
| Ticker | Starts schedules when they are due; one only, unless each has its own `SCHEDULER_RUNTIME_ID` |
| PostgreSQL 14 or newer | Everything Pipewright records |
| Stored files | A volume every gateway, worker and ticker shares, or an S3-compatible bucket |

People reach one address. A proxy in front sends `/api` to the gateway and
everything else to the web, so the sign-in cookie is shared by both: Caddy
does it in the Compose setup, the chart's ingress on Kubernetes. The web
image calls the API at `/api/v1` on its own host, so it works behind either
without rebuilding. Build it with `--build-arg NEXT_PUBLIC_API_BASE_URL=...`
only if the API has a host of its own.

## Settings

The settings that must be set before anyone uses it:

| Setting | Why |
| --- | --- |
| `DATABASE_URL` | `postgresql+psycopg://user:password@host:5432/database` |
| `AUTH_JWT_SECRET` | Signs sessions: `openssl rand -hex 32` |
| `APP_SECRET_ENCRYPTION_KEY` | Encrypts saved passwords, keys and signing secrets; without it none can be saved: `python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `AUTH_BOOTSTRAP_USERNAME`, `AUTH_BOOTSTRAP_PASSWORD` | The first administrator, made on first start |
| `WEB_BASE_URL` | Where people open Pipewright, for links in emails and embedded dashboards |
| `TRUSTED_PROXY_HOPS` | How many proxies are in front (1 behind Caddy or an ingress), for the gateway and the web |

Optional ones (single sign-on, storage encryption, mail, limits) are listed
in the [admin guide](user/admin.md#settings-reference). Keep the keys with
your other secrets: losing `APP_SECRET_ENCRYPTION_KEY` loses every saved
password, and losing `STORAGE_ENCRYPTION_KEY` loses every stored file.

## On one host with Docker Compose

```bash
cp .env.production.example .env
# replace each CHANGE value in .env: every service reads this one file
PIPEWRIGHT_TAG=v1.0.0 SITE_ADDRESS=pipewright.example.com \
  docker compose -f docker-compose.prod.yml up -d
```

This runs PostgreSQL, the four parts and Caddy, which fetches a certificate
for `SITE_ADDRESS`. The database is migrated before the gateway starts. For a
managed database, remove the `postgres` service and point `DATABASE_URL` at
it.

## On Kubernetes with Helm

You need Kubernetes 1.27 or newer, `kubectl`, Helm 3, an ingress controller,
PostgreSQL the cluster can reach, and either an S3-compatible bucket or a
storage class that offers `ReadWriteMany`. To try the chart on a cluster with
no database or bucket, `deploy/helm/trial-dependencies.yaml` makes a
throwaway PostgreSQL and MinIO; skip it in production.

**1. A namespace, and (to try it) the trial database and bucket.**

```bash
kubectl create namespace pipewright
kubectl -n pipewright apply -f deploy/helm/trial-dependencies.yaml
kubectl -n pipewright wait --for=condition=complete job/make-bucket --timeout=300s
```

**2. The secrets**, in a Secret you own, so nothing sensitive is in Helm's
values. With the trial dependencies, the database and bucket are as below;
otherwise use your own.

```bash
kubectl -n pipewright create secret generic pipewright-secrets \
  --from-literal=DATABASE_URL='postgresql+psycopg://pipewright:trial-only@postgres:5432/pipewright' \
  --from-literal=AUTH_JWT_SECRET="$(openssl rand -hex 32)" \
  --from-literal=APP_SECRET_ENCRYPTION_KEY="$(python3 -c 'import base64, os; print(base64.urlsafe_b64encode(os.urandom(32)).decode())')" \
  --from-literal=AUTH_BOOTSTRAP_USERNAME=admin \
  --from-literal=AUTH_BOOTSTRAP_PASSWORD='choose-a-long-password' \
  --from-literal=STORAGE_S3_ACCESS_KEY_ID=trial-access \
  --from-literal=STORAGE_S3_SECRET_ACCESS_KEY=trial-secret
```

**3. Install the chart.** The migration job runs first; a failed migration
stops the install rather than start code on a schema it does not match.

```bash
helm install pipewright deploy/helm/pipewright -n pipewright \
  --set image.tag=1.0.0 \
  --set secrets.existingSecret=pipewright-secrets \
  --set storage.backend=s3 \
  --set storage.s3.bucket=pipewright \
  --set storage.s3.endpointUrl=http://minio:9000 \
  --set ingress.enabled=true \
  --set ingress.host=pipewright.example.com \
  --set config.TRUSTED_PROXY_HOPS=1 \
  --wait --timeout 10m
```

For a real address, keep `ingress.tls.enabled` (the default) and give the
certificate's Secret as `ingress.tls.secretName`; to try it on a laptop, add
`--set ingress.tls.enabled=false`. With a bucket on AWS, leave out
`storage.s3.endpointUrl` and set `storage.s3.region`.

**4. Check it.** `https://pipewright.example.com/login` shows the sign-in
page; sign in with the bootstrap account, and **System status** says
whether the worker and the ticker are running. From a terminal:

```bash
curl -s https://pipewright.example.com/api/v1/health/ready
```

**Upgrading** is `helm upgrade` with the new `image.tag`; the migration job
runs before the new pods. **Removing it** is `helm uninstall pipewright -n
pipewright`; the namespace, your Secret and the trial dependencies stay until
you delete them.

CI installs the chart this way on a new kind cluster on every change (the
`helm` job in `.github/workflows/ci.yml`), so these steps are tested, not
only written.

## After deploying

- `/api/v1/health/live` and `/api/v1/health/ready` answer `200`.
- `/login` loads, and the bootstrap account signs in.
- **System status** shows the worker and the ticker, and lists the limits
  this server enforces.
- **Help** opens without signing in, and **Help → API reference** opens the
  interactive API reference (`/api/docs`).
- Upload a small file, or open the example from Home, and see its rows.

## Limits

- Stored files are one volume or one bucket shared by every part; there is
  no file storage per region.
- The ticker runs once per deployment (or once per `SCHEDULER_RUNTIME_ID`).
- Single sign-on is OIDC; SAML is not supported.
- There is no cloud-specific infrastructure code (Terraform and the like):
  the chart and Compose files are the deployment.
