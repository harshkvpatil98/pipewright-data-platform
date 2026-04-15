type StatusBadgeProps = {
  tone?: "default" | "success" | "warning";
  children: React.ReactNode;
};

const toneClasses: Record<NonNullable<StatusBadgeProps["tone"]>, string> = {
  default: "border-sky-400/20 bg-sky-400/10 text-sky-200",
  success: "border-emerald-400/20 bg-emerald-400/10 text-emerald-200",
  warning: "border-amber-400/20 bg-amber-400/10 text-amber-200",
};

export function StatusBadge({ tone = "default", children }: StatusBadgeProps) {
  return (
    <span
      className={`rounded-full border px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] ${toneClasses[tone]}`}
    >
      {children}
    </span>
  );
}
