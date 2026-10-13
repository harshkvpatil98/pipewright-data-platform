"use client";

import { useEffect, useMemo, useState } from "react";

import type {
  AuthUser,
  ConnectorCapability,
  ConnectorCatalogResponse,
  ConnectorHealth,
  ConnectorSpec,
  FormatCatalogResponse,
} from "@platform/shared-types";
import { Badge, Icon, SectionPanel, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
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
  saas: "SaaS tools",
  nosql: "Document stores",
  file: "Files",
  timeseries: "Time series",
  streaming: "Streams",
  lakehouse: "Lakehouse",
};

const CAPABILITY_LABEL: Record<ConnectorCapability, string> = {
  test: "Testable",
  discover: "Lists what it holds",
  schema: "Knows its columns",
  read: "Read",
  incremental: "Reads only what changed",
  write: "Write back",
};

export function ConnectorCatalogPageView({
  currentUser,
  initial,
}: ConnectorCatalogPageProps) {
  const [category, setCategory] = useState<string>("all");
  const [onlyVerified, setOnlyVerified] = useState(false);
  const [formats, setFormats] = useState<FormatCatalogResponse | null>(null);
  const [health, setHealth] = useState<ConnectorHealth | null>(null);

  useEffect(() => {
    apiFetch<FormatCatalogResponse>("/connectors/formats")
      .then(setFormats)
      .catch(() => setFormats(null));
    apiFetch<ConnectorHealth>("/connectors/health")
      .then(setHealth)
      .catch(() => setHealth(null));
  }, []);

  const grouped = useMemo(() => {
    const buckets = new Map<string, ConnectorSpec[]>();
    for (const spec of initial.items) {
      const list = buckets.get(spec.category) ?? [];
      list.push(spec);
      buckets.set(spec.category, list);
    }
    return buckets;
  }, [initial.items]);

  const visible = useMemo(() => {
    let pool = initial.items;
    if (category !== "all") pool = pool.filter((spec) => spec.category === category);
    if (onlyVerified) pool = pool.filter((spec) => spec.verified);
    return pool;
  }, [initial.items, category, onlyVerified]);

  const available = initial.items.filter((spec) => spec.available).length;
  const verified = initial.items.filter((spec) => spec.verified).length;

  return (
    <AppShell
      currentUser={currentUser}
      title="Connectors"
      subtitle="Every kind of source Pipewright can connect to, and how well each is tested."
    >
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat value={initial.items.length} label="Connectors" />
        <Stat value={available} label="Ready to use here" tone="text-success" />
        <Stat value={verified} label="Verified by a test" tone="text-success" />
        <Stat
          value={initial.items.filter((spec) => spec.capabilities.includes("write")).length}
          label="Can write back"
          tone="text-accent"
        />
      </div>

      {health ? <VerificationPanel health={health} /> : null}

      <SectionPanel
        title="Catalogue"
        description="Greyed-out connectors need a driver this deployment does not have installed. Every card carries how much is known about whether it works."
      >
        <div className="mb-3 flex flex-wrap gap-1.5">
          <FilterChip active={category === "all"} onClick={() => setCategory("all")}>
            All
          </FilterChip>
          {[...grouped.keys()].sort().map((key) => (
            <FilterChip
              key={key}
              active={category === key}
              onClick={() => setCategory(key)}
            >
              {CATEGORY_LABEL[key] ?? key} ({grouped.get(key)?.length ?? 0})
            </FilterChip>
          ))}
          <span className="mx-1 w-px self-stretch bg-line" aria-hidden="true" />
          <FilterChip active={onlyVerified} onClick={() => setOnlyVerified((on) => !on)}>
            Verified only ({verified})
          </FilterChip>
        </div>

        <div className="grid gap-2.5 md:grid-cols-2 xl:grid-cols-3">
          {visible.map((spec) => (
            <ConnectorCard key={spec.type} spec={spec} />
          ))}
        </div>
      </SectionPanel>

      {formats ? (
        <SectionPanel
          title="File formats"
          description="Typed formats keep the column types a CSV would lose."
        >
          <Table minWidth={560}>
            <TableHead>
              <TableRow className="text-[12px] text-muted">
                <TableHeaderCell>Format</TableHeaderCell>
                <TableHeaderCell>Extensions</TableHeaderCell>
                <TableHeaderCell>Keeps types</TableHeaderCell>
                <TableHeaderCell>Notes</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {formats.items.map((format) => (
                <TableRow key={format.name}>
                  <TableCell className="text-[12.5px] text-ink">{format.label}</TableCell>
                  <TableCell className="font-mono text-[12px] text-muted">
                    {format.extensions.join(" ")}
                  </TableCell>
                  <TableCell>
                    <Badge tone={format.typed
                          ? "success"
                          : "neutral"}>
                      {format.typed ? "yes" : "no"}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-[12px] text-ink-3">
                    {format.description}
                    {!format.writable ? " Read only." : ""}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <p className="mt-3 text-[12px] text-muted">
            Compression is unwrapped automatically: {formats.compressions.join(", ")}.
          </p>
        </SectionPanel>
      ) : null}
    </AppShell>
  );
}

function Stat({ value, label, tone }: { value: number; label: string; tone?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-3">
      <div className={cx("text-2xl font-semibold", tone ?? "text-ink")}>{value}</div>
      <div className="mt-0.5 text-[12px] text-muted">{label}</div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cx(
        "rounded-lg px-2.5 py-1 text-[12px] transition",
        active
          ? "bg-[color:var(--accent)] text-accent-ink"
          : "border border-line text-ink-3 hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}

function ConnectorCard({ spec }: { spec: ConnectorSpec }) {
  return (
    <article
      className={cx(
        "rounded-xl border px-3.5 py-3",
        spec.available
          ? "border-line bg-surface"
          : "border-line bg-surface opacity-60",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <h3 className="text-[13.5px] font-medium text-ink">{spec.label}</h3>
        <Badge className="shrink-0">
          {CATEGORY_LABEL[spec.category] ?? spec.category}
        </Badge>
      </div>

      <div className="mt-1.5">
        <Badge tone={tierTone(spec.tier)} title={spec.tier_explanation}>
          <span aria-hidden="true">{spec.tier_badge}</span>
          {spec.tier_label}
          {spec.verified_by ? <span className="font-normal opacity-80">· {spec.verified_by}</span> : null}
        </Badge>
      </div>
      <p className="mt-1 text-[12px] leading-5 text-ink-3">{spec.description}</p>

      <div className="mt-2 flex flex-wrap gap-1">
        {spec.capabilities
          .filter((capability) => capability !== "test")
          .map((capability) => (
            <Badge
              key={capability}
              tone={capability === "write" || capability === "incremental" ? "accent" : "neutral"}
              title={CAPABILITY_LABEL[capability]}
            >
              {CAPABILITY_LABEL[capability]}
            </Badge>
          ))}
      </div>

      {!spec.available && spec.unavailable_reason ? (
        <p className="mt-2 flex items-start gap-1.5 text-[12px] leading-4 text-warning">
          <Icon name="info" size={11} className="mt-0.5 shrink-0" />
          {spec.unavailable_reason}
        </p>
      ) : null}

      {!spec.verified ? (
        <p className="mt-2 text-[12px] leading-4 text-muted">{spec.tier_explanation}</p>
      ) : null}

      <div className="mt-2 text-[12px] text-muted">
        {spec.config_fields.length} setting{spec.config_fields.length === 1 ? "" : "s"}
        {spec.secret_fields.length > 0
          ? ` · ${spec.secret_fields.length} stored encrypted`
          : ""}
      </div>
    </article>
  );
}


function VerificationPanel({ health }: { health: ConnectorHealth }) {
  const total = health.total || 1;
  return (
    <SectionPanel
      title="How much is known"
      description="Every connector says how far it has been tested, and that carries into every run that uses it."
    >
      <ul className="flex flex-col gap-2">
        {health.tiers.map((tier) => (
          <li key={tier.tier} className="flex items-center gap-3">
            <Badge tone={tierTone(tier.tier)} className="flex w-40 shrink-0">
              <span aria-hidden="true">{tier.badge}</span>
              {tier.label}
            </Badge>
            {/* A fixed-width track: a bar sized against the whole row squeezed
                the explanation beside the largest tier into a 70px column. */}
            <span
              className="h-1.5 w-32 shrink-0 overflow-hidden rounded-full bg-surface-2"
              aria-hidden="true"
            >
              <span
                className="block h-full rounded-full bg-[color:var(--accent)]"
                style={{ width: `${Math.max(2, (tier.count / total) * 100)}%` }}
              />
            </span>
            <span className="w-8 shrink-0 text-right text-[12px] tabular-nums text-ink-2">
              {tier.count}
            </span>
            <span className="hidden min-w-0 flex-1 text-[12px] text-muted lg:block">
              {tier.explanation}
            </span>
          </li>
        ))}
      </ul>

      {health.missing_packages.length > 0 ? (
        <div className="mt-4 border-t border-line pt-3">
          <h4 className="text-[12px] text-muted">
            What installing one package would unlock
          </h4>
          <ul className="mt-2 flex flex-wrap gap-1.5">
            {health.missing_packages.slice(0, 8).map((entry) => (
              <li
                key={entry.package}
                className="rounded-lg border border-line px-2 py-1 text-[12px] text-ink-3"
              >
                <code className="text-ink">{entry.package}</code> · {entry.unlocks} connector
                {entry.unlocks === 1 ? "" : "s"}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className="mt-3 text-[12px] text-muted">
        {health.origins.manifest ?? 0} declared in a manifest ·{" "}
        {health.origins.dialect ?? 0} from the dialect table ·{" "}
        {health.origins.matrix ?? 0} object stores across {health.formats} formats (
        {health.store_format_combinations.toLocaleString()} combinations) ·{" "}
        {health.origins.declared ?? 0} engines listed with what to use instead ·{" "}
        {health.origins.handwritten ?? 0} hand-written.
      </p>
    </SectionPanel>
  );
}
