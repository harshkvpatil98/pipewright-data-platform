import { cx } from "./internal/cx";

type InputProps = React.InputHTMLAttributes<HTMLInputElement>;

export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cx(
        "h-11 w-full rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]",
        className,
      )}
      {...props}
    />
  );
}
