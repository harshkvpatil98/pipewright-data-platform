import { cx } from "./internal/cx";

const badgeToneMap: Record<string, string> = {
  active: "border-success-line bg-success-soft text-success",
  ready: "border-success-line bg-success-soft text-success",
  succeeded: "border-success-line bg-success-soft text-success",
  passed: "border-success-line bg-success-soft text-success",
  draft: "border-warning-line bg-warning-soft text-warning",
  pending: "border-warning-line bg-warning-soft text-warning",
  queued: "border-accent-line bg-accent-soft text-accent",
  processing: "border-info-line bg-info-soft text-info",
  running: "border-info-line bg-info-soft text-info",
  archived: "border-line bg-surface-2 text-ink-2",
  disabled: "border-line bg-surface-2 text-ink-2",
  registered: "border-accent-line bg-accent-soft text-accent",
  failed: "border-danger-line bg-danger-soft text-danger",
};

/** "partially_failed" reads as "Partially failed": sentence case, per the voice guide. */
function sentenceCase(value: string): string {
  const spaced = value.replace(/[_-]+/g, " ").trim().toLowerCase();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

type StatusBadgeProps = {
  value: string;
  className?: string;
};

export function StatusBadge({ value, className }: StatusBadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[12px] font-medium",
        badgeToneMap[value] ?? "border-line bg-surface-2 text-ink",
        className,
      )}
    >
      {sentenceCase(value)}
    </span>
  );
}
