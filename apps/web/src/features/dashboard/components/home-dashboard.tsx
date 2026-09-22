"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import type { AuthUser, PlatformStatusResponse, ProjectSummary } from "@platform/shared-types";

import { AppFrame } from "@/components/shell/app-frame";
import { runtimeSignalsFromStatus } from "@/components/ui/runtime-banner";
import { assessRuntime, humanDuration } from "@/lib/runtime-health";
import { Icon, type IconName } from "@/components/ui/icon";
import { cx } from "@/lib/utils";

type HomeDashboardProps = {
  currentUser: AuthUser | null;
  projects: ProjectSummary[];
  status: PlatformStatusResponse | null;
};

function detail(status: PlatformStatusResponse | null, service: string, key: string): number {
  const record = status?.services.find((item) => item.name === service);
  const value = record?.details?.[key];
  return typeof value === "number" ? value : 0;
}

export function HomeDashboard({ currentUser, projects, status }: HomeDashboardProps) {
  // Time of day is resolved after mount: the server's clock and the viewer's can
  // sit on opposite sides of a boundary, which would be a hydration mismatch.
  const [greeting, setGreeting] = useState("Welcome back");
  useEffect(() => setGreeting(timeOfDayGreeting()), []);

  const datasetCount = detail(status, "service-datasets", "dataset_count");
  const projectCount = detail(status, "service-projects", "project_count");
  const connectionCount = detail(status, "service-extraction", "connection_count");
  const jobCount = detail(status, "service-extraction", "job_count");
  const ruleCount = detail(status, "service-quality", "rule_count");
  const failingRules = detail(status, "service-quality", "rules_currently_failing");
  const openDrift = detail(status, "service-quality", "unacknowledged_drift_events");
  const breakingDrift = detail(status, "service-quality", "breaking_drift_events");

  const attention = failingRules + openDrift;
  const healthy = status?.status === "healthy";
  const firstProject = projects[0];

  // Background work: the one card that says whether queued work is moving.
  const runtime = status ? assessRuntime(runtimeSignalsFromStatus(status)) : null;
  const runtimeSignals = status ? runtimeSignalsFromStatus(status) : null;

  // Health, honestly ordered: whatever is not healthy comes first and is
  // never hidden by the display cap, and a degraded module says why.
  const orderedServices = [...(status?.services ?? [])].sort((a, b) =>
    (a.status === "healthy" ? 1 : 0) - (b.status === "healthy" ? 1 : 0),
  );
  const degradedServices = orderedServices.filter((s) => s.status !== "healthy");
  const healthLabel = healthy
    ? "All systems healthy"
    : `${degradedServices.length} module${degradedServices.length === 1 ? "" : "s"} degraded`;
  const degradedReason = (service: { name: string; details?: Record<string, unknown> }) => {
    const d = (service.details ?? {}) as Record<string, unknown>;
    if (typeof d.incidents_open === "number" && d.incidents_open > 0) {
      const critical = typeof d.incidents_critical === "number" ? d.incidents_critical : 0;
      return `${d.incidents_open} open incident${d.incidents_open === 1 ? "" : "s"}` +
        (critical ? ` (${critical} critical)` : "");
    }
    return null;
  };

  return (
    <AppFrame
      currentUser={currentUser}
      crumbs={[{ label: "Home" }]}
      statusItems={[
        { id: "projects", label: "Projects", value: String(projectCount) },
        { id: "datasets", label: "Datasets", value: String(datasetCount) },
        { id: "jobs", label: "Extraction jobs", value: String(jobCount) },
        {
          id: "attention",
          label: "Needs attention",
          value: String(attention),
          tone: attention > 0 ? "warn" : "good",
        },
      ]}
      health={{ label: healthLabel, healthy, href: "/system-status" }}
    >
      <div className="px-6 py-6 lg:px-8">
        <header className="mb-7">
          <h1 className="text-[26px] font-semibold tracking-tight text-ink">
            {greeting}
            {currentUser ? `, ${currentUser.username}` : ""}
          </h1>
          <p className="mt-2 text-[13px] text-ink-3">
            Here is the current state of your data platform.
          </p>
        </header>

        <section className="mb-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <Kpi
            icon="grid"
            label="Projects"
            value={projectCount}
            caption={`${datasetCount} dataset${datasetCount === 1 ? "" : "s"} total`}
            href="/projects"
          />
          <Kpi
            icon="database"
            label="Source connections"
            value={connectionCount}
            caption={`${jobCount} extraction job${jobCount === 1 ? "" : "s"}`}
            href={firstProject ? `/projects/${firstProject.id}/extraction` : "/projects"}
          />
          <Kpi
            icon="shield"
            label="Quality rules"
            value={ruleCount}
            caption={failingRules > 0 ? `${failingRules} currently failing` : "All passing"}
            tone={failingRules > 0 ? "warn" : "good"}
            href={firstProject ? `/projects/${firstProject.id}/data-quality` : "/projects"}
          />
          <Kpi
            icon="drift"
            label="Open schema drift"
            value={openDrift}
            caption={breakingDrift > 0 ? `${breakingDrift} breaking` : "Nothing breaking"}
            tone={breakingDrift > 0 ? "bad" : openDrift > 0 ? "warn" : "good"}
            href={firstProject ? `/projects/${firstProject.id}/schema-drift` : "/projects"}
          />
        </section>

        <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
          <section className="rounded-2xl border border-line bg-[color:var(--panel)]">
            <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
              <h2 className="text-[14px] font-semibold text-ink">Your projects</h2>
              <Link
                href="/projects"
                className="flex items-center gap-1 text-[12px] text-ink-3 transition hover:text-ink"
              >
                View all
                <Icon name="chevronRight" size={12} />
              </Link>
            </div>
            <div className="p-3">
              {projects.length === 0 ? (
                <div className="px-3 py-10 text-center">
                  <Icon name="grid" size={24} className="mx-auto text-muted" />
                  <p className="mt-3 text-[13px] text-ink-3">No projects yet.</p>
                  <p className="mt-1 text-[12px] text-muted">
                    Create one to start connecting sources and building pipelines.
                  </p>
                  <Link
                    href="/projects"
                    className="mt-4 inline-flex items-center gap-1.5 rounded-lg bg-[color:var(--accent)] px-3 py-2 text-[12px] font-medium text-accent-ink transition hover:brightness-110"
                  >
                    <Icon name="plus" size={13} />
                    New project
                  </Link>
                </div>
              ) : (
                <ul className="space-y-1">
                  {projects.slice(0, 6).map((project) => (
                    <li key={project.id}>
                      {/*
                        The whole row opens the project, but the quick actions are
                        separate destinations. Nesting anchors is invalid HTML, so
                        the row link is stretched behind the content instead.
                      */}
                      <div className="group relative flex items-center gap-3 rounded-xl px-3 py-3 transition duration-[var(--duration-fast)] hover:bg-surface">
                        <Link
                          href={`/projects/${project.id}`}
                          className="absolute inset-0 z-0 rounded-xl"
                          aria-label={`Open ${project.name}`}
                        />
                        <span className="pointer-events-none flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-line bg-surface text-ink-3 transition group-hover:border-[color:var(--accent-soft)] group-hover:text-[color:var(--accent-muted)]">
                          <Icon name="grid" size={16} />
                        </span>
                        <span className="pointer-events-none min-w-0 flex-1">
                          <span className="block truncate text-[13px] font-medium text-ink">
                            {project.name}
                          </span>
                          <span className="block truncate text-[11px] text-muted">
                            {project.description || "No description"}
                          </span>
                        </span>
                        <span className="relative z-10 hidden shrink-0 items-center gap-1.5 sm:flex">
                          <QuickLink
                            href={`/projects/${project.id}/studio`}
                            icon="transform"
                            label="Open Studio"
                          />
                          <QuickLink
                            href={`/projects/${project.id}/extraction`}
                            icon="database"
                            label="Open sources"
                          />
                        </span>
                        <Icon
                          name="chevronRight"
                          size={14}
                          className="pointer-events-none shrink-0 text-muted transition group-hover:text-ink-3"
                        />
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </section>

          <div className="space-y-5">
            <section className="rounded-2xl border border-line bg-[color:var(--panel)] p-5">
              <h2 className="text-[14px] font-semibold text-ink">Background work</h2>
              {runtimeSignals ? (
                <>
                  <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                    {[
                      { label: "Queued", value: runtimeSignals.queued },
                      { label: "Running", value: runtimeSignals.running },
                      { label: "Due now", value: runtimeSignals.dueNow },
                    ].map((stat) => (
                      <div key={stat.label} className="rounded-xl bg-surface-2 px-2 py-2.5">
                        <div className="tabular text-[18px] font-semibold text-ink">{stat.value}</div>
                        <div className="text-[10.5px] uppercase tracking-[0.12em] text-muted">{stat.label}</div>
                      </div>
                    ))}
                  </div>
                  {runtime?.level === "stalled" ? (
                    <p className="mt-3 rounded-lg border border-danger-line bg-danger-soft px-3 py-2 text-[12px] leading-5 text-danger">
                      Nothing is picking it up — the oldest run has waited{" "}
                      {humanDuration(runtime.oldestWaitMs)}. Start the worker (see System status).
                    </p>
                  ) : (
                    <p className="mt-3 text-[11.5px] text-muted">
                      {runtimeSignals.queued + runtimeSignals.running + runtimeSignals.dueNow === 0
                        ? "Nothing waiting. Scheduled work will appear here."
                        : "Work is moving normally."}
                    </p>
                  )}
                </>
              ) : (
                <p className="mt-3 text-[11.5px] text-muted">Status unavailable.</p>
              )}
            </section>

            <section className="rounded-2xl border border-line bg-[color:var(--panel)]">
              <div className="border-b border-line px-5 py-3.5">
                <h2 className="text-[14px] font-semibold text-ink">Platform health</h2>
              </div>
              <div className="space-y-1 p-3">
                {orderedServices.slice(0, Math.max(8, degradedServices.length)).map((service) => (
                  <div
                    key={service.name}
                    className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5"
                  >
                    <span
                      className={cx(
                        "h-1.5 w-1.5 shrink-0 rounded-full",
                        service.status === "healthy" ? "bg-success" : "bg-danger",
                      )}
                    />
                    <span className="min-w-0 flex-1 truncate text-[12px] text-ink-2">
                      {service.name.replace("service-", "")}
                    </span>
                    <span
                      className={cx(
                        "shrink-0 text-[11px]",
                        service.status === "healthy" ? "text-success" : "text-danger",
                      )}
                    >
                      {service.status === "healthy"
                        ? "healthy"
                        : degradedReason(service) ?? service.status}
                    </span>
                  </div>
                ))}
                {!status ? (
                  <p className="px-2.5 py-6 text-center text-[12px] text-muted">
                    Status unavailable.
                  </p>
                ) : null}
              </div>
              <div className="border-t border-line px-5 py-2.5">
                <Link
                  href="/system-status"
                  className="flex items-center gap-1 text-[12px] text-ink-3 transition hover:text-ink"
                >
                  Full system status
                  <Icon name="chevronRight" size={12} />
                </Link>
              </div>
            </section>

            <section className="rounded-2xl border border-line bg-[color:var(--panel)] p-5">
              <h2 className="text-[14px] font-semibold text-ink">Get started</h2>
              <p className="mt-1 text-[12px] leading-5 text-muted">
                The usual path through the platform.
              </p>
              <ol className="mt-4 space-y-2.5">
                {[
                  { step: "Connect a source database or upload a file", icon: "database" as IconName },
                  { step: "Shape the data in Studio", icon: "transform" as IconName },
                  { step: "Add quality rules so bad data cannot pass", icon: "shield" as IconName },
                  { step: "Schedule it and publish downstream", icon: "clock" as IconName },
                ].map((item, index) => {
                  const base = firstProject ? `/projects/${firstProject.id}` : "/projects";
                  const hrefs = firstProject
                    ? [base, `${base}/studio`, `${base}/data-quality`, `${base}/schedules`]
                    : ["/projects", "/projects", "/projects", "/projects"];
                  return (
                    <li key={item.step}>
                      <Link
                        href={hrefs[index]}
                        className="group flex items-start gap-2.5 rounded-lg px-1 py-0.5 transition hover:bg-surface-2"
                      >
                        <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md bg-surface-2 text-[10px] font-semibold text-ink-3">
                          {index + 1}
                        </span>
                        <span className="text-[12px] leading-5 text-ink-2 group-hover:text-ink">
                          {item.step}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ol>
            </section>
          </div>
        </div>
      </div>
    </AppFrame>
  );
}

function timeOfDayGreeting(): string {
  const hour = new Date().getHours();
  if (hour < 12) return "Good morning";
  if (hour < 18) return "Good afternoon";
  return "Good evening";
}

function QuickLink({ href, icon, label }: { href: string; icon: IconName; label: string }) {
  return (
    <Link
      href={href}
      title={label}
      aria-label={label}
      className="flex h-7 w-7 items-center justify-center rounded-lg border border-line bg-[color:var(--panel)] text-muted transition hover:border-[color:var(--accent-soft)] hover:bg-[color:var(--accent-faint)] hover:text-ink"
    >
      <Icon name={icon} size={13} />
    </Link>
  );
}

function Kpi({
  icon,
  label,
  value,
  caption,
  tone = "neutral",
  href,
}: {
  icon: IconName;
  label: string;
  value: number;
  caption: string;
  tone?: "neutral" | "good" | "warn" | "bad";
  href: string;
}) {
  const toneText = {
    neutral: "text-muted",
    good: "text-success",
    warn: "text-warning",
    bad: "text-danger",
  }[tone];

  return (
    <Link
      href={href}
      className="group rounded-2xl border border-line bg-[color:var(--panel)] p-4 transition duration-[var(--duration-base)] ease-[var(--ease-out)] hover:border-line-strong hover:bg-surface"
    >
      <div className="flex items-center justify-between">
        <span className="text-[11px] uppercase tracking-[0.16em] text-muted">{label}</span>
        <Icon
          name={icon}
          size={15}
          className="text-muted transition group-hover:text-[color:var(--accent-muted)]"
        />
      </div>
      <div className="tabular mt-3 text-[30px] font-semibold leading-none tracking-tight text-ink">
        {value.toLocaleString()}
      </div>
      <div className={cx("mt-2 text-[11px]", toneText)}>{caption}</div>
    </Link>
  );
}
