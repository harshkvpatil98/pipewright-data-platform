import type { ReactNode } from "react";

export function OperationalLoading({ message = "Loading…" }: { message?: string }) {
  return (
    <div className="rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink-2">
      <div className="flex items-center gap-3">
        <span className="inline-flex h-2.5 w-2.5 rounded-full bg-accent" aria-hidden />
        <span>{message}</span>
      </div>
    </div>
  );
}

type OperationalErrorProps = {
  title?: string;
  message: string;
  hint?: ReactNode;
};

export function OperationalError({ title = "Something went wrong", message, hint }: OperationalErrorProps) {
  return (
    <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-danger">{message}</p>
      {hint ? <div className="mt-2 text-xs text-danger">{hint}</div> : null}
    </div>
  );
}

type OperationalEmptyProps = {
  title?: string;
  description: string;
};

export function OperationalEmpty({ title, description }: OperationalEmptyProps) {
  return (
    <div className="rounded-2xl border border-dashed border-line bg-surface px-4 py-6 text-sm text-ink-3">
      {title ? <p className="font-medium text-ink">{title}</p> : null}
      <p className={title ? "mt-2 leading-6" : "leading-6"}>{description}</p>
    </div>
  );
}
