type StatusBadgeProps = {
  tone?: "default" | "success" | "warning";
  children: React.ReactNode;
};

const toneClasses: Record<NonNullable<StatusBadgeProps["tone"]>, string> = {
  default: "border-info-line bg-info-soft text-info",
  success: "border-success-line bg-success-soft text-success",
  warning: "border-warning-line bg-warning-soft text-warning",
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
