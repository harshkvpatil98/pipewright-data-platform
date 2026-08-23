import { cx } from "./internal/cx";

// React 19 passes `ref` to function components as an ordinary prop, so this
// needs no forwardRef -- only the type has to say so.
type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  ref?: React.Ref<HTMLInputElement>;
};

export function Input({ className, ...props }: InputProps) {
  return (
    <input
      className={cx(
        "h-11 w-full rounded-xl border border-line bg-sunken px-3 text-sm text-ink outline-none transition placeholder:text-muted focus:border-[color:var(--accent)] focus:ring-2 focus:ring-[color:var(--accent-soft)]",
        className,
      )}
      {...props}
    />
  );
}
