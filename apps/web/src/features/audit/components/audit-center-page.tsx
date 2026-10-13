"use client";

import { useCallback, useEffect, useState } from "react";

import type { AuditCenterResponse, AuditCenterRow, AuthUser } from "@platform/shared-types";
import { Badge, Button, EmptyState, Input, SectionPanel, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { OperationalError } from "@/components/operational/operational-messages";
import { apiFetch } from "@/lib/api/client";
import { appConfig } from "@/lib/config";
import { extractErrorMessage } from "@/lib/api/errors";
import { getAccessToken } from "@/lib/auth/session";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";
import { sentenceLabel } from "@/lib/labels";

type AuditCenterPageProps = {
  currentUser: AuthUser;
  initial: AuditCenterResponse | null;
  forbidden: boolean;
};

const OUTCOMES = [
  { key: "", label: "All" },
  { key: "success", label: "Success" },
  { key: "failure", label: "Failure" },
];

/**
 * Every action across every project, for an admin. The old route redirected
 * into a single project's audit; this is the governance-wide stream, filterable
 * and exportable, with the retention window stated so the policy is visible.
 */
export function AuditCenterPageView({ currentUser, initial, forbidden }: AuditCenterPageProps) {
  const [rows, setRows] = useState<AuditCenterRow[]>(initial?.items ?? []);
  const [retentionDays, setRetentionDays] = useState(initial?.retention_days ?? 0);
  const [outcome, setOutcome] = useState("");
  const [actor, setActor] = useState("");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const params = useCallback(() => {
    const search = new URLSearchParams();
    if (outcome) search.set("outcome", outcome);
    if (actor.trim()) search.set("actor", actor.trim());
    if (query.trim()) search.set("q", query.trim());
    return search;
  }, [outcome, actor, query]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const search = params();
      const suffix = search.toString() ? `?${search.toString()}` : "";
      const response = await apiFetch<AuditCenterResponse>(`/audits${suffix}`);
      setRows(response.items);
      setRetentionDays(response.retention_days);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setLoading(false);
    }
  }, [params]);

  // Debounced reload on any filter change (skip the first render — SSR seeded it).
  const [mounted, setMounted] = useState(false);
  useEffect(() => {
    if (!mounted) {
      setMounted(true);
      return;
    }
    const timer = setTimeout(() => void load(), 300);
    return () => clearTimeout(timer);
  }, [outcome, actor, query, mounted, load]);

  // Export via an authenticated fetch, not a plain link: the API reads a bearer
  // token, which a navigation would not carry. Stream the body into a download.
  const download = async (format: string) => {
    const search = params();
    search.set("format", format);
    try {
      const token = getAccessToken();
      const response = await fetch(`${appConfig.apiBaseUrl}/audits/export?${search.toString()}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });
      if (!response.ok) throw new Error(`Export failed (${response.status}).`);
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `audit-export.${format}`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  };

  if (forbidden) {
    return (
      <AppShell currentUser={currentUser} title="Audit across all projects" subtitle="Every change in every project, with filters and export.">
        <EmptyState size="compact"
          title="Admins only"
          description="The Audit Center shows actions across every project, so it is limited to platform admins."
        />
      </AppShell>
    );
  }

  return (
    <AppShell
      currentUser={currentUser}
      title="Audit across all projects"
      subtitle="Every action across every project. Filter, then export for an offline record."
      actions={
        <>
          <Button variant="secondary" onClick={() => void download("csv")}>Export CSV</Button>
          <Button variant="secondary" onClick={() => void download("json")}>Export JSON</Button>
        </>
      }
    >
      <div className="mb-4 flex flex-wrap items-end gap-3">
        <div className="flex gap-1.5">
          {OUTCOMES.map((option) => (
            <button
              key={option.key || "all"}
              type="button"
              onClick={() => setOutcome(option.key)}
              className={cx(
                "rounded-full border px-3 py-1.5 text-[12px] font-medium transition",
                outcome === option.key
                  ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] text-ink"
                  : "border-line bg-surface text-ink-2 hover:border-line-strong",
              )}
            >
              {option.label}
            </button>
          ))}
        </div>
        <div className="w-44">
          <Input value={actor} onChange={(e) => setActor(e.target.value)} placeholder="Actor…" aria-label="Filter by actor" />
        </div>
        <div className="w-64">
          <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Path or action…" aria-label="Search path or action" />
        </div>
      </div>

      {error ? <OperationalError title="Could not load the audit trail" message={error} /> : null}

      <SectionPanel
        title="Activity"
        description={
          loading
            ? "Loading…"
            : `${rows.length} entr${rows.length === 1 ? "y" : "ies"}` +
              (retentionDays > 0 ? ` · kept for ${retentionDays} days` : " · kept indefinitely")
        }
      >
        {rows.length === 0 ? (
          <EmptyState size="compact"
            title="No matching activity"
            description={
              outcome || actor || query
                ? "Nothing matches these filters."
                : "Nothing has been recorded yet. Every change anyone makes appears here."
            }
            action={
              outcome || actor || query ? (
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => {
                    setOutcome("");
                    setActor("");
                    setQuery("");
                  }}
                >
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        ) : (
          <div className="overflow-hidden rounded-[24px] border border-line bg-sunken">
            <Table minWidth={820}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>When</TableHeaderCell>
                  <TableHeaderCell>Actor</TableHeaderCell>
                  <TableHeaderCell>Project</TableHeaderCell>
                  <TableHeaderCell>Action</TableHeaderCell>
                  <TableHeaderCell>Outcome</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell className="text-xs text-ink-3">{formatDate(row.created_at)}</TableCell>
                    <TableCell className="text-ink-2">{row.actor_username ?? "—"}</TableCell>
                    <TableCell className="text-ink-3">{row.project_name ?? "—"}</TableCell>
                    <TableCell className="text-ink-2">
                      {row.action}
                      <span className="ml-2 font-mono text-[12px] text-muted">{row.method} {row.path}</span>
                    </TableCell>
                    <TableCell>
                      <Badge tone={row.outcome === "success"
                            ? "success"
                            : "danger"}>
                        {sentenceLabel(row.outcome)}
                      </Badge>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        )}
      </SectionPanel>
    </AppShell>
  );
}
