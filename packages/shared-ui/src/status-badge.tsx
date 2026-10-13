import { Badge, type BadgeTone } from "./badge";

const STATUS_TONES: Record<string, BadgeTone> = {
  active: "success",
  ready: "success",
  succeeded: "success",
  passed: "success",
  healthy: "success",
  draft: "warning",
  pending: "warning",
  partially_failed: "warning",
  queued: "accent",
  registered: "accent",
  processing: "info",
  running: "info",
  archived: "neutral",
  disabled: "neutral",
  cancelled: "neutral",
  skipped: "neutral",
  failed: "danger",
};

/** The tone a stored status reads in. Unknown statuses are neutral. */
export function statusTone(value: string): BadgeTone {
  return STATUS_TONES[value.toLowerCase()] ?? "neutral";
}

/** "partially_failed" reads as "Partially failed": sentence case, per the voice guide. */
export function sentenceCase(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

type StatusBadgeProps = {
  value: string;
  /** What to show instead of the status in sentence case. */
  label?: string;
  className?: string;
};

/** A run's, a check's or an object's state, coloured by what it means. */
export function StatusBadge({ value, label, className }: StatusBadgeProps) {
  return (
    <Badge tone={statusTone(value)} className={className}>
      {label ?? sentenceCase(value)}
    </Badge>
  );
}
