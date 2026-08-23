import Link from "next/link";

import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ReleaseBuildMeta } from "@/components/release/release-build-meta";

const platformCapabilities = [
  {
    title: "Data ingestion and profiling",
    items: [
      "Project-scoped CSV / XLSX / JSON upload",
      "Schema inference, preview persistence, and profile summaries",
      "Pipeline-run tracking for ingestion outcomes",
    ],
  },
  {
    title: "Transformation and lineage",
    items: [
      "Saved transformation pipelines with structured editing",
      "Preview-only execution before running the saved pipeline",
      "Derived datasets with parent linkage and run history",
    ],
  },
  {
    title: "Quality, audit, and testing",
    items: [
      "Dataset and run audit summaries with HTML export",
      "Dataset comparison and run comparison views",
      "Statistical tests plus saved test definitions and rerun history",
    ],
  },
  {
    title: "Delivery and downstream publishing",
    items: [
      "Saved delivery destinations including PostgreSQL publish",
      "Power BI and Tableau connection management",
      "Tracked publish runs and reviewer-visible outcomes",
    ],
  },
  {
    title: "Operations control plane",
    items: [
      "Saved schedules with retries and trigger-now execution",
      "In-app notifications plus external email / Slack targets",
      "System status page and release verification workflow",
    ],
  },
] as const;

const moduleHighlights = [
  "Auth and project ownership enforced across project-scoped APIs",
  "Dataset ingestion with persisted preview, profile, and artifact metadata",
  "Transformation pipelines with preview, run execution, and lineage",
  "Audit, comparison, and Testing Lab surfaces built from persisted metadata",
  "Destinations, BI connections, and tracked publish flows",
  "Schedules, retries, notifications, and status verification surfaces",
] as const;

const endToEndFlow = [
  "Create or open a project and upload a dataset.",
  "Review preview, schema, and profile metadata on dataset detail.",
  "Create a pipeline, preview changes, and run it to produce a derived dataset.",
  "Compare results, run audits, export HTML, or save statistical tests.",
  "Publish to PostgreSQL or BI tools using saved destinations and connections.",
  "Operate the workflow with schedules, notifications, and system-status checks.",
] as const;

const businessValue = [
  "Reduces manual ETL coordination by centralizing ingestion, transformation, testing, and publishing in one control surface.",
  "Improves traceability by persisting run outcomes, lineage, audit summaries, and operational notifications.",
  "Supports reusable project-scoped pipelines and publishing workflows instead of one-off scripts.",
  "Provides a modular foundation for internal enterprise data workflows without requiring a large initial platform footprint.",
] as const;

const technicalHighlights = [
  "Modular service-oriented backend packages behind a single FastAPI gateway",
  "Typed frontend/backend contracts through shared TypeScript domain models",
  "Ownership-aware project scope instead of UI-only filtering",
  "Persisted run lineage, dataset artifacts, and audit-friendly metadata",
  "Destination and BI integration support with redacted configuration reads",
  "Scheduling, notification, and status surfaces that resemble production operations tooling",
  "Deployment and verification packaging through Docker, Alembic, Make targets, and CI parity scripts",
] as const;

const showcaseValueMap = [
  {
    feature: "Ingestion, profiling, and persisted dataset artifacts",
    value: "Moves teams away from ad hoc file handoffs and gives users a stable source-of-truth record after upload.",
  },
  {
    feature: "Transformation pipelines, preview, and derived lineage",
    value: "Makes repeatable data preparation visible and auditable instead of hiding business logic inside one-off scripts.",
  },
  {
    feature: "Audit, comparison, Testing Lab, and HTML export",
    value: "Supports reviewer trust, QA checks, and stakeholder communication beyond simple CRUD tables.",
  },
  {
    feature: "Destination / BI publishing plus schedules, notifications, and status",
    value: "Shows end-to-end operational thinking: not just creating data, but delivering it and monitoring recurring workflows.",
  },
] as const;

const showcaseTalkingPoints = [
  "Not a thin CRUD app: it coordinates ingestion, transformation, audit, testing, publishing, scheduling, notifications, BI integration, and ops status.",
  "Built with modular backend boundaries and typed contracts, so the architecture looks like a maintainable internal platform rather than a demo-only monolith.",
  "Persists meaningful operational state such as runs, lineage, schedule metadata, audit outputs, and notifications, which makes the workflow explainable after execution.",
  "Includes production-style packaging: migrations, env templates, release verification, smoke checks, and system-status visibility.",
] as const;

