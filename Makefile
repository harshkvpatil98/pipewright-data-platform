SHELL := /bin/bash

setup-env:
	cp -n .env.example .env || true
	cp -n apps/web/.env.example apps/web/.env || true
	cp -n apps/api-gateway/.env.example apps/api-gateway/.env || true

setup:
	./scripts/setup.sh

dev:
	./scripts/dev.sh

lint:
	npm run lint --workspace @platform/web
	source .venv/bin/activate && ruff check apps/api-gateway/src services packages/shared-python/src

typecheck:
	npm run typecheck --workspace @platform/web

docker-up:
	docker compose up --build

docker-down:
	docker compose down

test:
	./scripts/test.sh

verify:
	./scripts/verify-release.sh

# Prerequisite + optional API checks (see docs/release-checklist.md). Not a substitute for `make verify`.
smoke:
	./scripts/smoke-test.sh

# Same checks as CI (fresh venv + verify). Use when testing CI locally without full setup.sh.
ci-verify:
	bash ./scripts/ci-bootstrap-python-venv.sh && bash ./scripts/verify-release.sh
