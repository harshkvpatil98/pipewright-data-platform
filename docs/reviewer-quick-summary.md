# Reviewer Quick Summary

## 30-second summary

This repo is a modular internal ETL and data operations platform, not a simple CRUD demo. A user can upload tabular data, inspect schema and profiling results, create and run transformation pipelines, compare outputs, export audits, publish downstream, schedule recurring work, and monitor status and notifications through one web application backed by a versioned API and modular Python services.

## 2-minute technical summary

The frontend is a Next.js App Router application. The backend is a FastAPI gateway that mounts routers from domain-specific Python service packages for auth, projects, ingestion, datasets, transformations, pipeline runs, comparisons, destinations, schedules, and notifications. PostgreSQL stores application state, while uploaded and derived dataset artifacts are stored through a shared storage abstraction. Shared TypeScript contracts keep the frontend and backend aligned.

What makes the repo stand out is not just that these features exist, but that the workflow state is persisted. Uploads become datasets with preview and profile metadata. Saved pipelines create derived datasets with lineage. Audits, comparisons, publish outcomes, schedules, and notifications all connect back to a consistent run history model. The repo also includes migrations, Docker Compose, smoke checks, CI verification, and detailed docs, so it evaluates well both as an application and as a handoff-ready codebase.

## Why this project stands out

- It demonstrates end-to-end workflow orchestration instead of isolated CRUD screens.
- It uses service boundaries behind one gateway rather than centralizing all logic in one module.
- It includes operational surfaces such as schedules, notifications, publish tracking, and status pages.
- It includes reviewer-friendly assets such as `/case-study`, `/demo`, setup docs, and release docs.
- It is honest about current limitations instead of overclaiming distributed infrastructure or fake scale.

## Resume-ready bullets

- Built a modular browser-based ETL and data operations platform spanning ingestion, profiling, transformation, audit, testing, downstream publishing, scheduling, notifications, and operational status.
- Designed a FastAPI gateway backed by domain-focused Python service packages and shared TypeScript contracts, keeping frontend and backend behavior aligned.
- Persisted workflow state for datasets, pipeline runs, lineage, saved tests, publish outcomes, schedules, and notifications to support traceability and post-run inspection.
- Packaged the project with Alembic migrations, Docker Compose, smoke checks, CI-parity verification, and reviewer-oriented documentation for a polished local handoff story.

## Interview talking points

- The strongest architectural choice is the modular-monolith backend shape: one deployable, multiple bounded services.
- The strongest product choice is project-scoped workflow ownership instead of global admin-only surfaces.
- The strongest reviewer-facing choice is the combination of `/case-study`, `/demo`, audit pages, status visibility, and local-run docs.
- The strongest credibility point is the honest scope: synchronous ingestion, lease-based scheduling, and best-effort external notifications instead of inflated claims.

## Recommended demo order

1. Open `/case-study`
2. Open `/demo`
3. Sign in at `/login`
4. Open `/projects`
5. Upload `samples/demo-customers.csv`
6. Show dataset detail
7. Show pipeline preview and run
8. Show compare or audit
9. Show publish or schedule surfaces
10. End on `/system-status`

## What to click first

If the reviewer only clicks one thing, start with:

- `/case-study` for the summary

If they want to see the app flow immediately, go next to:

- `/demo`
