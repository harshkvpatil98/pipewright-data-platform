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
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { PolicySimulationPanel } from "@/features/enterprise/components/policy-simulation-panel";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
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

const ACTION_TONE: Record<string, string> = {
  deny: "border-danger-line bg-danger-soft text-danger",
  redact: "border-warning-line bg-warning-soft text-warning",
  hash: "border-accent-line bg-accent-soft text-accent",
  mask: "border-warning-line bg-warning-soft text-warning",
  allow: "border-line text-ink-3",
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
    [projectId, subject],
  );

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Enterprise"
      title="Governance"
      subtitle="Who may see which rows, how long things are kept, what a person's data costs to hold, and what it costs to run."
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
                    <span className="rounded bg-surface-2 px-1.5 py-0.5 text-[10.5px] capitalize text-ink-3">
                      applies to {policy.role}
                    </span>
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
                  <div className="mt-1.5 text-[11.5px] text-ink-3">
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
                      <span
                        key={rule.column}
                        className={cx(
                          "rounded border px-1.5 py-0.5 font-mono text-[10.5px]",
                          ACTION_TONE[rule.action] ?? ACTION_TONE.allow,
                        )}
                      >
                        {rule.column} · {rule.action}
                      </span>
                    ))}
                  </div>
                ) : null}
                {!policy.enabled ? (
                  <div className="mt-1 text-[11px] text-muted">Disabled.</div>
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
              <Button variant="secondary" onClick={sweep} disabled={busy !== null}>
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
                    <div className="text-[11px] text-muted">
                      kept {policy.retain_days} day{policy.retain_days === 1 ? "" : "s"}
                      {policy.last_run_at ? ` · last run ${formatDate(policy.last_run_at)}` : ""}
                      {policy.last_deleted_count
                        ? ` · removed ${policy.last_deleted_count.toLocaleString()}`
                        : ""}
                    </div>
                  </div>
                  <span
                    className={cx(
                      "shrink-0 rounded-full border px-2 py-0.5 text-[10.5px]",
                      policy.dry_run
                        ? "border-warning-line bg-warning-soft text-warning"
                        : "border-danger-line bg-danger-soft text-danger",
                    )}
                  >
                    {policy.dry_run ? "report only" : "deletes"}
                  </span>
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
                  <span className="shrink-0 tabular text-[11.5px] text-ink-3">
                    {total.rows_processed.toLocaleString()} rows
                  </span>
                  <span className="shrink-0 tabular text-[11px] text-muted">
                    {total.compute_seconds}s
                  </span>
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-[11px] leading-4 text-muted">
            Rows and seconds, not currency. A price would need per-deployment compute and
            storage rates this platform has no way to know, and an invented one gets quoted in
            a meeting.
          </p>
        </SectionPanel>
      </div>

      <SectionPanel
        title="Erasure requests"
        description="Find a person across every dataset. Searching is safe; redacting is a separate decision."
      >
        <div className="flex flex-wrap gap-2">
          <input
            value={subject}
            onChange={(event) => setSubject(event.target.value)}
            placeholder="person@example.com"
            className={cx(inputClass, "min-w-[220px] flex-1")}
          />
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
  const report = request.report as { summary?: string; subject_value?: string } | null;
  return (
    <li className="rounded-xl border border-line bg-surface px-3.5 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-[12.5px] text-ink">
          {report?.subject_value ?? "***"}
        </span>
        <span
          className={cx(
            "rounded-full border px-2 py-0.5 text-[10.5px]",
            request.status === "completed"
              ? "border-success-line bg-success-soft text-success"
              : "border-line text-ink-3",
          )}
        >
          {request.status}
        </span>
      </div>
      {report?.summary ? (
        <p className="mt-1 text-[12px] leading-4 text-ink-3">{report.summary}</p>
      ) : null}
      <div className="mt-1 text-[11px] text-muted">
        {request.datasets_searched} dataset(s) searched · {request.rows_affected} row(s) ·{" "}
        {formatDate(request.created_at)}
      </div>
    </li>
  );
}
