"use client";

import { useState } from "react";

import { Button } from "@platform/shared-ui";

type CopyFieldProps = {
  label: string;
  value: string;
};

export function CopyField({ label, value }: CopyFieldProps) {
  const [state, setState] = useState<"idle" | "copied" | "error">("idle");

  async function onCopy() {
    try {
      await navigator.clipboard.writeText(value);
      setState("copied");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("error");
      setTimeout(() => setState("idle"), 2500);
    }
  }

  return (
    <div className="flex flex-col gap-2 rounded-xl border border-line bg-surface px-3 py-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <div className="text-[10px] uppercase tracking-[0.16em] text-muted">{label}</div>
        <code className="mt-1 block break-all text-xs text-ink">{value}</code>
      </div>
      <Button type="button" variant="secondary" size="sm" className="shrink-0" onClick={() => void onCopy()}>
        {state === "copied" ? "Copied" : state === "error" ? "Copy failed" : "Copy"}
      </Button>
    </div>
  );
}
