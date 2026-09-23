# Pipewright Helm chart

Deploys the gateway, web app, workflow worker, and schedule ticker. Postgres is
external by default — point `secrets.DATABASE_URL` (or `secrets.existingSecret`)
at a managed instance.

## Install

```sh
helm install pipewright deploy/helm/pipewright \
  --set image.tag=v1.2.3 \
  --set secrets.existingSecret=pipewright-secrets \
  --set ingress.enabled=true --set ingress.host=pipewright.example.com
```

- `image.tag` is required (the chart never deploys `latest`).
- Migrations run as a pre-install/pre-upgrade Job (`alembic upgrade head`), so
  schema is current before any new pod serves traffic.
- Keep `ticker.replicaCount: 1` unless each ticker has a distinct
  `SCHEDULER_RUNTIME_ID`; scale `worker.replicaCount` freely (leased queue).
- Ingress routes `/api` to the gateway and `/` to the web on one host, so the
  SSO session cookie carries across both. See `docs/operations.md`.

## Scaling

Enable per-component HPAs with `gateway.autoscaling.enabled=true` /
`web.autoscaling.enabled=true`; tune `min/maxReplicas` and the CPU target.
