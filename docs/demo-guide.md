# Demo Guide

This guide is for live demos, recruiter walkthroughs, reviewer sessions, and local acceptance checks.

## Best demo audience fit

Use this flow when you want to show:

- product completeness
- architecture depth
- reviewer-friendly documentation
- an end-to-end ETL workflow that goes beyond CRUD

## Recommended starting point

Before the demo:

```bash
make dev
source .venv/bin/activate
set -a && source .env && set +a
platform-bootstrap-user --username "$AUTH_BOOTSTRAP_USERNAME" --password "$AUTH_BOOTSTRAP_PASSWORD" --role admin
make smoke
```

Optional full verification:

```bash
make verify
```

## First pages to open

Open these in order:

1. `/case-study`
2. `/demo`
3. `/login`
4. `/projects`

Why this order works:

- `/case-study` gives the concise hiring-manager summary
- `/demo` gives the guided product map
- `/login` proves the app is actually running
- `/projects` gets you into the real workflow surface

## Recommended demo data

Use:

- `samples/demo-customers.csv`

It is small, fast to upload, and well suited for ingestion, transformation, compare, audit, and publish flows.

## End-to-end demo flow

## 1. Sign in

Use the bootstrap credentials from root `.env`.

Expected result:

- the app redirects to `/projects`

## 2. Create or open a project

Expected result:

- the project detail page loads with sections for sources, datasets, and run history

## 3. Upload a dataset

Use `samples/demo-customers.csv`.

Expected result:

- the dataset appears in the project dataset list
- the ingestion run is persisted
- the dataset detail page shows preview, schema, and profile information

## 4. Walk the dataset detail page

Point out:

- file metadata
- preview rows
- schema summary
- profile summary
- related run
- suggested transformations

This is one of the strongest screens because it shows the app is storing useful artifact state, not just file names.

## 5. Create and preview a pipeline

From the dataset:

- create a pipeline
- add a few transformation steps
- preview the result
- save the pipeline

Suggested safe demo steps:

- rename columns
- trim strings
- filter rows
- select columns

Expected result:

- preview works without writing persistent derived output

## 6. Run the saved pipeline

Execute the saved pipeline.

Expected result:

- a derived dataset is created
- a transformation run is recorded
- lineage fields connect the derived dataset to the parent dataset and pipeline

## 7. Show review workflows

Open:

- dataset audit
- run audit
- dataset comparison
- saved tests

Good talking points:

- audits are read-only summaries from persisted metadata
- comparison and statistical testing make the repo stronger than a typical upload app
- HTML export exists today and is easy to demonstrate

## 8. Show destination or BI configuration

Choose one of these based on your environment:

- Postgres destination plus publish
- Power BI connection plus test or publish
- Tableau connection plus test or publish

If external credentials are not configured, you can still show the configuration screens and explain that those flows are implemented but depend on real target credentials.

## 9. Show schedules and notifications

Open:

- `/projects/[projectId]/schedules`
- `/notifications`
- `/projects/[projectId]/notification-targets`

Show:

- manual trigger
- schedule state
- notification outcomes
- optional external notification target support

## 10. Close with system status

Open:

- `/system-status`

Use it to show:

- gateway health
- service rows
- scheduler snapshot
- reviewer-friendly operational visibility

## What to say during the demo

- This is a modular internal data platform, not a toy dashboard.
- The workflow covers upload, profiling, transform, review, publish, schedule, and status.
- The backend is organized as domain services behind one API gateway.
- The repo includes setup, migrations, tests, smoke checks, and deployment docs.
- The scope is honest: synchronous ingestion and pragmatic operations instead of overclaiming distributed infrastructure.

## If you only have 5 minutes

Do this:

1. `/case-study`
2. `/demo`
3. sign in
4. open project
5. upload `samples/demo-customers.csv`
6. open dataset detail
7. show pipeline run and audit
8. end on `/system-status`

## If publish integrations are not configured

Say this plainly:

- Postgres publish is implemented locally when destination credentials are configured.
- Power BI and Tableau publishing are implemented, but they require real integration credentials and target accounts.
- The repo includes those flows without pretending they can run without external access.

## Current limitations to mention honestly

- ingestion is synchronous
- scheduler coordination is Postgres lease-based
- external notification delivery is best-effort
- audit export is HTML, not PDF
- destination publish is implemented for PostgreSQL, while S3 and local export are config and test surfaces today

## Related docs

- `docs/reviewer-quick-summary.md`
- `docs/project-case-study.md`
- `docs/showcase-guide.md`
- `docs/local-setup-guide.md`
