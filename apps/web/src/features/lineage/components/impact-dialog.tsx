"use client";

import { useCallback, useEffect, useState } from "react";

import type { ImpactAnalysis, ImpactSeverity } from "@platform/shared-types";

import { Icon } from "@/components/ui/icon";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type ImpactDialogProps = {
  projectId: string;
  datasetId: string;
  columns: string[];
  onClose: () => void;
};

const SEVERITY_TONE: Record<ImpactSeverity, string> = {
  breaks: "border-danger-line bg-danger-soft text-danger",
  changes: "border-warning-line bg-warning-soft text-warning",
  informational: "border-line bg-surface text-ink-2",
};

const SEVERITY_LABEL: Record<ImpactSeverity, string> = {
  breaks: "Breaks",
  changes: "Changes results",
  informational: "Related",
};

/**
 * "What breaks if I drop this column?"
 *
 * The answer people expect is yes-or-no. The answer that saves them is
 * three-way, because the middle grade -- nothing errors but the numbers move --
 * is the one that gets discovered a quarter later.
 */
export function ImpactDialog({ projectId, datasetId, columns, onClose }: ImpactDialogProps) {
  const [analysis, setAnalysis] = useState<ImpactAnalysis | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setAnalysis(
        await apiFetch<ImpactAnalysis>(`/projects/${projectId}/datasets/${datasetId}/impact`, {
          method: "POST",
          body: JSON.stringify({ columns }),
        }),
      );
    } catch (caught) {
      setError(extractErrorMessage(caught));
    }
  }, [projectId, datasetId, columns]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[70] flex items-center justify-center px-4">
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default bg-scrim backdrop-blur-sm"
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="Impact analysis"
        className="animate-fade-up relative flex max-h-[80vh] w-full max-w-2xl flex-col overflow-hidden rounded-2xl border border-line bg-[color:var(--panel-strong)] shadow-[var(--shadow-lg)]"
      >
        <div className="flex items-center justify-between border-b border-line px-5 py-3.5">
          <div>
            <h2 className="text-[14px] font-semibold text-ink">Impact analysis</h2>
            <p className="mt-0.5 text-[12px] text-muted">
              What depends on {columns.map((column) => `'${column}'`).join(", ")}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close impact analysis"
            className="rounded p-1 text-muted transition hover:bg-surface-2 hover:text-ink"
          >
            <Icon name="close" size={14} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-5 py-4">
          {error ? (
            <div className="rounded-lg border border-danger-line bg-danger-soft px-3 py-2.5 text-[12.5px] text-danger">
              {error}
            </div>
          ) : !analysis ? (
            <div className="py-6 text-center text-[12.5px] text-muted">Checking…</div>
          ) : (
            <>
              <p
                className={cx(
                  "rounded-lg border px-3 py-2.5 text-[13px]",
                  analysis.breaks_count > 0
                    ? SEVERITY_TONE.breaks
                    : analysis.changes_count > 0
                      ? SEVERITY_TONE.changes
                      : "border-success-line bg-success-soft text-success",
                )}
              >
                {analysis.summary}
              </p>

              {analysis.findings.length > 0 ? (
                <ul className="mt-3 space-y-2">
                  {analysis.findings.map((finding, index) => (
                    <li
                      key={`${finding.kind}-${finding.id}-${index}`}
                      className="rounded-lg border border-line bg-surface px-3 py-2.5"
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <div className="text-[13px] text-ink">{finding.name}</div>
                          <p className="mt-1 text-[12px] leading-5 text-ink-3">
                            {finding.detail}
                          </p>
                        </div>
                        <span
                          className={cx(
                            "shrink-0 rounded-full border px-2 py-0.5 text-[10.5px]",
                            SEVERITY_TONE[finding.severity],
                          )}
                        >
                          {SEVERITY_LABEL[finding.severity]}
                        </span>
                      </div>
                      <div className="mt-1.5 text-[10.5px] uppercase tracking-wide text-muted">
                        {finding.kind.replace("_", " ")}
                      </div>
                    </li>
                  ))}
                </ul>
              ) : null}
            </>
          )}
        </div>
      </div>
    </div>
  );
}