const reviewerSummary = [
  "This is not a thin CRUD app; it coordinates ingestion, transformation, audit, testing, publishing, and operational flows.",
  "The platform persists meaningful workflow state: datasets, pipeline runs, schedules, lineage, notifications, and integration configs.",
  "The architecture separates domain concerns into service packages rather than concentrating logic in page handlers or one large backend module.",
  "User and project ownership are enforced through service contracts, not just frontend navigation.",
  "The repo includes operational packaging: migrations, env templates, release verification, CI parity, and deploy docs.",
  "The UI demonstrates serious internal-tool product thinking: project workspaces, audit surfaces, Testing Lab, publish controls, and status dashboards.",
  "The current implementation is intentionally pragmatic: synchronous ingestion and single-process-oriented scheduling, with clear seams for future scaling.",
] as const;

export function CaseStudyPage() {
  return (
    <AppShell
      eyebrow="Project summary"
      title="ETL platform case study"
      subtitle="A reviewer-friendly technical brief describing the implemented product, the engineering depth behind it, and the business value it delivers."
      actions={
        <div className="flex flex-wrap gap-2">
          <Link href="/demo">
            <Button size="sm">Open demo guide</Button>
          </Link>
          <Link href="/projects">
            <Button variant="secondary" size="sm">
              Open projects
            </Button>
          </Link>
        </div>
      }
    >
      <SectionPanel
        title="Project overview"
        description="This platform is a browser-based internal data operations product for project-scoped ETL work: upload data, profile it, transform it, validate outcomes, publish downstream, and operate recurring workflows."
      >
        <div className="grid gap-4 lg:grid-cols-[1.2fr_0.8fr]">
          <div className="h-full rounded-2xl border border-accent-line bg-accent-soft px-5 py-4 text-sm text-ink">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Problem solved</div>
            <p className="mt-3 leading-6 text-ink">
              Data teams often end up stitching together file uploads, ad hoc transformation scripts, one-off QA checks, manual publishes,
              and scattered operational follow-up. This project brings those concerns into one modular platform with shared run tracking,
              ownership enforcement, and reviewer-visible operational surfaces.
            </p>
          </div>
          <div className="h-full rounded-2xl border border-line bg-surface px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-3">What it does today</div>
            <ul className="mt-3 space-y-2 text-sm text-ink-2">
              {moduleHighlights.map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="text-success" aria-hidden>
                    ·
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel
        title="Why this project matters"
        description="A concise showcase layer for interviews and portfolio reviews: what it is, why it is stronger than CRUD, and how features map to business value."
      >
        <div className="grid gap-4 xl:grid-cols-[0.95fr_1.05fr]">
          <div className="rounded-2xl border border-accent-line bg-accent-soft px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-accent">Technical elevator pitch</div>
            <p className="mt-3 text-sm leading-6 text-ink">
              This is a modular ETL operations platform, not a single-page CRUD demo. It covers ingestion, profiling, transformation,
              audit, testing, downstream publishing, scheduling, notifications, BI integration, and operational status through one
              reviewer-friendly product shell backed by service-oriented Python packages and typed frontend contracts.
            </p>
            <div className="mt-4 text-xs uppercase tracking-[0.16em] text-muted">Interviewer talking points</div>
            <ul className="mt-3 space-y-2 text-sm text-ink-2">
              {showcaseTalkingPoints.map((item) => (
                <li key={item} className="flex gap-2">
                  <span className="text-success" aria-hidden>
                    ·
                  </span>
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-line bg-surface px-5 py-4">
            <div className="text-xs font-semibold uppercase tracking-[0.18em] text-ink-3">Feature to business value</div>
            <div className="mt-3 space-y-3">
              {showcaseValueMap.map((row) => (
                <div key={row.feature} className="rounded-2xl border border-line bg-sunken px-4 py-3">
                  <div className="text-sm font-medium text-ink">{row.feature}</div>
                  <p className="mt-1 text-sm leading-6 text-ink-3">{row.value}</p>
                </div>
              ))}
            </div>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel
        title="Core architecture"
        description="The project is organized like a real internal platform: one web app, one public gateway, explicit domain packages, shared contracts, and persistent run state."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          <div className="rounded-2xl border border-line bg-surface px-4 py-4">
            <div className="text-xs uppercase tracking-[0.16em] text-muted">Frontend</div>
            <p className="mt-3 text-sm text-ink-2">Next.js App Router UI with project workspaces, review pages, operational controls, and typed fetch helpers.</p>
          </div>
          <div className="rounded-2xl border border-line bg-surface px-4 py-4">
            <div className="text-xs uppercase tracking-[0.16em] text-muted">Gateway</div>
            <p className="mt-3 text-sm text-ink-2">FastAPI gateway exposing one versioned API surface while delegating domain logic to service packages.</p>
          </div>
          <div className="rounded-2xl border border-line bg-surface px-4 py-4">
            <div className="text-xs uppercase tracking-[0.16em] text-muted">Domain services</div>
            <p className="mt-3 text-sm text-ink-2">Separate service packages for datasets, ingestion, pipeline runs, comparisons, destinations, schedules, notifications, and more.</p>
          </div>
          <div className="rounded-2xl border border-line bg-surface px-4 py-4">
            <div className="text-xs uppercase tracking-[0.16em] text-muted">Persistence and storage</div>
            <p className="mt-3 text-sm text-ink-2">PostgreSQL via SQLAlchemy/Alembic plus file storage abstraction for dataset artifacts and derived outputs.</p>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel
        title="Implemented capability map"
        description="Only implemented modules are listed here; this page is intended to be accurate enough for recruiter and reviewer review."
      >
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {platformCapabilities.map((group) => (
            <div key={group.title} className="h-full rounded-2xl border border-line bg-sunken px-4 py-4">
              <div className="text-sm font-semibold text-ink">{group.title}</div>
              <ul className="mt-3 space-y-2 text-sm text-ink-2">
                {group.items.map((item) => (
                  <li key={item} className="flex gap-2">
                    <span className="text-accent" aria-hidden>
                      ·
                    </span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </SectionPanel>

      <SectionPanel
        title="End-to-end flow"
        description="A reviewer can describe the product through a single operational path from raw file upload to downstream delivery."
      >
        <ol className="grid gap-3 lg:grid-cols-2">
          {endToEndFlow.map((step, index) => (
            <li key={step} className="flex gap-3 rounded-2xl border border-line bg-surface px-4 py-4">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-line bg-surface-2 text-xs font-semibold text-ink">
                {index + 1}
              </span>
              <span className="pt-1 text-sm text-ink-2">{step}</span>
            </li>
          ))}
        </ol>
      </SectionPanel>

      <div className="grid gap-6 xl:grid-cols-2">
        <SectionPanel
          title="Business value"
          description="This platform is useful because it consolidates recurring data operations work into a controlled, reviewable workflow."
        >
          <ul className="space-y-3 text-sm text-ink-2">
            {businessValue.map((item) => (
              <li key={item} className="rounded-2xl border border-line bg-surface px-4 py-3 leading-6">
                {item}
              </li>
            ))}
          </ul>
        </SectionPanel>

        <SectionPanel
          title="Technical highlights"
          description="The engineering depth comes from orchestration, modularity, persistence, and operations support rather than from isolated UI polish."
        >
          <ul className="space-y-3 text-sm text-ink-2">
            {technicalHighlights.map((item) => (
              <li key={item} className="rounded-2xl border border-line bg-surface px-4 py-3 leading-6">
                {item}
              </li>
            ))}
          </ul>
        </SectionPanel>
      </div>

      <SectionPanel
        title="What makes this project strong"
        description="The value for reviewers is not just that multiple pages exist, but that the platform demonstrates real software engineering concerns."
      >
        <div className="grid gap-4 md:grid-cols-2">
          <div className="rounded-2xl border border-line bg-surface px-5 py-4">
            <div className="text-xs uppercase tracking-[0.16em] text-muted">Production-oriented posture</div>
            <p className="mt-3 text-sm leading-6 text-ink-2">
              The repo includes migrations, shared contracts, env templates, Docker-based local runtime, release verification scripts, CI parity,
              status aggregation, redacted config handling, and operational notifications. That makes it substantially more representative than a
              basic CRUD portfolio project.
            </p>
          </div>
          <div className="rounded-2xl border border-line bg-surface px-5 py-4">
            <div className="text-xs uppercase tracking-[0.16em] text-muted">Multi-step workflow depth</div>
            <p className="mt-3 text-sm leading-6 text-ink-2">
              Users can move from ingestion to transformation, lineage, audit, testing, publishing, scheduling, and notification review within one
              coherent platform. That end-to-end flow shows orchestration and state management complexity beyond isolated forms and tables.
            </p>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel
        title="How to talk about this project"
        description="Use these points in a recruiter screen, portfolio walkthrough, or technical interview."
      >
        <ul className="space-y-3 text-sm text-ink-2">
          {reviewerSummary.map((item) => (
            <li key={item} className="rounded-2xl border border-line bg-sunken px-4 py-3">
              {item}
            </li>
          ))}
        </ul>
        <div className="mt-4 flex flex-wrap gap-2 text-xs text-muted">
          <span className="rounded-full border border-line px-3 py-1">Internal tooling</span>
          <span className="rounded-full border border-line px-3 py-1">Modular backend</span>
          <span className="rounded-full border border-line px-3 py-1">ETL operations</span>
          <span className="rounded-full border border-line px-3 py-1">Auditability</span>
          <span className="rounded-full border border-line px-3 py-1">Operational workflows</span>
        </div>
      </SectionPanel>

      <SectionPanel
        title="Reviewer entry points"
        description="Use the page below depending on whether someone wants a quick product summary, a guided click path, or detailed documentation."
      >
        <div className="grid gap-4 md:grid-cols-3">
          <div className="rounded-2xl border border-line bg-surface px-4 py-4">
            <div className="text-sm font-semibold text-ink">Case study</div>
            <p className="mt-2 text-sm text-ink-3">This page: concise business and technical framing for recruiters and reviewers.</p>
          </div>
          <div className="rounded-2xl border border-line bg-surface px-4 py-4">
            <div className="text-sm font-semibold text-ink">Demo guide</div>
            <p className="mt-2 text-sm text-ink-3">Use `/demo` for the click path and `docs/demo-guide.md` for setup plus verification details.</p>
          </div>
          <div className="rounded-2xl border border-line bg-surface px-4 py-4">
            <div className="text-sm font-semibold text-ink">Architecture docs</div>
            <p className="mt-2 text-sm text-ink-3">Use `README.md`, `docs/architecture.md`, and `docs/agent-context.md` for deeper technical detail.</p>
          </div>
        </div>
      </SectionPanel>

      <SectionPanel
        title={"Release candidate & known limitations"}
        description="Honest scope for handoff. This is a repo-contained platform, not a full cloud control plane."
      >
        <ul className="space-y-2 text-sm text-ink-2">
          <li>
            <strong className="font-medium text-ink">Ready-for-review flow:</strong> follow <code className="rounded bg-sunken px-1 text-xs">docs/release-checklist.md</code>, run{" "}
            <code className="rounded bg-sunken px-1 text-xs">make verify</code> for full CI-parity checks, and{" "}
            <code className="rounded bg-sunken px-1 text-xs">make smoke</code> (or <code className="rounded bg-sunken px-1 text-xs">./scripts/smoke-test.sh</code>) with the gateway up for a quick API sanity check.
          </li>
          <li>
            Scheduler execution uses <strong className="font-medium text-ink">Postgres-backed leases</strong> for safer multi-poller setups; it is not equivalent to a distributed job platform, Redis locks, or leader election.
          </li>
          <li>
            Sensitive integration fields use <strong className="font-medium text-ink">app-level Fernet encryption</strong> in the database; external KMS/Vault is not bundled.
          </li>
          <li>
            <strong className="font-medium text-ink">BI publishing</strong> covers practical push/Hyper flows—not full semantic modeling, workbook automation, or hosted BI administration.
          </li>
          <li>
            <strong className="font-medium text-ink">External notifications</strong> (email, Slack webhook) are best-effort fan-out from the same events as in-app notifications.
          </li>
          <li>
            <strong className="font-medium text-ink">Packaging</strong> is Compose/Dockerfile-centric; production IaC, multi-region, and managed observability are out of scope for this repository.
          </li>
        </ul>
      </SectionPanel>

      <div className="mt-2 border-t border-line pt-4">
        <ReleaseBuildMeta />
      </div>
    </AppShell>
  );
}
