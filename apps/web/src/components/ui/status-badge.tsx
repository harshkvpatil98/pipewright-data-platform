import { titleCase } from "@/lib/format";
import { cx } from "@/lib/utils";

const badgeToneMap: Record<string, string> = {
  active: "border-success-line bg-success-soft text-success",
  ready: "border-success-line bg-success-soft text-success",
  draft: "border-warning-line bg-warning-soft text-warning",
  pending: "border-warning-line bg-warning-soft text-warning",
  processing: "border-info-line bg-info-soft text-info",
  archived: "border-line bg-surface-2 text-ink-2",
  disabled: "border-line bg-surface-2 text-ink-2",
  registered: "border-accent-line bg-accent-soft text-accent",
  failed: "border-danger-line bg-danger-soft text-danger",
};

type StatusBadgeProps = {
  value: string;
  className?: string;
};

export function StatusBadge({ value, className }: StatusBadgeProps) {
  return (
    <span
      className={cx(
        "inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium uppercase tracking-[0.18em]",
        badgeToneMap[value] ?? "border-line bg-surface-2 text-ink",
        className,
      )}
    >
      {titleCase(value)}
    </span>
  );
}
