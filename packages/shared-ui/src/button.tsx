import { cx } from "./internal/cx";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
};

const variantClasses: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary:
    "bg-[color:var(--accent)] text-white shadow-[0_12px_32px_rgba(79,70,229,0.22)] hover:brightness-110",
  secondary:
    "border border-white/10 bg-white/[0.06] text-slate-100 hover:border-white/20 hover:bg-white/[0.09]",
  ghost: "text-slate-300 hover:bg-white/[0.06] hover:text-white",
  danger: "bg-rose-500/90 text-white hover:bg-rose-500",
};

const sizeClasses: Record<NonNullable<ButtonProps["size"]>, string> = {
  sm: "h-9 px-3 text-sm",
  md: "h-11 px-4 text-sm",
};

export function Button({
  className,
  variant = "primary",
  size = "md",
  type = "button",
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cx(
        "inline-flex items-center justify-center gap-2 rounded-xl font-medium transition duration-200 disabled:cursor-not-allowed disabled:opacity-50",
        variantClasses[variant],
        sizeClasses[size],
        className,
      )}
      {...props}
    />
  );
}
