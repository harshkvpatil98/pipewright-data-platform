import { cx } from "./internal/cx";

type StatTileProps = {
  label: string;
  value: string;
  caption?: string;
  /** Colour the number when it calls for attention. */
  tone?: "neutral" | "success" | "warning" | "danger";
};

const TONES: Record<NonNullable<StatTileProps["tone"]>, string> = {
  neutral: "text-ink",
  success: "text-success",
  warning: "text-warning",
  danger: "text-danger",
};

/** One number that drives an action, with what it counts. Use only where the number matters (A0, S4). */
export function StatTile({ label, value, caption, tone = "neutral" }: StatTileProps) {
  return (
    <div className="rounded-[24px] border border-line bg-[color:var(--panel)] px-5 py-5 shadow-[var(--shadow-lg)]">
      <div className="text-[13px] font-medium text-ink-3">{label}</div>
      <div className={cx("mt-3 text-3xl font-semibold tracking-tight", TONES[tone])}>{value}</div>
      {caption ? <div className="mt-2 text-sm text-ink-3">{caption}</div> : null}
    </div>
  );
}
