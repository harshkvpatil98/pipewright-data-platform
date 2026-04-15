import { cx } from "./internal/cx";

type SelectProps = React.SelectHTMLAttributes<HTMLSelectElement>;

export function Select({ className, ...props }: SelectProps) {
  return (
    <select
      className={cx(
        "h-11 w-full rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-slate-100 outline-none transition focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]",
        className,
      )}
      {...props}
    />
  );
}
