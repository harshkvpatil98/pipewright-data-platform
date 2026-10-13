"use client";

import { useCallback, useEffect, useState } from "react";

import type { ImpactAnalysis, ImpactSeverity } from "@platform/shared-types";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { sentenceLabel } from "@/lib/labels";
import { cx } from "@/lib/utils";
import { Badge, type BadgeTone, Modal } from "@platform/shared-ui";

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

const SEVERITY_BADGE: Record<ImpactSeverity, BadgeTone> = {
  breaks: "danger",
  changes: "warning",
  informational: "neutral",
};

const KIND_LABEL: Record<string, string> = {
  pipeline: "Recipe",
  quality_rule: "Check",
  workflow: "Workflow",
  dataset: "Dataset",
  chart: "Chart",
  dashboard: "Dashboard",
  metric: "Metric",
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

  return (
    <Modal
      open
      onClose={onClose}
      title="What depends on this"
      description={`What uses ${columns.map((column) => `“${column}”`).join(", ")}, and what would break or change without it.`}
    >
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
                    <Badge tone={SEVERITY_BADGE[finding.severity]} className="shrink-0">
                      {SEVERITY_LABEL[finding.severity]}
                    </Badge>
                  </div>
                  <div className="mt-1.5 text-[12px] text-muted">
                    {KIND_LABEL[finding.kind] ?? sentenceLabel(finding.kind)}
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </Modal>
  );
}
