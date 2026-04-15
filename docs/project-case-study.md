# Project Case Study

## One-paragraph summary

Intelligent Data Platform is a browser-based ETL and data operations product designed to show what a serious internal data tool can look like when it is packaged like a real engineering project. The application supports project-scoped ingestion, profiling, transformation, lineage, audit, testing, downstream publishing, scheduling, notifications, and system status through a cohesive Next.js frontend and a modular FastAPI plus Python service backend.

## Problem this project solves

Data teams often juggle uploads, transformations, QA checks, publish jobs, and operational follow-up across disconnected scripts and admin tools. This project centralizes that workflow in one product surface so a user can move from dataset upload to downstream publish and operational review without leaving the platform.

## What is implemented today

- JWT login and project-scoped ownership
- Dataset upload for `csv`, `xlsx`, and `json`
- Persisted schema, preview, and profile metadata
- Saved transformation pipelines with preview and run execution
- Derived datasets with lineage and run history
- Dataset audit and run audit with HTML export
- Dataset comparison, run comparison, statistical tests, and saved test reruns
- Destination configuration and PostgreSQL publish
- Power BI and Tableau connection and publish flows
- Schedules, trigger-now, due execution hooks, and notifications
- System status, smoke checks, release verification, and deployment docs

## Why this stands out

This repo is stronger than a normal CRUD portfolio app because it models workflow state and operational behavior, not just record editing. It includes lineage, runs, audits, testing, publishing, scheduling, and status visibility. It also uses a modular backend structure with bounded service packages instead of concentrating everything in one controller layer.

## Architecture snapshot

- Frontend: Next.js App Router application in `apps/web`
- API gateway: FastAPI deployable in `apps/api-gateway`
- Domain services: Python service packages in `services/service-*`
- Shared infrastructure: `packages/shared-python`
- Shared contracts and UI primitives: `packages/shared-types`, `packages/shared-ui`
- Persistence: PostgreSQL plus filesystem-backed dataset artifacts

## Business value framing

- turns raw uploads into inspectable datasets with profile and preview metadata
- makes transformation logic reusable through saved pipelines
- improves reviewability with audit pages, compare flows, and saved tests
- supports downstream delivery and recurring operations instead of stopping at internal analysis
- demonstrates practical platform design without overbuilding infrastructure

## Strongest reviewer entry points

- `/case-study`
- `/demo`
- `/projects`
- `/system-status`
- `docs/reviewer-quick-summary.md`
- `docs/architecture.md`

## Recommended demo narrative

1. Explain that this is an internal data operations platform, not a consumer app.
2. Show `/case-study` and `/demo`.
3. Sign in and open a project.
4. Upload `samples/demo-customers.csv`.
5. Show dataset profiling and transformation workflow.
6. Show audit, compare, or saved test surfaces.
7. Show publish, schedule, and status surfaces.

## How to talk about it in interviews

- I built a modular ETL and data operations platform instead of a basic upload dashboard.
- I separated domain logic into service packages behind one API gateway so the backend can grow without collapsing into one file or route layer.
- I persisted workflow state across uploads, lineage, runs, audits, schedules, and publish outcomes so the platform is inspectable after execution.
- I packaged the repo with migrations, verification scripts, deployment references, and reviewer docs to make it easy to run and evaluate locally.

## Honest limitations

- ingestion is synchronous
- scheduler coordination is lease-based in Postgres
- external notification delivery is best-effort
- audit export is HTML only
- destination publish is implemented for PostgreSQL, not for every destination type
- BI support is publish-first functionality, not a complete BI governance layer
