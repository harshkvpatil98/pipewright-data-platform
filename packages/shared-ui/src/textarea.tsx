import { cx } from "./internal/cx";

type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className, ...props }: TextareaProps) {
  return (
    <textarea
      className={cx(
        "min-h-[120px] w-full rounded-xl border border-white/10 bg-black/20 px-3 py-3 text-sm text-slate-100 outline-none transition placeholder:text-slate-500 focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]",
        className,
      )}
      {...props}
    />
  );
}
