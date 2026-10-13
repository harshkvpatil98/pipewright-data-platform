"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import type {
  AuthUser,
  ConnectorCapability,
  ConnectorCatalogResponse,
  ConnectorHealth,
  ConnectorSpec,
  FormatCatalogResponse,
  SupportContact,
} from "@platform/shared-types";
import {
  Badge,
  Icon,
  SectionPanel,
  StatTile,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { countOf } from "@/lib/format";
import { tierTone } from "@/lib/labels";
import { cx } from "@/lib/utils";

type ConnectorCatalogPageProps = {
  currentUser: AuthUser;
  initial: ConnectorCatalogResponse;
};

const CATEGORY_LABEL: Record<string, string> = {
  database: "Databases",
  warehouse: "Warehouses",
  api: "APIs",
  storage: "Object storage",
  saas: "Apps",
  nosql: "Document stores",
  file: "Files",
  timeseries: "Time series",
  streaming: "Streams",
  lakehouse: "Lakehouse",
};

const CAPABILITY_LABEL: Partial<Record<ConnectorCapability, string>> = {
  discover: "Lists what it holds",
  schema: "Knows its columns",
  incremental: "Reads only what changed",
  write: "Can be written to",
};

/**
 * Every kind of source Pipewright can connect to (A6, W4). The tested ones
 * are the catalogue; the rest sit under "Available on request" with how
 * validation works, so a buyer reads what testing means rather than a wall
 * of warnings. Tiers stay exactly as honest as before: nothing untested is
 * shown as tested, and every connector still carries its own tier.
 */
export function ConnectorCatalogPageView({ currentUser, initial }: ConnectorCatalogPageProps) {
  const [category, setCategory] = useState<string>("all");
  const [query, setQuery] = useState("");
  const [showOnRequest, setShowOnRequest] = useState(false);
  const [formats, setFormats] = useState<FormatCatalogResponse | null>(null);
  const [health, setHealth] = useState<ConnectorHealth | null>(null);
  const [support, setSupport] = useState<SupportContact | null>(null);

  useEffect(() => {
    apiFetch<FormatCatalogResponse>("/connectors/formats").then(setFormats).catch(() => setFormats(null));
    apiFetch<ConnectorHealth>("/connectors/health").then(setHealth).catch(() => setHealth(null));
    apiFetch<SupportContact>("/status/support").then(setSupport).catch(() => setSupport(null));
  }, []);

  const matches = useMemo(() => {
    const words = query.trim().toLowerCase();
    return initial.items
      .filter((spec) => category === "all" || spec.category === category)
      .filter(
        (spec) =>
          !words ||
          spec.label.toLowerCase().includes(words) ||
          spec.description.toLowerCase().includes(words) ||
          (CATEGORY_LABEL[spec.category] ?? spec.category).toLowerCase().includes(words),
      )
      .sort((a, b) => a.label.localeCompare(b.label));
  }, [initial.items, category, query]);

  const tested = matches.filter((spec) => spec.verified);
  const onRequest = matches.filter((spec) => !spec.verified);
  const testedTotal = initial.items.filter((spec) => spec.verified).length;
  const onRequestTotal = initial.items.length - testedTotal;
  const needPackage = initial.items.filter((spec) => !spec.available).length;
  const categories = [...new Set(initial.items.map((spec) => spec.category))].sort((a, b) =>
    (CATEGORY_LABEL[a] ?? a).localeCompare(CATEGORY_LABEL[b] ?? b),
  );
  // A search reaches into the connectors on request too: someone looking
  // for one by name should find it, not be told it is hidden.
  const onRequestOpen = showOnRequest || query.trim().length > 0;

  return (
    <AppShell
      currentUser={currentUser}
      title="Connectors"
      subtitle="Every kind of source Pipewright can connect to, and how each is tested."
    >
      <div className="grid gap-3 sm:grid-cols-3">
        <StatTile label="Tested" value={String(testedTotal)} tone="success" caption="Run in Pipewright's tests on every change" />
        <StatTile label="Available on request" value={String(onRequestTotal)} caption="Written from the vendor's documentation" />
        <StatTile
          label="Need a package on this server"
          value={String(needPackage)}
          caption={needPackage ? "Listed at the end of this page" : "Everything is installed"}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex h-10 w-full max-w-sm items-center gap-2 rounded-lg border border-line bg-sunken px-3 focus-within:border-[color:var(--accent)]">
          <Icon name="search" size={15} className="text-ink-3" />
          <span className="sr-only">Find a connector</span>
          <input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Find a connector, for example “Salesforce”"
            className="min-w-0 flex-1 bg-transparent text-[14px] text-ink outline-none placeholder:text-ink-3"
          />
        </label>
        <div className="flex flex-wrap gap-1.5">
          <FilterChip active={category === "all"} onClick={() => setCategory("all")}>
            All
          </FilterChip>
          {categories.map((key) => (
            <FilterChip key={key} active={category === key} onClick={() => setCategory(key)}>
              {CATEGORY_LABEL[key] ?? key}
            </FilterChip>
          ))}
        </div>
      </div>

      <SectionPanel
        title={`Tested (${tested.length})`}
        description="Tested on every change to Pipewright: databases against a real server, apps and APIs against a test server built from the vendor's documentation."
      >
        {tested.length ? (
          <ConnectorGrid specs={tested} />
        ) : (
          <p className="text-[14px] text-ink-3">No tested connector matches. Look under Available on request below.</p>
        )}
      </SectionPanel>

      <SectionPanel
        title={`Available on request (${onRequest.length})`}
        description="Written from each vendor's documentation, and not yet run in Pipewright's tests. Each can be used now; it says so wherever it appears."
        actions={
          query.trim() ? null : (
            <button
              type="button"
              onClick={() => setShowOnRequest((open) => !open)}
              aria-expanded={onRequestOpen}
              className="inline-flex h-9 items-center gap-1.5 rounded-lg border border-line px-3 text-[13.5px] text-ink transition hover:bg-surface-2"
            >
              <Icon name={onRequestOpen ? "chevronUp" : "chevronDown"} size={14} />
              {onRequestOpen ? "Hide them" : `Show all ${onRequest.length}`}
            </button>
          )
        }
      >
        <ol className="grid gap-3 md:grid-cols-3">
          <Step number={1} title="Ask for it">
            {support?.href ? (
              <>
                Tell{" "}
                <a href={support.href} target="_blank" rel="noreferrer" className="text-accent underline">
                  {support.contact}
                </a>{" "}
                which connector you need and what you want from it.
              </>
            ) : (
              <>
                Tell your administrator, or{" "}
                <Link href="/help#getting-help" className="text-accent underline">
                  support
                </Link>
                , which connector you need and what you want from it.
              </>
            )}
          </Step>
          <Step number={2} title="It is tested">
            A test is written from the vendor&apos;s documentation and runs on every change to Pipewright. With a real
            account, it runs live too.
          </Step>
          <Step number={3} title="It shows as tested">
            Once it passes, it moves to Tested here and wherever a source is chosen, and stays checked from then on.
          </Step>
        </ol>
        {onRequestOpen ? (
          <div className="mt-5">
            {onRequest.length ? (
              <ConnectorGrid specs={onRequest} />
            ) : (
              <p className="text-[14px] text-ink-3">No connector on request matches.</p>
            )}
          </div>
        ) : null}
      </SectionPanel>

      {health && health.missing_packages.length > 0 ? (
        <SectionPanel
          title="Packages this server is missing"
          description="Some connectors need a driver installed on the server. Whoever runs Pipewright can add these; each unlocks the connectors shown."
        >
          <ul className="flex flex-wrap gap-2">
            {health.missing_packages.map((entry) => (
              <li key={entry.package} className="rounded-lg border border-line px-2.5 py-1.5 text-[13px] text-ink-3">
                <code className="font-mono text-ink">{entry.package}</code> · {countOf(entry.unlocks, "connector")}
              </li>
            ))}
          </ul>
        </SectionPanel>
      ) : null}

      {formats ? (
        <SectionPanel title="File formats" description="Formats that keep column types hold on to what a CSV would lose.">
          <Table minWidth={560}>
            <TableHead>
              <TableRow>
                <TableHeaderCell>Format</TableHeaderCell>
                <TableHeaderCell>Extensions</TableHeaderCell>
                <TableHeaderCell>Keeps column types</TableHeaderCell>
                <TableHeaderCell>Notes</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {formats.items.map((format) => (
                <TableRow key={format.name}>
                  <TableCell className="text-ink">{format.label}</TableCell>
                  <TableCell className="font-mono text-[13px] text-ink-3">{format.extensions.join(" ")}</TableCell>
                  <TableCell>
                    <Badge tone={format.typed ? "success" : "neutral"}>{format.typed ? "Yes" : "No"}</Badge>
                  </TableCell>
                  <TableCell className="text-[13px] text-ink-3">
                    {format.description}
                    {!format.writable ? " Read only." : ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 text-[13px] text-ink-3">
            Compressed files are opened automatically: {formats.compressions.join(", ")}.
          </p>
        </SectionPanel>
      ) : null}
    </AppShell>
  );
}

function Step({ number, title, children }: { number: number; title: string; children: React.ReactNode }) {
  return (
    <li className="rounded-xl border border-line bg-surface px-4 py-3">
      <div className="flex items-center gap-2">
        <span className="flex h-6 w-6 items-center justify-center rounded-full bg-[color:var(--accent-soft)] text-[13px] font-semibold text-ink">
          {number}
        </span>
        <h3 className="text-[14px] font-medium text-ink">{title}</h3>
      </div>
      <p className="mt-1.5 text-[13px] leading-5 text-ink-3">{children}</p>
    </li>
  );
}

function ConnectorGrid({ specs }: { specs: ConnectorSpec[] }) {
  return (
    <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
      {specs.map((spec) => (
        <ConnectorCard key={spec.type} spec={spec} />
      ))}
    </div>
  );
}

function FilterChip({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={active}
      className={cx(
        "rounded-full border px-3 py-1 text-[13px] transition",
        active
          ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)] text-ink"
          : "border-line text-ink-3 hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function ConnectorCard({ spec }: { spec: ConnectorSpec }) {
  const capabilities = spec.capabilities.flatMap((capability) => {
    const label = CAPABILITY_LABEL[capability];
    return label ? [{ capability, label }] : [];
  });
  return (
    <article className={cx("rounded-xl border border-line bg-surface px-3.5 py-3", !spec.available && "opacity-70")}>
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[14px] font-medium text-ink">{spec.label}</h3>
        <Badge tone={tierTone(spec.tier)} title={spec.tier_explanation} className="shrink-0">
          {spec.tier_label}
        </Badge>
      </div>
      <div className="mt-0.5 text-[13px] text-ink-3">{CATEGORY_LABEL[spec.category] ?? spec.category}</div>
      <p className="mt-1.5 text-[13px] leading-5 text-ink-2">{spec.description}</p>

      {capabilities.length ? (
        <div className="mt-2 flex flex-wrap gap-1">
          {capabilities.map(({ capability, label }) => (
            <Badge key={capability} tone={capability === "write" || capability === "incremental" ? "accent" : "neutral"}>
              {label}
            </Badge>
          ))}
        </div>
      ) : null}

      {!spec.available && spec.unavailable_reason ? (
        <p className="mt-2 flex items-start gap-1.5 text-[13px] leading-5 text-warning">
          <Icon name="info" size={13} className="mt-1 shrink-0" />
          {spec.unavailable_reason}
        </p>
      ) : null}

      <div className="mt-2 text-[13px] text-ink-3">
        {countOf(spec.config_fields.length, "setting")}
        {spec.secret_fields.length > 0 ? ` · ${countOf(spec.secret_fields.length, "secret")} kept encrypted` : ""}
      </div>
    </article>
  );
}
