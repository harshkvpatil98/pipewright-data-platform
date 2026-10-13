"use client";

import { useEffect, useMemo, useState } from "react";

import type {
  DatasetListResponse,
  MemberListResponse,
  ProjectMember,
  SecurityPolicy,
  SecurityPreview,
} from "@platform/shared-types";
import {
  Badge,
  Button,
  SectionPanel,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

const ROLES = ["viewer", "operator", "editor", "admin"] as const;
const selectClass =
  "h-9 rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none focus:border-[color:var(--accent)]";

/**
 * Answer "would this person see the salary column?" before granting access.
 * Pick a dataset, then preview it as a bare role or as a specific member; the
 * result shows exactly what rows and columns that view would expose.
 */
export function PolicySimulationPanel({
  projectId,
  policies,
}: {
  projectId: string;
  policies: SecurityPolicy[];
}) {
  // Datasets that actually have a policy are the ones worth simulating.
  const policiedDatasetIds = useMemo(
    () => Array.from(new Set(policies.map((p) => p.dataset_id))),
    [policies],
  );

  const [datasets, setDatasets] = useState<{ id: string; name: string }[]>([]);
  const [members, setMembers] = useState<ProjectMember[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [mode, setMode] = useState<"role" | "user">("role");
  const [role, setRole] = useState<string>("viewer");
  const [userId, setUserId] = useState("");
  const [result, setResult] = useState<SecurityPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<DatasetListResponse>(`/projects/${projectId}/datasets`)
      .then((response) => {
        const named = response.items.map((d) => ({ id: d.id, name: d.name }));
        setDatasets(named);
        const firstPolicied = named.find((d) => policiedDatasetIds.includes(d.id)) ?? named[0];
        if (firstPolicied) setDatasetId(firstPolicied.id);
      })
      .catch(() => setDatasets([]));
    apiFetch<MemberListResponse>(`/projects/${projectId}/members`)
      .then((response) => {
        setMembers(response.items);
        if (response.items[0]) setUserId(response.items[0].user_id);
      })
      .catch(() => setMembers([]));
  }, [projectId, policiedDatasetIds]);

  const run = async () => {
    if (!datasetId) return;
    setBusy(true);
    setError(null);
    try {
      const query =
        mode === "user" && userId
          ? `?user_id=${encodeURIComponent(userId)}`
          : `?role=${encodeURIComponent(role)}`;
      setResult(
        await apiFetch<SecurityPreview>(
          `/projects/${projectId}/datasets/${datasetId}/security-preview${query}`,
        ),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
      setResult(null);
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionPanel
      title="Policy simulation"
      description="See exactly what a role, or one person, would see on a dataset before you grant it."
    >
      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-[12px] text-muted">
          Dataset
          <select className={selectClass} value={datasetId} onChange={(e) => setDatasetId(e.target.value)}>
            {datasets.length === 0 ? <option value="">No datasets</option> : null}
            {datasets.map((d) => (
              <option key={d.id} value={d.id}>
                {d.name}
                {policiedDatasetIds.includes(d.id) ? " • has policy" : ""}
              </option>
            ))}
          </select>
        </label>

        <div className="flex gap-1.5">
          {(["role", "user"] as const).map((m) => (
            <button
              key={m}
              type="button"
              onClick={() => setMode(m)}
              className={cx(
                "rounded-full border px-3 py-1.5 text-[12px] font-medium capitalize transition",
                mode === m
                  ? "border-[color:var(--accent-soft)] bg-[color:var(--accent-faint)] text-ink"
                  : "border-line bg-surface text-ink-2 hover:border-line-strong",
              )}
            >
              As {m}
            </button>
          ))}
        </div>

        {mode === "role" ? (
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            Role
            <select className={selectClass} value={role} onChange={(e) => setRole(e.target.value)}>
              {ROLES.map((r) => (
                <option key={r} value={r}>{r}</option>
              ))}
            </select>
          </label>
        ) : (
          <label className="flex flex-col gap-1 text-[12px] text-muted">
            User
            <select className={selectClass} value={userId} onChange={(e) => setUserId(e.target.value)}>
              {members.length === 0 ? <option value="">No members</option> : null}
              {members.map((m) => (
                <option key={m.user_id} value={m.user_id}>
                  {m.username}{m.is_owner ? " (owner)" : ""}
                </option>
              ))}
            </select>
          </label>
        )}

        <Button onClick={() => void run()} disabled={busy || !datasetId}>
          {busy ? "Simulating…" : "Simulate"}
        </Button>
      </div>

      {error ? (
        <div className="mt-4 rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}

      {result ? (
        <div className="mt-5 space-y-4">
          <p className="text-[13px] text-ink-2">
            {result.viewed_as_username
              ? `As ${result.viewed_as_username} (${result.role}): `
              : `As ${result.role}: `}
            <span className="font-medium text-ink">
              {result.rows_after} of {result.rows_before} rows visible
            </span>
            {result.rows_hidden > 0 ? `, ${result.rows_hidden} hidden` : ""}.
          </p>
          {result.columns_removed.length > 0 || result.columns_masked.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {result.columns_removed.map((c) => (
                <Badge key={`r-${c}`} tone="danger">
                  {c} removed
                </Badge>
              ))}
              {result.columns_masked.map((c) => (
                <Badge key={`m-${c}`} tone="warning">
                  {c} masked
                </Badge>
              ))}
            </div>
          ) : (
            <p className="text-[12px] text-muted">No columns hidden or masked for this view.</p>
          )}

          {result.sample_rows.length > 0 ? (
            <div className="overflow-hidden rounded-xl border border-line bg-sunken">
              <Table edge="panel">
                <TableHead>
                  <TableRow>
                    {Object.keys(result.sample_rows[0]).map((key) => (
                      <TableHeaderCell key={key}>{key}</TableHeaderCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.sample_rows.map((row, index) => (
                    <TableRow key={index}>
                      {Object.keys(result.sample_rows[0]).map((key) => (
                        <TableCell key={key} className="text-ink-2">{String(row[key] ?? "—")}</TableCell>
                      ))}
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}
        </div>
      ) : null}
    </SectionPanel>
  );
}
