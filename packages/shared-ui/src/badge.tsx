import { cx } from "./internal/cx";

export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

const TONES: Record<BadgeTone, string> = {
  neutral: "border-line bg-surface-2 text-ink-2",
  accent: "border-accent-line bg-accent-soft text-accent",
  success: "border-success-line bg-success-soft text-success",
  warning: "border-warning-line bg-warning-soft text-warning",
  danger: "border-danger-line bg-danger-soft text-danger",
  info: "border-info-line bg-info-soft text-info",
};

type BadgeProps = {
  tone?: BadgeTone;
  children: React.ReactNode;
  className?: string;
  /** The longer explanation, on hover. */
  title?: string;
};

/** A short label beside something: its state, its kind, a count. */
export function Badge({ tone = "neutral", children, className, title }: BadgeProps) {
  return (
    <span
      title={title}
      className={cx(
        "inline-flex items-center gap-1 whitespace-nowrap rounded-full border px-2 py-0.5 text-[12px] font-medium",
        TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}
