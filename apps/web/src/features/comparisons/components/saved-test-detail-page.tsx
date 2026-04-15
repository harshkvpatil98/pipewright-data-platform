"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type { AuthUser, SavedStatisticalTestDetail } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate, titleCase } from "@/lib/format";

type SavedTestDetailPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  detail: SavedStatisticalTestDetail;
};

export function SavedTestDetailPageView({ currentUser, projectId, detail }: SavedTestDetailPageViewProps) {
  const router = useRouter();
  const { saved_test, runs, comparison_note } = detail;
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function onRerun() {
    setError(null);
    setRunning(true);
    try {
      await apiFetch(`/projects/${projectId}/tests/saved/${saved_test.id}/run`, { method: "POST" });
      router.refresh();
    } catch (e) {
      setError(extractErrorMessage(e));
    } finally {
      setRunning(false);
    }
  }

  const latestSuccess = runs.find((r) => r.status === "succeeded" && r.result);

  return (
    <AppShell
      currentUser={currentUser}
      eyebrow="Testing lab"
      title={saved_test.name}
      subtitle={saved_test.description ?? "Saved statistical test configuration and run history."}
      actions={
        <div className="flex flex-wrap gap-2">
          <Link
            href={`/projects/${projectId}/tests/saved`}
            className="rounded-full border border-white/10 bg-white/[0.05] px-4 py-2 text-xs font-medium uppercase tracking-[0.16em] text-slate-200 hover:border-white/20"
          >
            All saved tests
          </Link>
          <Button variant="secondary" disabled={running} onClick={() => void onRerun()}>
            {running ? "Running…" : "Run again"}
          </Button>
        </div>
      }
      meta={
        <span className="rounded-full border border-white/10 bg-white/[0.05] px-3 py-1 text-xs uppercase tracking-[0.18em] text-slate-300">
          {titleCase(saved_test.test_type.replace(/_/g, " "))} · {saved_test.column_name}
        </span>
      }
    >
      {error ? (
        <p className="mb-4 text-sm text-rose-300" role="alert">
          {error}
        </p>
      ) : null}

      <SectionPanel title="Configuration" description="Stored definition; datasets are referenced by id and rerun against current files.">
        <dl className="grid gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-[0.16em] text-slate-500">Left dataset</dt>
            <dd className="mt-1 text-slate-200">{saved_test.left_dataset_name}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.16em] text-slate-500">Right dataset</dt>
            <dd className="mt-1 text-slate-200">{saved_test.right_dataset_name}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.16em] text-slate-500">Test type</dt>
            <dd className="mt-1 font-mono text-xs text-slate-300">{saved_test.test_type}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-[0.16em] text-slate-500">Column</dt>
            <dd className="mt-1 font-mono text-xs text-slate-300">{saved_test.column_name}</dd>
          </div>
        </dl>
      </SectionPanel>

      {latestSuccess?.result ? (
        <SectionPanel title="Latest successful result" description="Most recent succeeded run.">
          <dl className="grid gap-2 md:grid-cols-2 text-sm">
            <div>
              <dt className="text-xs text-slate-500">Statistic</dt>
              <dd className="font-mono text-slate-100">
                {latestSuccess.result.statistic != null && Number.isFinite(latestSuccess.result.statistic)
                  ? String(latestSuccess.result.statistic)
                  : "—"}
              </dd>
            </div>
            <div>
              <dt className="text-xs text-slate-500">p-value</dt>
              <dd className="font-mono text-slate-100">
                {latestSuccess.result.p_value != null ? latestSuccess.result.p_value.toExponential(4) : "—"}
              </dd>
            </div>
            <div className="md:col-span-2">
              <p className="text-slate-300">{latestSuccess.result.interpretation}</p>
            </div>
          </dl>
        </SectionPanel>
      ) : null}

      {comparison_note ? (
        <SectionPanel title="Compared to previous success" description="p-value comparison across the two most recent successful runs.">
          <p className="text-sm text-slate-300">{comparison_note}</p>
        </SectionPanel>
      ) : null}

      <SectionPanel title="Run history" description="Newest first. Failed runs retain error details for troubleshooting.">
        {runs.length === 0 ? (
          <p className="text-sm text-slate-400">No runs yet.</p>
        ) : (
          <ul className="space-y-4">
            {runs.map((run) => (
              <li
                key={run.id}
                className="rounded-2xl border border-white/10 bg-white/[0.03] px-4 py-3 text-sm text-slate-200"
              >
                <div className="flex flex-wrap items-center justify-between gap-2 text-xs uppercase tracking-[0.14em] text-slate-500">
                  <span>{formatDate(run.created_at)}</span>
                  <span className={run.status === "succeeded" ? "text-emerald-300/90" : "text-rose-300/90"}>
                    {run.status}
                  </span>
                </div>
                {run.status === "succeeded" && run.result ? (
                  <div className="mt-2 space-y-1">
                    <p className="font-mono text-xs text-slate-300">
                      statistic {run.result.statistic ?? "—"} · p {run.result.p_value != null ? run.result.p_value.toExponential(4) : "—"}
                    </p>
                    <p className="text-slate-400">{run.result.interpretation}</p>
                    {run.result.warnings.length > 0 ? (
                      <ul className="list-inside list-disc text-xs text-slate-500">
                        {run.result.warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    ) : null}
                  </div>
                ) : (
                  <p className="mt-2 text-rose-200/90">{run.error_message ?? "Run failed."}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </SectionPanel>
    </AppShell>
  );
}
