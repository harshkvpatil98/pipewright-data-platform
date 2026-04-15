import type { ServiceHealthStatus } from "@platform/shared-types";

export type StatusTone = "success" | "warning" | "danger" | "neutral";

export function serviceHealthTone(status: ServiceHealthStatus): StatusTone {
  if (status === "healthy") {
    return "success";
  }
  if (status === "degraded") {
    return "warning";
  }
  return "danger";
}

export function toneClasses(tone: StatusTone): string {
  switch (tone) {
    case "success":
      return "border-emerald-400/30 bg-emerald-500/10 text-emerald-100";
    case "warning":
      return "border-amber-400/30 bg-amber-500/10 text-amber-100";
    case "danger":
      return "border-rose-400/30 bg-rose-500/10 text-rose-100";
    default:
      return "border-slate-500/30 bg-slate-500/10 text-slate-200";
  }
}
