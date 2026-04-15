import type { ReactNode } from "react";

export function OperationalLoading({ message = "Loading…" }: { message?: string }) {
  return (
    <div className="rounded-2xl border border-white/8 bg-white/[0.03] px-4 py-4 text-sm text-slate-300">
      <div className="flex items-center gap-3">
        <span className="inline-flex h-2.5 w-2.5 rounded-full bg-indigo-300/80" aria-hidden />
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
    <div className="rounded-2xl border border-rose-400/25 bg-rose-500/10 px-4 py-3 text-sm text-rose-100">
      <p className="font-medium">{title}</p>
      <p className="mt-1 text-rose-200/90">{message}</p>
      {hint ? <div className="mt-2 text-xs text-rose-200/70">{hint}</div> : null}
    </div>
  );
}

type OperationalEmptyProps = {
  title?: string;
  description: string;
};

export function OperationalEmpty({ title, description }: OperationalEmptyProps) {
  return (
    <div className="rounded-2xl border border-dashed border-white/10 bg-white/[0.025] px-4 py-6 text-sm text-slate-400">
      {title ? <p className="font-medium text-slate-200">{title}</p> : null}
      <p className={title ? "mt-2 leading-6" : "leading-6"}>{description}</p>
    </div>
  );
}
