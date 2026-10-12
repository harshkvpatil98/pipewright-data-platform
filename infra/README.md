# Infrastructure

Reserved for infrastructure that sits outside the application — cloud
provisioning, for example. Nothing is deployed from here yet.

The deployment assets that exist today live elsewhere:

- [`deploy/helm/pipewright`](../deploy/helm/pipewright/README.md) — the Helm
  chart (gateway, web, workflow worker, schedule ticker, migration Job,
  ingress, autoscaling);
- [`deploy/Caddyfile`](../deploy/Caddyfile) — the TLS-terminating reverse proxy
  used by [`docker-compose.prod.yml`](../docker-compose.prod.yml);
- [`.github/workflows/release-images.yml`](../.github/workflows/release-images.yml)
  — gateway and web images pushed to GHCR on a version tag.

Day-two operations are in [docs/operations.md](../docs/operations.md).
