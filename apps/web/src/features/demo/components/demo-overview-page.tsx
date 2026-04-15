import Link from "next/link";

import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { ReleaseBuildMeta } from "@/components/release/release-build-meta";
import { CopyAppUrl } from "@/features/demo/components/copy-app-url";
import { CopyField } from "@/features/demo/components/copy-field";
import { appConfig } from "@/lib/config";

const capabilityCategories = [
  {
    title: "Platform core",
    items: ["JWT auth", "Project ownership", "Sources registry", "Versioned FastAPI gateway", "Postgres + Alembic"],
  },
  {
    title: "Data ingestion",
    items: ["CSV / XLSX / JSON upload", "Synchronous pipeline runs", "Schema, preview, and profile persistence", "Storage abstraction (local; S3-ready seam)"],
  },
  {
    title: "Transformation pipelines",
    items: ["Structured pipeline editor", "In-memory preview", "Run to derived datasets", "Rule-based transformation suggestions"],
  },
  {
    title: "Audit and testing",
    items: ["Dataset & run audit (read-only)", "HTML export", "Run comparison (Testing Lab)", "Dataset compare + statistical tests", "Saved tests + rerun history"],
  },
  {
    title: "Delivery and BI publishing",
    items: ["Postgres / S3 / local destinations + test", "PostgreSQL publish (replace / append)", "Power BI & Tableau connections", "Push dataset & Hyper publish flows"],
  },
  {
    title: "Scheduling and operations",
    items: ["Cron schedules + retries", "Trigger now", "Due-schedule executor (CLI / internal API)", "In-app notifications", "System status aggregation"],
  },
] as const;

const walkthroughSteps = [
  {
    title: "Create or open a project",
    detail: "Use an owned project as the workspace for all data and runs.",
    href: "/projects",
    cta: "Projects",
  },
  {
    title: "Upload a dataset",
    detail: "From project detail, upload CSV/XLSX/JSON. Try samples/demo-customers.csv from the repo.",
    href: "/projects",
    cta: "Go to projects",
  },
  {
    title: "Review profile and preview",
    detail: "Open the dataset: schema, preview rows, column insights, related pipeline run.",
    href: "/projects",
    cta: "Projects → dataset",
  },
  {
    title: "Create a transformation pipeline",
    detail: "From dataset detail: create pipeline, add steps, save.",
    href: "/projects",
    cta: "Via dataset detail",
  },
  {
    title: "Preview and run transformation",
    detail: "Preview in the editor, then run to create a derived dataset and transformation run.",
    href: "/projects",
    cta: "Pipeline editor",
  },
  {
    title: "Compare source vs derived",
    detail: "Use dataset comparison or “compare with parent” from a derived dataset.",
    href: "/projects",
    cta: "From dataset / compare",
  },
  {
    title: "Run or save a statistical test",
    detail: "From comparison: run Welch / proportion / chi-square; optionally save for reruns.",
    href: "/projects",
    cta: "Testing Lab",
  },
  {
    title: "View audit and export HTML",
    detail: "Dataset or run audit pages; download self-contained HTML reports.",
    href: "/projects",
    cta: "Audit from dataset/run",
  },
  {
    title: "Configure destination or BI connection",
    detail: "Project destinations (Postgres/S3/local) and BI connections (Power BI / Tableau) with test/discover.",
    href: "/projects",
    cta: "Destinations / BI",
  },
  {
    title: "Publish dataset",
    detail: "From dataset detail: PostgreSQL publish or BI publish when ingestion succeeded.",
    href: "/projects",
    cta: "Dataset detail",
  },
  {
    title: "Create a schedule",
    detail: "Transformation or Postgres publish schedules; Trigger now or due executor for cron.",
    href: "/projects",
    cta: "Schedules",
  },
  {
    title: "Notifications and system status",
    detail: "Check Notifications for run/publish outcomes; System status for gateway health and scheduler counters.",
    href: "/system-status",
    cta: "System status",
  },
] as const;

