# Contributing to Pipewright

Thanks for taking the time. This guide covers how to get a working checkout,
the gate every change has to pass, and the rules the code relies on. Read
[docs/HANDOFF.md](docs/HANDOFF.md) for the current state of the project — what
is done, what is next, and the gaps that are known and stated.

Everyone taking part is expected to follow the
[code of conduct](CODE_OF_CONDUCT.md). A security problem goes through the
[security policy](SECURITY.md), never a public issue.

## Prerequisites

| Tool | Version | Why |
|---|---|---|
| Node.js | 22.x | `rush.json` accepts `>=22 <23`; CI runs 22 |
| npm | 10.x | npm workspaces install the web app and shared packages |
| Python | 3.11 or newer | every `pyproject.toml` requires `>=3.11`; CI runs 3.11. On macOS the system Python is too old — use Homebrew's `python@3.12` |
| Docker | any recent | PostgreSQL 16 for development, and the connector test servers |

## Setting up

```bash
make setup     # .env files from the examples, npm install, .venv with every
               # Python package installed editable, an encryption key, and —
               # when Docker is running — Postgres plus `alembic upgrade head`
make dev       # Postgres, migrations, gateway on :8000, workflow worker and
               # schedule ticker, web on :3000
```

`make dev` refuses to start when Postgres is unreachable; that message is
accurate — start Docker. Set `PW_DEV_NO_WORKERS=1` to run without the worker
and ticker, and `BACKEND_PORT` / `FRONTEND_PORT` to move the servers.

Create the first admin once, in a second terminal:

```bash
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" \
  --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
```

`make setup` and `npm run setup` are the same script (`scripts/setup.sh`); so
are `make dev` / `npm run dev`, `make test` / `npm test` and `make verify` /
`npm run verify`.

## The gate

```bash
npm run verify    # ruff, the pytest bundle, web tests (Vitest), ESLint,
                  # tsc --noEmit, and the production web build
```

This is `scripts/verify-release.sh`, and it is exactly what CI runs after
installing dependencies. Everything must be green before a change is done.

- `scripts/test.sh` lists its pytest paths explicitly. **A new test directory
  has to be added there** or it never runs, locally or in CI.
- pytest runs with `--import-mode=importlib` and the test directories have no
  `__init__.py`. Two `conftest.py` files with the same basename collide, which
  is why fixtures are defined per module.
- The bar is zero warnings in the pytest summary. A warning is fixed at its
  source or filtered at the exact site with the reason written next to it
  (see `pytest.ini`).

To run one service's tests:

```bash
.venv/bin/python -m pytest --import-mode=importlib services/service-transformations -q
```

### What a local run does not cover

CI starts real PostgreSQL, MySQL and MariaDB servers, and fails the build if
they are unreachable, because the tier-2 connector claims rest on them. Without
them `test_containers.py` skips those tests — a skip, not a pass. To run them
locally:

```bash
docker compose -f docker-compose.connectors.yml up -d --wait
export CONNECTORS_TEST_POSTGRES_URL=postgresql+psycopg://platform:platform@127.0.0.1:15432/platform
export CONNECTORS_TEST_MYSQL_URL=mysql+pymysql://root:platform@127.0.0.1:13306/platform
export CONNECTORS_TEST_MARIADB_URL=mysql+pymysql://root:platform@127.0.0.1:13307/platform
.venv/bin/python scripts/check-connector-servers.py
npm run verify
```

Other differences worth knowing: notebook Python cells are disabled on macOS
(the sandbox cannot apply a memory limit there), so their tests skip on a Mac;
and the PostgreSQL change-data-capture round trip needs `wal_level=logical`,
which the development compose file sets and the CI service container does not.
`make ci-verify` rebuilds `.venv` the way CI does
(`scripts/ci-bootstrap-python-venv.sh`) before running the gate.

When you report results — in a pull request or anywhere else — passed, failed,
skipped and could-not-run are four different outcomes. Say which.

## Invariants

