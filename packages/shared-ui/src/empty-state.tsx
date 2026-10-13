import { cx } from "./internal/cx";

type EmptyStateProps = {
  title?: string;
  description: string;
  /** What to do next: an empty state offers the button, not just the advice (A0, S5). */
  action?: React.ReactNode;
  /** A page or panel with nothing in it yet, or one line inside a list that came back empty. */
  size?: "default" | "compact";
};

export function EmptyState({ title, description, action, size = "default" }: EmptyStateProps) {
  if (size === "compact") {
    return (
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-dashed border-line bg-surface px-4 py-5 text-sm text-ink-3">
        <div className="min-w-0">
          {title ? <p className="font-medium text-ink">{title}</p> : null}
          <p className={cx("leading-6", title && "mt-1")}>{description}</p>
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
    );
  }
  return (
    <div className="rounded-[24px] border border-dashed border-line bg-surface px-6 py-10 text-center">
      {title ? <h3 className="text-lg font-semibold text-ink">{title}</h3> : null}
      <p className={cx("mx-auto max-w-xl text-sm leading-6 text-ink-3", title && "mt-2")}>{description}</p>
      {action ? <div className="mt-6 flex justify-center">{action}</div> : null}
    </div>
  );
}
