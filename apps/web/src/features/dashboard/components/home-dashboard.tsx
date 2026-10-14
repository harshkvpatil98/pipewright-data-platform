"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type {
  AuthUser,
  PlatformStatusResponse,
  ProjectSummary,
} from "@platform/shared-types";

import { AppFrame } from "@/components/shell/app-frame";
import { runtimeSignalsFromStatus } from "@/components/ui/runtime-banner";
import { assessRuntime, humanDuration } from "@/lib/runtime-health";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { serviceLabel } from "@/lib/service-labels";
import { cx } from "@/lib/utils";
import { Badge, Icon, type IconName, useToast } from "@platform/shared-ui";
import { formatCount } from "@/lib/format";

type HomeDashboardProps = {
  currentUser: AuthUser | null;
  projects: ProjectSummary[];
  status: PlatformStatusResponse | null;
};

const WORKER_LABELS: Record<string, string> = {
  "workflow-worker": "Worker",
  "schedule-ticker": "Ticker",
};

function detail(
  status: PlatformStatusResponse | null,
  service: string,
  key: string,
): number {
  const record = status?.services.find((item) => item.name === service);
  const value = record?.details?.[key];
  return typeof value === "number" ? value : 0;
}

export function HomeDashboard({
  currentUser,
  projects,
  status,
}: HomeDashboardProps) {
  // Time of day is resolved after mount: the server's clock and the viewer's can
  // sit on opposite sides of a boundary, which would be a hydration mismatch.
  const [greeting, setGreeting] = useState("Welcome back");
  useEffect(() => setGreeting(timeOfDayGreeting()), []);

  const datasetCount = detail(status, "service-datasets", "dataset_count");
  const projectCount = detail(status, "service-projects", "project_count");
  const connectionCount = detail(
    status,
    "service-extraction",
    "connection_count",
  );
  const jobCount = detail(status, "service-extraction", "job_count");
  const ruleCount = detail(status, "service-quality", "rule_count");
  const failingRules = detail(
    status,
    "service-quality",
    "rules_currently_failing",
  );
  const openDrift = detail(
    status,
    "service-quality",
    "unacknowledged_drift_events",
  );
  const breakingDrift = detail(
    status,
    "service-quality",
    "breaking_drift_events",
  );

  const attention = failingRules + openDrift;
  const healthy = status?.status === "healthy";
  const firstProject = projects[0];
  const router = useRouter();
  const toast = useToast();
  const [seeding, setSeeding] = useState(false);

  // Mirror the project checklist on Home: tick the get-started steps that the
  // first project has actually completed, so this list is a live map of
  // progress rather than a static brochure. dataset_count is already known;
  // the other three counts are fetched once.
  const [firstProgress, setFirstProgress] = useState({
    data: (firstProject?.dataset_count ?? 0) > 0,
    shape: false,
    guard: false,
    schedule: false,
  });
  useEffect(() => {
    if (!firstProject) return;
    let cancelled = false;
    const count = (path: string) =>
      apiFetch<{ items?: unknown[] }>(path)
        .then((r) => (Array.isArray(r.items) ? r.items.length : 0))
        .catch(() => 0);
    const base = `/projects/${firstProject.id}`;
    void Promise.all([
      count(`${base}/pipelines`),
      count(`${base}/data-quality/rules`),
      count(`${base}/schedules`),
    ]).then(([pipelines, rules, schedules]) => {
      if (cancelled) return;
      setFirstProgress({
        data: firstProject.dataset_count > 0,
        shape: pipelines > 0,
        guard: rules > 0,
        schedule: schedules > 0,
      });
    });
    return () => {
      cancelled = true;
    };
  }, [firstProject]);

  const createDemo = async () => {
    setSeeding(true);
    try {
      const demo = await apiFetch<{ id: string }>("/projects/demo", {
        method: "POST",
      });
      toast.success(
        "Demo project created",
        "A worked example with data, a recipe, a check and a schedule.",
      );
      router.push(`/projects/${demo.id}`);
    } catch (caught) {
      toast.error("Could not create the demo", extractErrorMessage(caught));
      setSeeding(false);
    }
  };

  // Background work: the one card that says whether queued work is moving.
  const runtime = status
    ? assessRuntime(runtimeSignalsFromStatus(status))
    : null;
  const runtimeSignals = status ? runtimeSignalsFromStatus(status) : null;

  // Health, honestly ordered: whatever is not healthy comes first and is
  // never hidden by the display cap, and a degraded module says why.
  const orderedServices = [...(status?.services ?? [])].sort(
    (a, b) =>
      (a.status === "healthy" ? 1 : 0) - (b.status === "healthy" ? 1 : 0),
  );
  const degradedServices = orderedServices.filter(
    (s) => s.status !== "healthy",
  );
  const healthLabel = healthy
    ? "Everything is working"
    : `${degradedServices.length} part${degradedServices.length === 1 ? "" : "s"} need${degradedServices.length === 1 ? "s" : ""} attention`;
  const degradedReason = (service: {
    name: string;
    details?: Record<string, unknown>;
  }) => {
    const d = (service.details ?? {}) as Record<string, unknown>;
    if (typeof d.incidents_open === "number" && d.incidents_open > 0) {
      const critical =
        typeof d.incidents_critical === "number" ? d.incidents_critical : 0;
      return (
        `${d.incidents_open} open incident${d.incidents_open === 1 ? "" : "s"}` +
        (critical ? ` (${critical} critical)` : "")
      );
    }
    return null;
  };

  return (
    <AppFrame
      currentUser={currentUser}
      statusItems={[
        { id: "projects", label: "Projects", value: String(projectCount) },
        { id: "datasets", label: "Datasets", value: String(datasetCount) },
        { id: "jobs", label: "Imports", value: String(jobCount) },
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
          <h1 className="text-ink text-[26px] font-semibold tracking-tight">
            {greeting}
            {currentUser
              ? `, ${currentUser.display_name || currentUser.username}`
              : ""}
          </h1>
          <p className="text-ink-3 mt-2 text-[14px]">
            What needs attention across your projects, and where you left off.
          </p>
        </header>

        {projects.length === 0 ? (
          <WelcomeHero
            seeding={seeding}
            onCreateDemo={() => void createDemo()}
          />
        ) : (
          <>
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
                label="Databases connected"
                value={connectionCount}
                caption={`${jobCount} import${jobCount === 1 ? "" : "s"} set up`}
                href={
                  firstProject
                    ? `/projects/${firstProject.id}/sources`
                    : "/projects"
                }
              />
              <Kpi
                icon="shield"
                label="Checks"
                value={ruleCount}
                caption={
                  failingRules > 0
                    ? `${failingRules} currently failing`
                    : "All passing"
                }
                tone={failingRules > 0 ? "warn" : "good"}
                href={
                  firstProject
                    ? `/projects/${firstProject.id}/checks`
                    : "/projects"
                }
              />
              <Kpi
                icon="drift"
                label="Schema changes to review"
                value={openDrift}
                caption={
                  breakingDrift > 0
                    ? `${breakingDrift} breaking`
                    : "Nothing breaking"
                }
                tone={
                  breakingDrift > 0 ? "bad" : openDrift > 0 ? "warn" : "good"
                }
                href={
                  firstProject
                    ? `/projects/${firstProject.id}/schema-drift`
                    : "/projects"
                }
              />
            </section>

            <div className="grid gap-5 lg:grid-cols-[1.5fr_1fr]">
              <section className="border-line rounded-2xl border bg-[color:var(--panel)]">
                <div className="border-line flex items-center justify-between border-b px-5 py-3.5">
                  <h2 className="text-ink text-[14px] font-semibold">
                    Your projects
                  </h2>
                  <Link
                    href="/projects"
                    className="text-ink-3 hover:text-ink flex items-center gap-1 text-[12px] transition"
                  >
                    View all
                    <Icon name="chevronRight" size={12} />
                  </Link>
                </div>
                <div className="p-3">
                  <ul className="space-y-1">
                    {projects.slice(0, 6).map((project) => (
                      <li key={project.id}>
                        {/*
                        The whole row opens the project, but the quick actions are
                        separate destinations. Nesting anchors is invalid HTML, so
                        the row link is stretched behind the content instead.
                      */}
                        <div className="group hover:bg-surface relative flex items-center gap-3 rounded-xl px-3 py-3 transition duration-[var(--duration-fast)]">
                          <Link
                            href={`/projects/${project.id}`}
                            className="absolute inset-0 z-0 rounded-xl"
                            aria-label={`Open ${project.name}`}
                          />
                          <span className="border-line bg-surface text-ink-3 pointer-events-none flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border transition group-hover:border-[color:var(--accent-soft)] group-hover:text-[color:var(--accent-muted)]">
                            <Icon name="grid" size={16} />
                          </span>
                          <span className="pointer-events-none min-w-0 flex-1">
                            <span className="text-ink block truncate text-[13px] font-medium">
                              {project.name}
                            </span>
                            <span className="text-muted block truncate text-[12px]">
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
                              href={`/projects/${project.id}/sources`}
                              icon="database"
                              label="Open sources"
                            />
                          </span>
                          <Icon
                            name="chevronRight"
                            size={14}
                            className="text-muted group-hover:text-ink-3 pointer-events-none shrink-0 transition"
                          />
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              </section>

              <div className="space-y-5">
                <section className="border-line rounded-2xl border bg-[color:var(--panel)] p-5">
                  <h2 className="text-ink text-[14px] font-semibold">
                    Background work
                  </h2>
                  {runtimeSignals ? (
                    <>
                      <div className="mt-3 grid grid-cols-3 gap-2 text-center">
                        {[
                          { label: "Queued", value: runtimeSignals.queued },
                          { label: "Running", value: runtimeSignals.running },
                          { label: "Due now", value: runtimeSignals.dueNow },
                        ].map((stat) => (
                          <div
                            key={stat.label}
                            className="bg-surface-2 rounded-xl px-2 py-2.5"
                          >
                            <div className="tabular text-ink text-[18px] font-semibold">
                              {stat.value}
                            </div>
                            <div className="text-muted text-[12px]">
                              {stat.label}
                            </div>
                          </div>
                        ))}
                      </div>
                      {(status?.runtime?.components?.length ?? 0) > 0 ? (
                        <div className="mt-3 flex flex-wrap gap-1.5">
                          {status?.runtime?.components.map((component) => (
                            <Badge
                              key={`${component.component}:${component.host ?? "-"}`}
                              tone={component.healthy ? "success" : "danger"}
                              title={
                                component.healthy
                                  ? "Checking in normally"
                                  : "Not checking in, so this part is not running"
                              }
                            >
                              {WORKER_LABELS[component.component] ?? component.component}
                            </Badge>
                          ))}
                        </div>
                      ) : null}
                      {runtime?.level === "stalled" ? (
                        <p className="border-danger-line bg-danger-soft text-danger mt-3 rounded-lg border px-3 py-2 text-[12px] leading-5">
                          Nothing is picking it up: the oldest has waited{" "}
                          {humanDuration(runtime.oldestWaitMs)}. Whoever runs
                          Pipewright needs to start its background worker.
                        </p>
                      ) : (
                        <p className="text-muted mt-3 text-[12px]">
                          {runtimeSignals.queued +
                            runtimeSignals.running +
                            runtimeSignals.dueNow ===
                          0
                            ? "Nothing waiting. Scheduled work will appear here."
                            : "Work is moving normally."}
                        </p>
                      )}
                    </>
                  ) : (
                    <p className="text-muted mt-3 text-[12px]">
                      Status unavailable.
                    </p>
                  )}
                </section>

                <section className="border-line rounded-2xl border bg-[color:var(--panel)]">
                  <div className="border-line border-b px-5 py-3.5">
                    <h2 className="text-ink text-[14px] font-semibold">
                      Platform health
                    </h2>
                  </div>
                  <div className="space-y-1 p-3">
                    {orderedServices
                      .slice(0, Math.max(8, degradedServices.length))
                      .map((service) => (
                        <div
                          key={service.name}
                          className="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5"
                        >
                          <span
                            className={cx(
                              "h-1.5 w-1.5 shrink-0 rounded-full",
                              service.status === "healthy"
                                ? "bg-success"
                                : "bg-danger",
                            )}
                          />
                          <span className="text-ink-2 min-w-0 flex-1 truncate text-[13px]">
                            {serviceLabel(service.name)}
                          </span>
                          <span
                            className={cx(
                              "shrink-0 text-[12px]",
                              service.status === "healthy"
                                ? "text-success"
                                : "text-danger",
                            )}
                          >
                            {service.status === "healthy"
                              ? "Working"
                              : (degradedReason(service) ?? service.status)}
                          </span>
                        </div>
                      ))}
                    {!status ? (
                      <p className="text-muted px-2.5 py-6 text-center text-[12px]">
                        Status unavailable.
                      </p>
                    ) : null}
                  </div>
                  <div className="border-line border-t px-5 py-2.5">
                    <Link
                      href="/system-status"
                      className="text-ink-3 hover:text-ink flex items-center gap-1 text-[12px] transition"
                    >
                      Full system status
                      <Icon name="chevronRight" size={12} />
                    </Link>
                  </div>
                </section>

                <section className="border-line rounded-2xl border bg-[color:var(--panel)] p-5">
                  <h2 className="text-ink text-[14px] font-semibold">
                    Get started
                  </h2>
                  <p className="text-muted mt-1 text-[12px] leading-5">
                    The usual path through the platform.
                  </p>
                  <ol className="mt-4 space-y-2.5">
                    {[
                      {
                        step: "Upload a file or connect a database",
                        done: firstProgress.data,
                      },
                      { step: "Clean it in Studio", done: firstProgress.shape },
                      {
                        step: "Add a check so bad rows are caught",
                        done: firstProgress.guard,
                      },
                      {
                        step: "Put it on a schedule",
                        done: firstProgress.schedule,
                      },
                    ].map((item, index) => {
                      const base = firstProject
                        ? `/projects/${firstProject.id}`
                        : "/projects";
                      const hrefs = firstProject
                        ? [
                            base,
                            `${base}/studio`,
                            `${base}/checks`,
                            `${base}/schedules`,
                          ]
                        : ["/projects", "/projects", "/projects", "/projects"];
                      return (
                        <li key={item.step}>
                          <Link
                            href={hrefs[index]}
                            className="group hover:bg-surface-2 flex items-start gap-2.5 rounded-lg px-1 py-0.5 transition"
                          >
                            <span
                              className={cx(
                                "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md text-[12px] font-semibold",
                                item.done
                                  ? "bg-success text-accent-ink"
                                  : "bg-surface-2 text-ink-3",
                              )}
                            >
                              {item.done ? (
                                <Icon name="check" size={11} />
                              ) : (
                                index + 1
                              )}
                            </span>
                            <span
                              className={cx(
                                "group-hover:text-ink text-[12px] leading-5",
                                item.done
                                  ? "text-ink-3 decoration-ink-4 line-through"
                                  : "text-ink-2",
                              )}
                            >
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
          </>
        )}
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

function QuickLink({
  href,
  icon,
  label,
}: {
  href: string;
  icon: IconName;
  label: string;
}) {
  return (
    <Link
      href={href}
      title={label}
      aria-label={label}
      className="border-line text-muted hover:text-ink flex h-7 w-7 items-center justify-center rounded-lg border bg-[color:var(--panel)] transition hover:border-[color:var(--accent-soft)] hover:bg-[color:var(--accent-faint)]"
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
      className="group border-line hover:border-line-strong hover:bg-surface rounded-2xl border bg-[color:var(--panel)] p-4 transition duration-[var(--duration-base)] ease-[var(--ease-out)]"
    >
      <div className="flex items-center justify-between">
        <span className="text-ink-3 text-[13px] font-medium">{label}</span>
        <Icon
          name={icon}
          size={15}
          className="text-muted transition group-hover:text-[color:var(--accent-muted)]"
        />
      </div>
      <div className="tabular text-ink mt-3 text-[30px] leading-none font-semibold tracking-tight">
        {formatCount(value)}
      </div>
      <div className={cx("mt-2 text-[12px]", toneText)}>{caption}</div>
    </Link>
  );
}

/**
 * What a brand-new workspace sees instead of four zero tiles: the two ways to
 * begin, side by side, and nothing else competing for attention.
 */
function WelcomeHero({
  seeding,
  onCreateDemo,
}: {
  seeding: boolean;
  onCreateDemo: () => void;
}) {
  return (
    <section className="border-line rounded-3xl border bg-[color:var(--panel)] p-6 lg:p-8">
      <h2 className="text-ink text-[20px] font-semibold tracking-tight">
        Start with a project
      </h2>
      <p className="text-ink-3 mt-1.5 max-w-2xl text-[14px] leading-6">
        A project keeps one team&apos;s or one subject&apos;s data together,
        with the recipes, checks and dashboards built from it. Most people start
        with one of these.
      </p>
      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <Link
          href="/projects?new=1"
          className="group rounded-2xl border border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] p-5 transition hover:brightness-105"
        >
          <Icon
            name="plus"
            size={20}
            className="text-[color:var(--accent-muted)]"
          />
          <h3 className="text-ink mt-3 text-[16px] font-semibold">
            Start a new project
          </h3>
          <p className="text-ink-3 mt-1 text-[14px] leading-6">
            Name it, then add your own file, connect a database, or use sample
            data.
          </p>
          <span className="text-ink mt-4 inline-flex items-center gap-1 text-[14px] font-medium">
            New project
            <Icon
              name="arrowRight"
              size={14}
              className="transition group-hover:translate-x-0.5"
            />
          </span>
        </Link>
        <button
          type="button"
          onClick={onCreateDemo}
          disabled={seeding}
          className="group border-line bg-surface hover:border-line-strong rounded-2xl border p-5 text-left transition disabled:opacity-60"
        >
          <Icon
            name="sparkles"
            size={20}
            className="text-[color:var(--accent-muted)]"
          />
          <h3 className="text-ink mt-3 text-[16px] font-semibold">
            Explore a finished example
          </h3>
          <p className="text-ink-3 mt-1 text-[14px] leading-6">
            A shop&apos;s orders, already cleaned, checked, scheduled and on a
            dashboard. Delete it whenever you like.
          </p>
          <span className="text-ink mt-4 inline-flex items-center gap-1 text-[14px] font-medium">
            {seeding ? "Building the example…" : "Open the example"}
            <Icon
              name="arrowRight"
              size={14}
              className="transition group-hover:translate-x-0.5"
            />
          </span>
        </button>
      </div>
    </section>
  );
}
