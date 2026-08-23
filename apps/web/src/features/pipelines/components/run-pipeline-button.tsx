"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import type { TransformationRunResponse } from "@platform/shared-types";
import { Button } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type RunPipelineButtonProps = {
  projectId: string;
  pipelineId: string;
  label?: string;
};

export function RunPipelineButton({ projectId, pipelineId, label = "Run" }: RunPipelineButtonProps) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    setError(null);
    try {
      setLoading(true);
      const res = await apiFetch<TransformationRunResponse>(`/projects/${projectId}/pipelines/${pipelineId}/run`, {
        method: "POST",
      });
      router.push(`/projects/${projectId}/datasets/${res.dataset.id}`);
      router.refresh();
    } catch (err) {
      setError(extractErrorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col items-end gap-1">
      <Button type="button" variant="secondary" size="sm" onClick={handleRun} disabled={loading}>
        {loading ? "Running…" : label}
      </Button>
      {error ? <span className="max-w-[220px] text-right text-xs text-danger">{error}</span> : null}
    </div>
  );
}
