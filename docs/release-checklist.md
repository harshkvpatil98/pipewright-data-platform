# Release Checklist

Use this before a GitHub push, reviewer handoff, local demo session, or deployment packaging pass.

## Documentation and repo polish

- [ ] `README.md` is accurate and links to the main docs
- [ ] setup, architecture, demo, deployment, troubleshooting, and reviewer docs are internally consistent
- [ ] docs describe only implemented features
- [ ] placeholder or planned pages are not presented as complete modules

## Environment safety

- [ ] `.env` files with local values are ignored
- [ ] no real secrets are stored in example env files
- [ ] `APP_SECRET_ENCRYPTION_KEY` instructions are documented clearly
- [ ] `.gitignore` covers local runtime and generated artifacts

## Local run readiness

- [ ] `make setup` path is documented
- [ ] `make dev` path is documented
- [ ] bootstrap user creation is documented
- [ ] local URLs are documented
- [ ] `samples/demo-customers.csv` is referenced for demos

## Verification

- [ ] `make test`
- [ ] `make verify`
- [ ] `make smoke`

If the stack is not running, use:

```bash
SMOKE_SKIP_NETWORK=1 ./scripts/smoke-test.sh
```

## Reviewer flow

- [ ] `/case-study` is the first summary page
- [ ] `/demo` is the guided walkthrough
- [ ] `/system-status` is available as an operational proof point
- [ ] the main project workflow is easy to follow from `/projects`

## Deployment packaging

- [ ] `docker-compose.yml` and `docker-compose.prod.yml` are still documented correctly
- [ ] `apps/api-gateway/.env.production.example` and `apps/web/.env.production.example` are consistent with docs
- [ ] Alembic migration command is documented
- [ ] CI summary matches `.github/workflows/ci.yml`

## Honest scope reminders

- [ ] ingestion is described as synchronous
- [ ] scheduler is described as lease-based in Postgres
- [ ] audit export is described as HTML
- [ ] Postgres publish is described as implemented today
- [ ] S3 and local export are not described as implemented dataset publish flows
- [ ] BI publishing is described as practical publish support, not full BI administration

## Push readiness

- [ ] `git status` is clean except for the intended repo changes
- [ ] no local-only files are staged
- [ ] docs and hygiene files look coherent at the repo root
- [ ] commit message is clear and professional