export function DemoOverviewPage() {
  const openApiDocs = `${appConfig.apiBaseUrl.replace(/\/api\/v1$/, "")}/docs`;

  return (
    <AppShell
      eyebrow="Internal overview"
      title="Demo & platform map"
      subtitle="Concise map of implemented capabilities and a recommended click path. Built for reviewers and demos—not a marketing site."
      actions={
        <div className="flex flex-wrap gap-2">
          <Link href="/projects">
            <Button size="sm">Open projects</Button>
          </Link>
          <Link href="/login">
            <Button variant="secondary" size="sm">
              Sign in
            </Button>
          </Link>
        </div>
      }
    >
      <SectionPanel
        title="Recommended first step"
        description="Sign in, open a project, then upload a small file (see samples/demo-customers.csv in the repository)."
      >
        <div className="flex flex-wrap gap-2">
          <Link
            href="/projects"
            className="rounded-xl border border-indigo-400/30 bg-indigo-500/10 px-4 py-2 text-sm font-medium text-indigo-100 hover:border-indigo-400/50"
          >
            1. Projects
          </Link>
          <span className="self-center text-slate-600">→</span>
          <span className="self-center text-sm text-slate-400">Upload dataset → pipeline → compare → audit → publish → schedules</span>
        </div>
      </SectionPanel>

      <SectionPanel
        title="What this platform does"
        description="Production-style modular ETL operations in the browser: ingestion through delivery, with runs, audits, and light-weight testing."
      >
        <ul className="list-inside list-disc space-y-2 text-sm text-slate-300">
          <li>Orchestrated actions persist as pipeline runs with structured summaries and logs.</li>
          <li>Project-scoped security: owned datasets, destinations, schedules, and BI configs.</li>
          <li>Operational surfaces: notifications, system status, and schedule execution hooks.</li>
        </ul>
        <p className="mt-4 text-xs text-slate-500">
          Repository walkthrough for reviewers: <code className="rounded bg-black/30 px-1">docs/demo-guide.md</code> · Deploy and
          CI: <code className="rounded bg-black/30 px-1">docs/deployment-guide.md</code> · Release checklist:{" "}
          <code className="rounded bg-black/30 px-1">docs/release-checklist.md</code> · Quick acceptance:{" "}
          <code className="rounded bg-black/30 px-1">./scripts/smoke-test.sh</code> or <code className="rounded bg-black/30 px-1">make smoke</code>
        </p>
      </SectionPanel>

      <SectionPanel title="Capability map" description="Implemented modules grouped for quick scanning.">
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {capabilityCategories.map((cat) => (
            <div key={cat.title} className="h-full rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-4">
              <div className="text-xs font-semibold uppercase tracking-[0.14em] text-slate-400">{cat.title}</div>
              <ul className="mt-3 space-y-2 text-sm text-slate-300">
                {cat.items.map((item) => (
                  <li key={item} className="flex gap-2">
                    <span className="text-emerald-400/90" aria-hidden>
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
        title="Guided walkthrough"
        description="Twelve-step path covering ingestion through operations. Links jump to areas that do not require IDs; deeper routes open from your current project."
      >
        <ol className="space-y-4">
          {walkthroughSteps.map((step, i) => (
            <li
              key={step.title}
              className="flex flex-col gap-3 rounded-2xl border border-white/[0.08] bg-black/20 px-4 py-4 transition hover:border-white/12 sm:flex-row sm:items-start sm:justify-between"
            >
              <div className="flex gap-3">
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg border border-white/10 bg-white/[0.06] text-xs font-semibold text-slate-200">
                  {i + 1}
                </span>
                <div>
                  <div className="font-medium text-white">{step.title}</div>
                  <p className="mt-1 text-sm text-slate-400">{step.detail}</p>
                  <span className="mt-2 inline-block text-[10px] uppercase tracking-[0.14em] text-slate-500">{step.cta}</span>
                </div>
              </div>
              <Link
                href={step.href}
                className="shrink-0 self-start rounded-lg border border-white/15 px-3 py-1.5 text-xs font-medium text-slate-200 hover:border-white/25 sm:self-center"
              >
                Open
              </Link>
            </li>
          ))}
        </ol>
        <p className="mt-4 text-xs text-slate-500">
          Use <Link href="/notifications" className="text-indigo-300 underline">Notifications</Link> from the sidebar for in-app alerts (step 12 focuses on system status).
        </p>
      </SectionPanel>

      <SectionPanel
        title="Quick links"
        description="Copy full URLs using the current browser origin. OpenAPI URL follows NEXT_PUBLIC_API_BASE_URL (default local gateway)."
      >
        <div className="grid gap-3 md:grid-cols-2">
          <CopyAppUrl label="Projects" path="/projects" />
          <CopyAppUrl label="Demo (this page)" path="/demo" />
          <CopyAppUrl label="Notifications" path="/notifications" />
          <CopyAppUrl label="System status" path="/system-status" />
          <CopyField label="OpenAPI docs" value={openApiDocs} />
        </div>
      </SectionPanel>

      <div className="mt-2 border-t border-white/[0.06] pt-4">
        <ReleaseBuildMeta />
      </div>
    </AppShell>
  );
}
