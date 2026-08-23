"use client";

import { useId } from "react";

import { cx } from "./internal/cx";

type LogoMarkProps = {
  /** Rendered pixel size of the square mark. */
  size?: number;
  className?: string;
  /**
   * "badge" renders the glyph on a filled gradient tile, which holds its weight
   * at small sizes. "glyph" renders the strokes alone for tight or monochrome
   * placements.
   */
  variant?: "badge" | "glyph";
  title?: string;
};

/**
 * The Pipewright mark: two upstream feeds converging through a junction into a
 * single downstream trunk -- the shape of an extract/transform/load flow.
 */
export function LogoMark({ size = 36, className, variant = "badge", title }: LogoMarkProps) {
  const gradientId = useId();
  const isBadge = variant === "badge";
  // The glyph sits ON the accent fill, so it takes the accent's own ink token.
  // Hardcoded white worked on the old dark-only badge and is only ~2:1 against
  // the brighter accent used in dark mode.
  const strokeColor = isBadge ? "var(--accent-ink)" : `url(#${gradientId})`;

  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      role={title ? "img" : "presentation"}
      aria-hidden={title ? undefined : true}
      aria-label={title}
      className={className}
    >
      {title ? <title>{title}</title> : null}
      <defs>
        <linearGradient id={gradientId} x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop stopColor="var(--brand-gradient-from)" />
          <stop offset="1" stopColor="var(--brand-gradient-to)" />
        </linearGradient>
      </defs>

      {isBadge ? <rect width="40" height="40" rx="11" fill={`url(#${gradientId})`} /> : null}

      {/* upstream feeds */}
      <path
        d="M9 13h6a5 5 0 0 1 5 5v2"
        stroke={strokeColor}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <path
        d="M9 27h6a5 5 0 0 0 5-5v-2"
        stroke={strokeColor}
        strokeWidth="3"
        strokeLinecap="round"
        strokeLinejoin="round"
        opacity={isBadge ? 0.72 : 0.6}
      />
      {/* downstream trunk */}
      <path d="M20 20h11" stroke={strokeColor} strokeWidth="3" strokeLinecap="round" />
      {/* junction */}
      <circle cx="20" cy="20" r="3.6" fill={strokeColor} />
    </svg>
  );
}

type LogoProps = {
  /** Product name; kept as a prop so the brand string stays centrally owned. */
  name: string;
  tagline?: string;
  size?: number;
  className?: string;
  variant?: "badge" | "glyph";
};

/** Mark plus wordmark, for headers, sidebars, and auth screens. */
export function Logo({ name, tagline, size = 36, className, variant = "badge" }: LogoProps) {
  return (
    <span className={cx("inline-flex items-center gap-3", className)}>
      <LogoMark size={size} variant={variant} title={name} />
      <span className="flex flex-col leading-none">
        <span className="text-[17px] font-semibold tracking-tight text-ink">{name}</span>
        {tagline ? (
          <span className="mt-1.5 whitespace-nowrap text-[10px] uppercase tracking-[0.2em] text-muted">
            {tagline}
          </span>
        ) : null}
      </span>
    </span>
  );
}
