import { titleCase } from "@/lib/format";
import { cx } from "@/lib/utils";

const badgeToneMap: Record<string, string> = {
  active: "border-emerald-400/20 bg-emerald-400/12 text-emerald-200",
  ready: "border-emerald-400/20 bg-emerald-400/12 text-emerald-200",
  draft: "border-amber-300/20 bg-amber-300/12 text-amber-200",
  pending: "border-amber-300/20 bg-amber-300/12 text-amber-200",
  processing: "border-sky-400/20 bg-sky-400/12 text-sky-200",
  archived: "border-slate-400/20 bg-slate-400/12 text-slate-300",
  disabled: "border-slate-400/20 bg-slate-400/12 text-slate-300",
  registered: "border-violet-400/20 bg-violet-400/12 text-violet-200",
  failed: "border-rose-400/20 bg-rose-400/12 text-rose-200",
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
        badgeToneMap[value] ?? "border-white/10 bg-white/[0.06] text-slate-200",
        className,
      )}
    >
      {titleCase(value)}
    </span>
  );
}
