import { cx } from "./internal/cx";

type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement>;

export function Textarea({ className, ...props }: TextareaProps) {
  return (
    <textarea
      className={cx(
        "min-h-[120px] w-full rounded-xl border border-line bg-sunken px-3 py-3 text-sm text-ink outline-none transition placeholder:text-muted focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]",
        className,
      )}
      {...props}
    />
  );
}
