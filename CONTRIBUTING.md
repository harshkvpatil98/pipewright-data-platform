# Contributing

Thanks for contributing to Pipewright.

## Before opening a PR

1. Read `README.md` and the relevant docs in `docs/`.
2. Set up the repo with `make setup`.
3. Run the app locally with `make dev` when your change touches runtime behavior.
4. Run verification before submitting:

```bash
make test
make verify
```

## Contribution guidelines

- Keep changes aligned with the current modular architecture.
- Prefer extending the owning service package rather than moving domain logic into the gateway.
- Keep docs truthful to the implemented product surface.
- Do not commit local `.env` files, secrets, or generated artifacts.
- Keep reviewer-facing docs polished when setup, routes, or workflows change.

## Docs to update when behavior changes

Update the relevant files when you change setup, product flow, or deployment behavior:

- `README.md`
- `docs/installation-guide.md`
- `docs/local-setup-guide.md`
- `docs/features-guide.md`
- `docs/architecture.md`
- `docs/demo-guide.md`
- `docs/deployment-guide.md`
- `docs/troubleshooting.md`
- `docs/release-checklist.md`
- `docs/agent-context.md`

## Repo conventions

- Node: use the repo’s documented local version expectations
- Python: `3.11+`
- Database: PostgreSQL
- Verification: `make verify` is the authoritative local CI-parity check

## Pull request checklist

- [ ] change is scoped and intentional
- [ ] tests or verification were run when appropriate
- [ ] docs were updated if setup, routes, or behavior changed
- [ ] no secrets or local-only files were added
