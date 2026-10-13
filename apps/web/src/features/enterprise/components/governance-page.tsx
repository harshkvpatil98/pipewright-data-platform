"use client";

import { useCallback, useState } from "react";

import type {
  AuthUser,
  ErasureListResponse,
  ErasureRequest,
  RetentionListResponse,
  SecurityPolicyListResponse,
  UsageResponse,
} from "@platform/shared-types";
import { Badge, type BadgeTone, Button, Icon, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { PolicySimulationPanel } from "@/features/enterprise/components/policy-simulation-panel";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { sentenceLabel } from "@/lib/labels";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type GovernancePageProps = {
  currentUser: AuthUser;
  projectId: string;
  policies: SecurityPolicyListResponse;
  retention: RetentionListResponse;
  erasures: ErasureListResponse;
  usage: UsageResponse;
};

const inputClass =
  "h-9 w-full rounded-lg border border-line bg-sunken px-2.5 text-[13px] text-ink outline-none transition focus:border-[color:var(--accent)]";

const ACTION_TONE: Record<string, BadgeTone> = {
  deny: "danger",
  redact: "warning",
  hash: "accent",
  mask: "warning",
  allow: "neutral",
};

export function GovernancePageView({
  currentUser,
  projectId,
  policies: initialPolicies,
  retention,
  erasures,
  usage,
}: GovernancePageProps) {
  // Local so a deleted policy leaves the list without a reload.
  const [policies, setPolicies] = useState(initialPolicies);
  const [retentionState, setRetentionState] = useState(retention);
  const [erasureState, setErasureState] = useState(erasures.items);
  const [subject, setSubject] = useState("");
  const [erasureMode, setErasureMode] = useState<"correction" | "destructive">("correction");
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const sweep = useCallback(async () => {
    setBusy("sweep");
    setError(null);
    try {
      const result = await apiFetch<{ summary: string }>(
        `/projects/${projectId}/retention/run`,
        { method: "POST" },
      );
      setNote(result.summary);
      setRetentionState(
        await apiFetch<RetentionListResponse>(`/projects/${projectId}/retention`),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  }, [projectId]);

  const search = useCallback(
    async (apply: boolean) => {
      if (!subject.trim()) return;
      setBusy(apply ? "erase" : "search");
      setError(null);
      try {
        await apiFetch(`/projects/${projectId}/erasures`, {
          method: "POST",
          body: JSON.stringify({
            subject_value: subject.trim(),
            subject_kind: "email",
            apply,
            mode: erasureMode,
          }),
        });
        setErasureState(
          (await apiFetch<ErasureListResponse>(`/projects/${projectId}/erasures`)).items,
        );
        setSubject("");
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(null);
      }
    },
    [projectId, subject, erasureMode],
  );

  return (
    <AppShell
      currentUser={currentUser}
      title="Policies"
      subtitle="Who sees which rows and columns, and how long data is kept."
    >
      {error ? (
        <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </div>
      ) : null}
      {note ? (
        <div className="rounded-2xl border border-success-line bg-success-soft px-4 py-3 text-sm text-success">
          {note}
        </div>
      ) : null}

      <SectionPanel
        title="Row and column rules"
        description="Membership decides whether you can open a dataset. These decide what you see once you have."
      >
        {policies.warnings.map((warning) => (
          <p key={warning} className="mb-2 flex items-start gap-1.5 text-[12px] text-warning">
            <Icon name="warning" size={11} className="mt-0.5 shrink-0" />
            {warning}
          </p>
        ))}

        {policies.items.length === 0 ? (
          <p className="rounded-xl border border-line px-4 py-6 text-center text-[12.5px] text-muted">
            No policies. Everyone with access to this project sees every row and column, which
            is the right default until something here needs protecting.
          </p>
        ) : (
          <ul className="space-y-2">
            {policies.items.map((policy) => (
              <li
                key={policy.id}
                className="rounded-xl border border-line bg-surface px-3.5 py-3"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="text-[13px] text-ink">{policy.name}</span>
                  <div className="flex items-center gap-2">
                    <Badge className="capitalize">
                      applies to {policy.role}
                    </Badge>
                    <DeleteRowButton
                      path={`/projects/${projectId}/security-policies/${policy.id}`}
                      name={policy.name}
                      kind="security policy"
                      consequences={[
                        "Everyone with access to this project sees every row and column it was hiding.",
                      ]}
                      onDeleted={() =>
                        setPolicies((current) => ({
                          ...current,
                          items: current.items.filter((row) => row.id !== policy.id),
                        }))
                      }
                      className="rounded-lg p-1 text-muted transition hover:text-danger"
                    />
                  </div>
                </div>
                {policy.row_rules.length > 0 ? (
                  <div className="mt-1.5 text-[12px] text-ink-3">
                    Rows where{" "}
                    {policy.row_rules
                      .map(
                        (rule) =>
                          `${rule.column} ${rule.operator.replace(/_/g, " ")} ${JSON.stringify(rule.value)}`,
                      )
                      .join(" and ")}
                  </div>
                ) : null}
                {policy.column_rules.length > 0 ? (
                  <div className="mt-1.5 flex flex-wrap gap-1">
                    {policy.column_rules.map((rule) => (
                      <Badge tone={ACTION_TONE[rule.action] ?? ACTION_TONE.allow} className="font-mono"
                        key={rule.column}>
                        {rule.column} · {rule.action}
                      </Badge>
                    ))}
                  </div>
                ) : null}
                {!policy.enabled ? (
                  <div className="mt-1 text-[12px] text-muted">Disabled.</div>
                ) : null}
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>

      <PolicySimulationPanel projectId={projectId} policies={policies.items} />

      <div className="grid gap-4 lg:grid-cols-2">
        <SectionPanel
          title="Retention"
          description="What gets deleted, and when. New policies start in report-only mode."
          actions={
            retentionState.items.length > 0 ? (
              <Button
                variant="secondary"
                size="sm"
                className="whitespace-nowrap"
                onClick={sweep}
                disabled={busy !== null}
              >
                {busy === "sweep" ? "Running…" : "Run now"}
              </Button>
            ) : null
          }
        >
          {retentionState.items.length === 0 ? (
            <p className="text-[12.5px] text-muted">
              Nothing expires. Runs, metrics, and audit entries accumulate indefinitely, which
              is both a cost and a liability.
            </p>
          ) : (
            <ul className="space-y-2">
              {retentionState.items.map((policy) => (
                <li
                  key={policy.id}
                  className="flex flex-wrap items-center gap-2 rounded-lg border border-line px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <div className="text-[12.5px] text-ink">{policy.resource_label}</div>
                    <div className="text-[12px] text-muted">
                      kept {policy.retain_days} day{policy.retain_days === 1 ? "" : "s"}
                      {policy.last_run_at ? ` · last run ${formatDate(policy.last_run_at)}` : ""}
                      {policy.last_deleted_count
                        ? ` · removed ${policy.last_deleted_count.toLocaleString()}`
                        : ""}
                    </div>
                  </div>
                  <Badge tone={policy.dry_run
                        ? "warning"
                        : "danger"} className="shrink-0">
                    {policy.dry_run ? "report only" : "deletes"}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </SectionPanel>

        <SectionPanel
          title="What it costs to run"
          description={usage.summary}
        >
          {usage.totals.length === 0 ? (
            <p className="text-[12.5px] text-muted">Nothing has run in this period.</p>
          ) : (
            <ul className="space-y-1.5">
              {usage.totals.slice(0, 6).map((total) => (
                <li
                  key={`${total.subject_type}-${total.subject_id ?? total.subject_name}`}
                  className="flex items-center gap-3 rounded-lg border border-line px-3 py-2"
                >
                  <span className="min-w-0 flex-1 truncate text-[12.5px] text-ink">
                    {total.subject_name}
                  </span>
                  <span className="shrink-0 tabular text-[12px] text-ink-3">
                    {total.rows_processed.toLocaleString()} rows
                  </span>
                  <span className="shrink-0 tabular text-[12px] text-muted">
                    {total.compute_seconds}s
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[12px] leading-4 text-muted">
            Rows and seconds, not currency. A price would need per-deployment compute and
            storage rates this platform has no way to know, and an invented one gets quoted in
            a meeting.
          </p>
        </SectionPanel>
      </div>

      <SectionPanel
        title="Erasure requests"
        description="Find a person across every dataset. Searching is safe; redacting is a separate decision, and it never reports success while data remains."
      >
        <div className="flex flex-wrap gap-2">
          <input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="person@example.com"
            className={cx(inputClass, "min-w-[220px] flex-1")}
          />
          <select
            value={erasureMode}
            onChange={(event) => setErasureMode(event.target.value as "correction" | "destructive")}
            className={cx(inputClass, "w-auto")}
            aria-label="Erasure mode"
          >
            <option value="correction">Correction (clear live data)</option>
            <option value="destructive">Destructive (remove from history too)</option>
          </select>
          <Button
            variant="secondary"
            onClick={() => void search(false)}
            disabled={busy !== null || !subject.trim()}
          >
            {busy === "search" ? "Searching…" : "Find them"}
          </Button>
          <Button onClick={() => void search(true)} disabled={busy !== null || !subject.trim()}>
            {busy === "erase" ? "Erasing…" : "Find and erase"}
          </Button>
        </div>
        <p className="mt-2 text-[12px] text-muted">
          Correction clears the current data and keeps history readable. Destructive also removes the
          person from past versions; anything it cannot remove yet (a dataset made from another, a
          file it cannot read) is reported as blocked, never skipped quietly.
        </p>

        {erasureState.length === 0 ? (
          <p className="mt-3 text-[12.5px] text-muted">No requests yet.</p>
        ) : (
          <ul className="mt-3 space-y-2">
            {erasureState.map((request) => (
              <ErasureRow key={request.id} request={request} />
            ))}
          </ul>
        )}
      </SectionPanel>
    </AppShell>
  );
}

function ErasureRow({ request }: { request: ErasureRequest }) {
  const report = request.report as {
    summary?: string;
    subject_value?: string;
    blocked?: { dataset: string; reason: string }[];
  } | null;
  const blocked = report?.blocked ?? [];
  const statusTone: BadgeTone =
    request.status === "completed"
      ? "success"
      : request.status === "blocked"
        ? "danger"
        : request.status === "partial"
          ? "warning"
          : "neutral";
  return (
    <li className="rounded-xl border border-line bg-surface px-3.5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[12.5px] text-ink">
          {report?.subject_value ?? "***"}
        </span>
        <div className="flex items-center gap-1.5">
          <Badge>
            {sentenceLabel(request.mode)}
          </Badge>
          <Badge tone={statusTone}>
            {sentenceLabel(request.status)}
          </Badge>
        </div>
      </div>
      {report?.summary ? (
        <p className="mt-1 text-[12px] leading-4 text-ink-3">{report.summary}</p>
      ) : null}
      {blocked.length > 0 ? (
        <div className="mt-2 rounded-lg border border-warning-line bg-warning-soft px-2.5 py-2 text-[12px] text-warning">
          Not erased ({blocked.length}):{" "}
          {blocked.map((entry) => `${entry.dataset}: ${entry.reason}`).join("; ")}
        </div>
      ) : null}
      <div className="mt-1 text-[12px] text-muted">
        {request.datasets_searched} dataset(s) searched · {request.rows_affected} row(s) ·{" "}
        {formatDate(request.created_at)}
      </div>
    </li>
  );
}
