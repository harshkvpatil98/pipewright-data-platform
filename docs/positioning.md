# What Pipewright is for

Pipewright is a data workbench a team runs on its own servers. It brings
data in from files, databases and business apps, lets people clean and
combine it in a visual Studio without writing code, checks that it is
right, runs the work on a timetable, and delivers the results to databases,
storage, BI tools and dashboards. Every step is recorded and every version
of every dataset is kept.

## Who it is for

- **Teams that own their data but have no data-engineering team**: finance,
  operations, sales operations, analysts. They clean, check and deliver data
  themselves; the help, the plain wording and the guided first run are built
  for people who have never used a data tool.
- **Organisations that must keep data in their own infrastructure**, for
  regulation or policy: self-hosted, with single sign-on, two-factor
  sign-in, roles per project, row and column policies on every read, network
  allow-lists, encryption at rest and an audit log in sentences.
- **Consultancies and partners serving several clients**: one project per
  client, work moved between projects as a bundle, dashboards embedded in a
  client's own site with per-customer filters, and webhooks into their
  systems.

## What it is not for

- **A data warehouse.** It prepares and delivers data; it does not replace
  PostgreSQL, Snowflake or BigQuery as the place analytics queries run.
- **Big data.** It processes a dataset on one machine, in memory. It is not
  Spark, and it is not for billions of rows (see the envelope below).
- **Real-time streaming.** It takes inbound webhooks and PostgreSQL change
  capture in small batches, at least once. It does not do windows, joins
  across streams or exactly-once delivery.
- **An enterprise semantic layer or a replacement for a BI suite.** Its
  charts, dashboards and metrics serve the people who prepare the data and
  those they share with; Power BI and Tableau are delivery targets, not
  competitors.
- **Machine learning.** Nothing in it trains or calls a model; the
  Assistant's findings come from rules applied to the data, and say so.

## The envelope it is tested in

Measured on this release, unless marked as a starting point.

| | |
| --- | --- |
| One uploaded file | up to 200MB; a 199MB CSV (3,957,935 rows) is read in 37 s, with a worker peak of 1.86GB |
| A chart, or the Assistant's analysis | datasets of up to 500,000 rows; larger ones are grouped or filtered by a recipe first |
| Checks | any size; 4,000,000 rows checked in about a second |
| A delivery to a database | 1,003,735 rows to MySQL in 21 s, on the background worker |
| Copying a database | up to 2,000,000 rows a table |
| Runs at once | 4 per project by default, recipe runs, imports, deliveries and workflows together (`PROJECT_RUNS_AT_ONCE`, or the project's own setting); more wait their turn, a person's first |
| One run's data | up to 2GB by default (`RUN_MEMORY_LIMIT_MB`); a step past it stops with the step and the size |
| Changing step 14 of a 15-step recipe | under a second on 1,000,000 rows, from what the earlier steps made |
| A re-run after rows were appended | computes only the new rows: 1,000 added to 1,000,000 in 6.5 s, against 17.2 s in full |
| A run whose worker stops | noticed and failed with the reason within 3 minutes; it can then be picked up from where it failed |
| API response times | p95 budgets on ten endpoints enforced in CI (for example, the project list within 1 s) |
| People per deployment | starting points, not measured: a trial on one machine; about 50 with two gateways; about 500 with three to six gateways and a larger database ([sizing](operations.md#sizing)) |

## How it is deployed

On one host with Docker Compose (PostgreSQL, the web, the gateway, a worker,
a ticker and Caddy for TLS), or on Kubernetes with the Helm chart, which CI
installs on a new cluster on every change. Gateways, web servers and workers
scale out; stored files live on a shared volume or an S3-compatible bucket.
See the [deployment guide](deployment-guide.md).

## What is not proven yet

- 161 of the 211 connectors were written from vendor documentation and have
  not run against the real service; each says so wherever it appears.
- Single sign-on is tested against Keycloak; Okta and Entra ID have not been
  run. SAML is not supported.
- Usability sessions with people outside the team have not been run yet;
  [the protocol](cold-user-sessions.md) is ready.
- English is the one language.
