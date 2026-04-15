# Showcase Guide

Use this document when presenting the project in a recruiter screen, interview loop, portfolio review, or live technical walkthrough.

## Best short pitch

This project is a modular internal ETL and data operations platform built with Next.js, FastAPI, PostgreSQL, and Python service packages. It supports upload, profiling, transformation, lineage, audit, testing, downstream publishing, schedules, notifications, and system status in one reviewer-friendly application.

## Strongest angles to emphasize

- full-stack scope beyond CRUD
- modular backend architecture
- persisted workflow state and lineage
- operational depth through schedules, notifications, and status
- polished local-run and reviewer documentation

## Recruiter-friendly framing

If the audience is non-specialist, focus on:

- this is a full product workflow, not just a dashboard
- it shows backend architecture judgment, not only frontend polish
- it is easy to run locally and demo
- it is honest about current limitations while still feeling substantial

## Technical interviewer framing

If the audience is technical, focus on:

- the modular-monolith backend shape
- domain separation by service package
- shared contracts between frontend and backend
- persisted `pipeline_runs`, lineage, schedules, and notifications
- release verification, migrations, and deployment packaging

## Resume bullets

- Built a browser-based ETL and data operations platform covering ingestion, profiling, transformation, audit, testing, publishing, scheduling, notifications, and operational status.
- Designed a FastAPI gateway backed by domain-specific Python service packages and shared TypeScript contracts for a modular full-stack architecture.
- Persisted workflow state across datasets, derived outputs, run history, schedules, publish outcomes, and notifications to support traceability and post-run review.
- Packaged the project with Alembic migrations, Docker Compose, smoke checks, CI-style verification, and reviewer-facing documentation for a polished local handoff experience.

## Interview talking points

- The app is strongest when shown through the project-scoped workflow, not through placeholder top-level pages.
- Ingestion is modeled as a real workflow with artifact storage, profiling, and run tracking.
- Transformation preview is deliberately non-persistent, while pipeline run is persistent and lineage-aware.
- Audits, comparisons, and saved tests make the platform more reviewable and technically interesting.
- The repo includes deployment and release packaging because code quality is only part of the handoff story.

## Recommended live demo sequence

1. `/case-study`
2. `/demo`
3. `/login`
4. `/projects`
5. upload `samples/demo-customers.csv`
6. dataset detail
7. pipeline preview and run
8. audit or compare flow
9. publish or schedule flow
10. `/system-status`

## What not to overclaim

- Do not describe S3 or local export as implemented dataset publish targets.
- Do not describe the scheduler as a distributed orchestration platform.
- Do not imply self-service signup or advanced user management.
- Do not describe the top-level planned pages as fully implemented feature centers.

## Best supporting docs

- `README.md`
- `docs/reviewer-quick-summary.md`
- `docs/project-case-study.md`
- `docs/demo-guide.md`
- `docs/architecture.md`
