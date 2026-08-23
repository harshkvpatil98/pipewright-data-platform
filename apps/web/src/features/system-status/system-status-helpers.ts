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
      return "border-success-line bg-success-soft text-success";
    case "warning":
      return "border-warning-line bg-warning-soft text-warning";
    case "danger":
      return "border-danger-line bg-danger-soft text-danger";
    default:
      return "border-line bg-surface-2 text-ink";
  }
}
