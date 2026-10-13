import { cx } from "./internal/cx";

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "md";
};

const variantClasses: Record<NonNullable<ButtonProps["variant"]>, string> = {
  primary:
    "bg-[color:var(--accent)] text-accent-ink shadow-[var(--shadow-glow)] hover:brightness-110",
  secondary:
    "border border-line bg-surface-2 text-ink hover:border-line-strong hover:bg-surface-2",
  ghost: "text-ink-2 hover:bg-surface-2 hover:text-ink",
  danger: "bg-danger text-danger-ink hover:bg-danger",
};

const sizeClasses: Record<NonNullable<ButtonProps["size"]>, string> = {
  sm: "h-9 px-3 text-sm",
  md: "h-11 px-4 text-sm",
};

/**
 * The button look, for things that navigate rather than act: a `<Link>` that
 * should read as "Go to Home" uses this instead of hand-rolling a pill, so a
 * link and a button side by side are the same shape.
 */
export function buttonClassName(
  variant: NonNullable<ButtonProps["variant"]> = "primary",
  size: NonNullable<ButtonProps["size"]> = "md",
  className?: string,
): string {
  return cx(
    // `saturate-0` alongside the fade because opacity alone is theme-blind:
    // half-strength bright teal on a near-black ground still reads as an
    // active button, while half-strength dark teal on white correctly
    // washes out. Desaturating removes the "this is live" signal in both.
    "inline-flex shrink-0 items-center justify-center gap-2 whitespace-nowrap rounded-xl font-medium transition duration-200 disabled:cursor-not-allowed disabled:opacity-50 disabled:saturate-0",
    variantClasses[variant],
    sizeClasses[size],
    className,
  );
}

export function Button({
  className,
  variant = "primary",
  size = "md",
  type = "button",
  ...props
}: ButtonProps) {
  return <button type={type} className={buttonClassName(variant, size, className)} {...props} />;
}