These are enforced by existing code and tests. Breaking one is a bug, not a
style disagreement; the reasoning behind each is in
[docs/HANDOFF.md §5–§8](docs/HANDOFF.md#5-architecture-rules--violating-these-breaks-things).

- **Permission is decided in one place.** A dependency on the whole API router
  reads the method and path (`service_access/permissions.py`); tenancy is
  resolved in the same place (`service_projects.contracts.project_role`). Do
  not add per-route ownership checks. An unrecognised write path requires
  `editor` — failing closed is the design.
- **Services extend each other through registered hooks**
  (`register_role_resolver`, `register_snapshotter`,
  `register_reference_resolver`), never by importing another service's
  internals.
- **Use `sqlalchemy.Uuid`**, not `sqlalchemy.dialects.postgresql.UUID`: SQLite
  gives the latter numeric affinity, and an all-digit UUID becomes a float.
- **IR join sides are positional** — the first operand is the left input, the
  second the right. Resolving them by name silently produces a cartesian
  product.
- **Lineage is derived, never stored.** `service_lineage/columns.py` is the
  deriver; adding a transformation step means updating it, and a test enforces
  that every step type is known to it.
- **Three-valued logic is real.** Comparisons return a nullable boolean with NA;
  only `Filter` and `Case` collapse NA to false. `SUM` of an all-null group is
  NULL, not 0.
- **A dialect that cannot express something raises `Unsupported`.** Never
  approximate; the planner keeps that node local.
- **Capabilities are reported honestly.** A connector declares only what works
  here, and its tier says how that is known. Every `service-intelligence`
  result names the method that produced it, and that service makes **no model
  calls**.
- **The frontend has no icon library and no chart library** — every icon and
  chart is hand-written SVG. Never write a raw colour literal; use the semantic
  theme tokens (`no-raw-colours.test.ts` enforces this across `apps/web/src`
  and `packages/shared-ui/src`).

Never weaken, skip, delete or narrow a failing test to get a green run. A test
that is genuinely wrong may be corrected, with the reason stated in the change.

## Common changes

- **A database change** is a new Alembic revision in
  `apps/api-gateway/alembic/versions/`, numbered after the current head. Add a
  revision rather than editing one that has shipped. The suite builds tables
  with `Base.metadata.create_all` on SQLite; the Alembic chain itself needs
  PostgreSQL.
- **A connector**: follow [docs/adding-a-connector.md](docs/adding-a-connector.md).
  A tier above 4 must cite the test file that drives the connector.
- **A transformation tool** is one declaration in a category module under
  `services/service-transformations/src/service_transformations/tools/`, then
  `scripts/generate-tool-reference.py`. `docs/transformation-tools.md` is
  generated, and a test fails if the checked-in copy drifts — do not edit it by
  hand.
- **A new service** needs its `pyproject.toml`, an entry in the install order in
  `scripts/setup.sh` and `scripts/ci-bootstrap-python-venv.sh`, and its test
  directory in `scripts/test.sh`.

## Where the truth lives

When two sources disagree, the code and the tests that pass win, then the
ledger in [docs/HANDOFF.md](docs/HANDOFF.md), then the roadmap prose in
[docs/roadmap-v2.md](docs/roadmap-v2.md). Record a contradiction you find,
with file evidence, rather than silently picking one side.

Update the documentation in the same change as the behaviour:

- `docs/HANDOFF.md` — the progress ledger, and §7 when a known gap opens or
  closes;
- `README.md` — when what the platform can do, or how to run it, changes;
- [docs/security.md](docs/security.md) — when authentication, authorisation or
  secret handling changes;
- [docs/operations.md](docs/operations.md) and the Helm chart's README — when
  deployment or scaling changes.

## Commits and pull requests

Commit messages describe the software change in the imperative, the way the
history does: `P9: the IR is the only executor`, `Let a dataset be renamed and
deleted, and take its file with it`. The body says why, and gives the evidence —
the test counts from the gate, and what you checked against a running stack.
Commits carry the author's own name and email, with no tool or bot attribution
trailers.

Pull requests use the template: what changed, the evidence, and the gate
checklist. Keep a pull request to one concern, and never commit `.env` files,
uploaded data, `backups/` or build output.
