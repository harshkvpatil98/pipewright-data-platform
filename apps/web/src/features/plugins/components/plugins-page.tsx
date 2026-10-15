"use client";

import { useState } from "react";

import type { AuthUser, PluginListResponse, PluginStatus } from "@platform/shared-types";
import { Badge, type BadgeTone, EmptyState, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { countOf } from "@/lib/format";
import { cx } from "@/lib/utils";

const STATE: Record<PluginStatus["state"], { label: string; tone: BadgeTone }> = {
  loaded: { label: "Loaded", tone: "success" },
  refused: { label: "Refused", tone: "danger" },
  "not enabled": { label: "Not enabled", tone: "neutral" },
  "not found": { label: "Not found", tone: "warning" },
};

const KIND: Record<string, string> = {
  tool: "Tool",
  function: "Formula function",
  "chart type": "Chart type",
  connector: "Connector",
};

type Props = { currentUser: AuthUser; listed: PluginListResponse | null; forbidden: boolean };

/**
 * What plugins are installed on this server, what each adds, and the checks
 * each passed or failed (Phase 23, X1). Loading is decided by the server's
 * settings, so this page reports and explains; it changes nothing.
 */
export function PluginsPageView({ currentUser, listed, forbidden }: Props) {
  const subtitle = "Tools, formula functions, chart types and connectors from plugins, checked like Pipewright's own.";
  if (forbidden || !listed) {
    return (
      <AppShell currentUser={currentUser} title="Plugins" subtitle={subtitle}>
        <EmptyState
          size="compact"
          title="Admins only"
          description="This page shows what is loaded into the server, so only platform admins can see it."
        />
      </AppShell>
    );
  }
  const loaded = listed.items.filter((item) => item.state === "loaded").length;
  return (
    <AppShell currentUser={currentUser} title="Plugins" subtitle={subtitle}>
      <SectionPanel
        title="How plugins load"
        description={`This server speaks plugin SDK ${listed.sdk}. ${countOf(loaded, "plugin")} loaded.`}
      >
        <p className="text-[13px] leading-6 text-ink-2">
          A plugin loads when the server&apos;s <code className="font-mono text-[12.5px]">PLUGINS_ENABLED</code>{" "}
          setting names it, after the gateway and the worker restart. Before anything of it is used, it passes the
          checks Pipewright&apos;s own tools, functions, charts and connectors pass; one failure refuses the whole
          plugin, with the reason below. A plugin installed and not named is never run.
        </p>
      </SectionPanel>

      <div className="mt-4 space-y-3">
        {listed.items.length === 0 ? (
          <EmptyState
            size="compact"
            title="No plugins installed"
            description="Install a plugin's package where Pipewright runs, or put its folder in PLUGINS_PATH; it is listed here."
          />
        ) : (
          listed.items.map((item) => <PluginCard key={item.name} plugin={item} />)
        )}
      </div>
    </AppShell>
  );
}

function PluginCard({ plugin }: { plugin: PluginStatus }) {
  const [open, setOpen] = useState(plugin.state === "refused");
  const state = STATE[plugin.state];
  const failed = plugin.checks.filter((check) => !check.passed).length;
  return (
    <section className="rounded-2xl border border-line bg-surface p-4" aria-label={`Plugin ${plugin.name}`}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-[16px] font-semibold text-ink">{plugin.name}</h2>
        {plugin.version ? <span className="text-[13px] text-ink-3">{plugin.version}</span> : null}
        <Badge tone={state.tone}>{state.label}</Badge>
        {plugin.publisher ? <span className="text-[13px] text-ink-3">by {plugin.publisher}</span> : null}
      </div>
      {plugin.description ? <p className="mt-1 text-[13px] text-ink-2">{plugin.description}</p> : null}
      {plugin.reason ? (
        <p
          className={cx(
            "mt-2 rounded-lg px-3 py-2 text-[13px]",
            plugin.state === "refused" ? "bg-danger-soft text-danger" : "bg-sunken text-ink-2",
          )}
        >
          {plugin.reason}
        </p>
      ) : null}
      {plugin.source ? <p className="mt-2 text-[12px] text-muted">From {plugin.source}.</p> : null}

      {plugin.contributions.length ? (
        <ul className="mt-3 divide-y divide-line rounded-xl border border-line">
          {plugin.contributions.map((item) => (
            <li key={`${item.kind}-${item.name}`} className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 px-3 py-2">
              <span className="w-32 shrink-0 text-[12.5px] text-ink-3">{KIND[item.kind] ?? item.kind}</span>
              <span className="text-[13px] font-medium text-ink">{item.title}</span>
              <span className="font-mono text-[12px] text-muted">{item.name}</span>
              {item.tier ? <span className="basis-full text-[12px] text-muted sm:basis-auto">{item.tier}</span> : null}
            </li>
          ))}
        </ul>
      ) : null}

      {plugin.checks.length ? (
        <div className="mt-3">
          <button
            type="button"
            onClick={() => setOpen((current) => !current)}
            aria-expanded={open}
            className="text-[13px] text-[color:var(--accent-muted)] hover:underline"
          >
            {open ? "Hide the checks" : "Show the checks"} ({countOf(plugin.checks.length, "check")}
            {failed ? `, ${failed} failed` : ", all passed"})
          </button>
          {open ? (
            <ul className="mt-2 space-y-1">
              {plugin.checks.map((check, index) => (
                <li key={index} className="flex items-start gap-2 text-[12.5px]">
                  <Badge tone={check.passed ? "success" : "danger"}>{check.passed ? "Passed" : "Failed"}</Badge>
                  <span className="text-ink-2">
                    <span className="font-medium text-ink">{check.subject}</span>: {check.name}
                    {check.detail ? <span className="text-danger"> ({check.detail})</span> : null}
                    <span className="text-muted"> · {check.suite}</span>
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
