import Link from "next/link";

import { KpiCard } from "@/components/dashboard/kpi-card";
import { SectionCard } from "@/components/dashboard/section-card";
import { StatusBadge } from "@/components/dashboard/status-badge";
import { AppShell } from "@/components/layout/app-shell";
import { navigationItems } from "@/lib/navigation";

const foundationHighlights = [
  {
    label: "Platform posture",
    value: "Production-ready scaffold",
    tone: "success" as const,
  },
  {
    label: "API contract",
    value: "Versioned FastAPI v1",
    tone: "default" as const,
  },
  {
    label: "Primary datastore",
    value: "PostgreSQL wired",
    tone: "default" as const,
  },
  {
    label: "Runtime model",
    value: "Docker Compose enabled",
    tone: "warning" as const,
  },
];

const futureDomains = [
  "Authentication and RBAC",
  "Dataset and source management",
  "Profiling and discrepancy detection",
  "Transformation pipelines and execution",
  "Audit reports and validation",
  "Statistical testing and comparisons",
  "Integrations, destinations, and scheduling",
  "Governance, versioning, and notifications",
];

export default function HomePage() {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";

  return (
    <AppShell
      title="Platform Overview"
      subtitle="A serious web foundation for intelligent data ingestion, data quality, transformation, testing, and governance workflows."
    >
      <section className="rounded-2xl border border-indigo-400/20 bg-indigo-500/[0.07] px-5 py-4 text-sm text-slate-200">
        <span className="font-semibold text-white">Demo & walkthrough:</span>{" "}
        <Link href="/demo" className="text-indigo-200 underline hover:text-white">
          Open the in-app demo map
        </Link>{" "}
        for a guided click path, or open the{" "}
        <Link href="/case-study" className="text-indigo-200 underline hover:text-white">
          in-app case study
        </Link>{" "}
        for a recruiter-friendly project summary. See also{" "}
        <code className="rounded bg-black/25 px-1 text-xs">docs/demo-guide.md</code> in the repository.
      </section>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {foundationHighlights.map((item) => (
          <KpiCard key={item.label} label={item.label} value={item.value}>
            <StatusBadge tone={item.tone}>{item.label}</StatusBadge>
          </KpiCard>
        ))}
      </section>

      <section className="grid gap-4 xl:grid-cols-[1.5fr_1fr]">
        <SectionCard
          eyebrow="Architecture"
          title="Initial product shell"
          description="The repository is organized for long-term domain growth, versioned APIs, PostgreSQL-backed services, and a dashboard-style user experience rather than a one-off demo."
        >
          <div className="grid gap-3 md:grid-cols-2">
            {futureDomains.map((domain) => (
              <div
                key={domain}
                className="rounded-2xl border border-white/10 bg-white/5 px-4 py-3 text-sm text-slate-200"
              >
                {domain}
              </div>
            ))}
          </div>
        </SectionCard>

        <SectionCard
          eyebrow="Runtime"
          title="Environment-aware connectivity"
          description="The frontend is already configured to talk to the backend through an environment-driven base URL so the deployment topology can change without rewriting application code."
        >
          <div className="rounded-2xl border border-sky-400/20 bg-sky-400/10 p-4 text-sm text-slate-200">
            <div className="mb-2 text-xs uppercase tracking-[0.24em] text-sky-300">API base URL</div>
            <code className="break-all text-slate-50">{apiBaseUrl}</code>
          </div>
          <div className="mt-4 flex flex-wrap gap-3">
            <Link
              href="/projects"
              className="rounded-xl bg-sky-400 px-4 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-300"
            >
              Explore modules
            </Link>
            <Link
              href="http://localhost:8000/docs"
              className="rounded-xl border border-white/15 px-4 py-2 text-sm font-semibold text-slate-100 transition hover:border-white/30 hover:bg-white/5"
            >
              Backend docs
            </Link>
          </div>
        </SectionCard>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <SectionCard
          eyebrow="Operational model"
          title="Built for multi-domain expansion"
          description="Navigation areas already reflect the eventual product surface, giving each future capability a stable place in the information architecture."
        >
          <div className="space-y-3 text-sm text-slate-300">
            {navigationItems
              .filter((item) => item.badge === "Planned")
              .map((item) => (
                <div
                  key={item.href}
                  className="flex items-center justify-between rounded-2xl border border-white/10 px-4 py-3"
                >
                  <span>{item.label}</span>
                  <span className="text-xs uppercase tracking-[0.18em] text-slate-500">Planned</span>
                </div>
              ))}
          </div>
        </SectionCard>

        <SectionCard
          eyebrow="Engineering standards"
          title="Clean defaults for the next build steps"
          description="Typed config, SQLAlchemy session management, Alembic migrations, frontend linting, Prettier, Docker, and Make targets are all in place so future feature work lands on a disciplined base."
        >
          <ul className="space-y-3 text-sm text-slate-300">
            <li className="rounded-2xl border border-white/10 px-4 py-3">Versioned backend routes under `app/api/v1`</li>
            <li className="rounded-2xl border border-white/10 px-4 py-3">Modular services, models, and schemas by domain</li>
            <li className="rounded-2xl border border-white/10 px-4 py-3">Dashboard-ready layout and reusable UI composition</li>
            <li className="rounded-2xl border border-white/10 px-4 py-3">Local full-stack startup through Docker Compose</li>
          </ul>
        </SectionCard>
      </section>
    </AppShell>
  );
}
