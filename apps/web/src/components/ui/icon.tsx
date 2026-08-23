/**
 * Inline icon set.
 *
 * Hand-drawn on a 24x24 grid with a 1.7 stroke so every glyph shares the same
 * optical weight. Inlining them avoids shipping an icon package and keeps the
 * icons themable -- they inherit `currentColor`.
 */

export type IconName =
  | "home"
  | "database"
  | "table"
  | "transform"
  | "shield"
  | "drift"
  | "clock"
  | "send"
  | "bell"
  | "activity"
  | "search"
  | "plus"
  | "play"
  | "check"
  | "close"
  | "chevronRight"
  | "chevronDown"
  | "chevronLeft"
  | "arrowRight"
  | "filter"
  | "sort"
  | "columns"
  | "merge"
  | "sigma"
  | "grid"
  | "trash"
  | "settings"
  | "help"
  | "sparkles"
  | "warning"
  | "info"
  | "panelRight"
  | "menu"
  | "download"
  | "refresh"
  | "book";

const PATHS: Record<IconName, React.ReactNode> = {
  home: <path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4v-6H9v6H5a1 1 0 0 1-1-1z" />,
  database: (
    <>
      <ellipse cx="12" cy="6" rx="7" ry="3" />
      <path d="M5 6v12c0 1.7 3.1 3 7 3s7-1.3 7-3V6" />
      <path d="M5 12c0 1.7 3.1 3 7 3s7-1.3 7-3" />
    </>
  ),
  table: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M3 9.5h18M9 9.5V20" />
    </>
  ),
  transform: (
    <>
      <path d="M4 7h9a4 4 0 0 1 4 4v1" />
      <path d="m14 4 3 3-3 3" />
      <path d="M20 17h-9a4 4 0 0 1-4-4v-1" />
      <path d="m10 20-3-3 3-3" />
    </>
  ),
  shield: <path d="M12 3.5 5 6.2V12c0 4.2 2.9 7.4 7 8.5 4.1-1.1 7-4.3 7-8.5V6.2z" />,
  drift: (
    <>
      <path d="M3 17c3 0 3-6 6-6s3 6 6 6 3-6 6-6" />
      <path d="M3 7.5h6M15 7.5h6" strokeDasharray="2 2" />
    </>
  ),
  clock: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7v5.2l3.2 1.9" />
    </>
  ),
  send: <path d="M20.5 3.5 3.8 10.2c-.7.3-.7 1.3.1 1.5l6.4 1.9 1.9 6.4c.2.8 1.2.8 1.5.1z" />,
  bell: (
    <>
      <path d="M6.5 10a5.5 5.5 0 0 1 11 0c0 4 1.5 5.5 1.5 5.5H5S6.5 14 6.5 10" />
      <path d="M10.2 19a2 2 0 0 0 3.6 0" />
    </>
  ),
  activity: <path d="M3 12.5h4l2.5-7 4 14 2.5-7h5" />,
  search: (
    <>
      <circle cx="11" cy="11" r="6.5" />
      <path d="m16 16 4.5 4.5" />
    </>
  ),
  plus: <path d="M12 5v14M5 12h14" />,
  play: <path d="M8 5.5v13l10-6.5z" />,
  check: <path d="m5 12.5 4.5 4.5L19 7.5" />,
  close: <path d="m6 6 12 12M18 6 6 18" />,
  chevronRight: <path d="m9.5 5.5 6.5 6.5-6.5 6.5" />,
  chevronDown: <path d="m5.5 9.5 6.5 6.5 6.5-6.5" />,
  chevronLeft: <path d="m14.5 5.5-6.5 6.5 6.5 6.5" />,
  arrowRight: <path d="M4 12h15m0 0-5.5-5.5M19 12l-5.5 5.5" />,
  filter: <path d="M4 5.5h16l-6.2 7.3V19l-3.6 1.8v-8z" />,
  sort: <path d="M7 4v16m0 0-3-3m3 3 3-3M17 20V4m0 0-3 3m3-3 3 3" />,
  columns: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M9.5 4v16M14.5 4v16" />
    </>
  ),
  merge: (
    <>
      <path d="M5 4v4c0 2 1.5 4 4 4h6" />
      <path d="M5 20v-4c0-2 1.5-4 4-4" />
      <path d="m12 9 3 3-3 3" />
      <path d="M15 12h4" />
    </>
  ),
  sigma: <path d="M18 5H6l6 7-6 7h12" />,
  grid: (
    <>
      <rect x="3" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="3" width="7.5" height="7.5" rx="1.5" />
      <rect x="3" y="13.5" width="7.5" height="7.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1.5" />
    </>
  ),
  trash: (
    <>
      <path d="M4.5 6.5h15M9.5 6.5V4.8c0-.7.6-1.3 1.3-1.3h2.4c.7 0 1.3.6 1.3 1.3v1.7" />
      <path d="M6.5 6.5 7.4 19a1.5 1.5 0 0 0 1.5 1.4h6.2a1.5 1.5 0 0 0 1.5-1.4l.9-12.5" />
    </>
  ),
  settings: (
    <>
      <circle cx="12" cy="12" r="3" />
      <path d="M12 2.5v2.2M12 19.3v2.2M21.5 12h-2.2M4.7 12H2.5M18.7 5.3l-1.6 1.6M6.9 17.1l-1.6 1.6M18.7 18.7l-1.6-1.6M6.9 6.9 5.3 5.3" />
    </>
  ),
  help: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M9.6 9.4a2.5 2.5 0 1 1 3.3 2.4c-.6.2-.9.7-.9 1.3v.4" />
      <path d="M12 17h.01" />
    </>
  ),
  sparkles: (
    <>
      <path d="M12 3.5 13.6 8l4.5 1.6-4.5 1.6L12 15.7l-1.6-4.5L5.9 9.6 10.4 8z" />
      <path d="M18.5 15.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z" />
    </>
  ),
  warning: (
    <>
      <path d="M10.6 4.2 2.9 17.5A1.6 1.6 0 0 0 4.3 20h15.4a1.6 1.6 0 0 0 1.4-2.5L13.4 4.2a1.6 1.6 0 0 0-2.8 0" />
      <path d="M12 9.5v4M12 17h.01" />
    </>
  ),
  info: (
    <>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 11v5.5M12 7.8h.01" />
    </>
  ),
  panelRight: (
    <>
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16" />
    </>
  ),
  menu: <path d="M4 7h16M4 12h16M4 17h16" />,
  download: <path d="M12 4v10m0 0-4-4m4 4 4-4M5 19h14" />,
  refresh: (
    <>
      <path d="M20 12a8 8 0 1 1-2.6-5.9" />
      <path d="M20 4.5V10h-5.5" />
    </>
  ),
  book: (
    <>
      <path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H10a2.5 2.5 0 0 1 2 1 2.5 2.5 0 0 1 2-1h4.5A1.5 1.5 0 0 1 20 5.5v12a1.5 1.5 0 0 1-1.5 1.5H14a2.5 2.5 0 0 0-2 1 2.5 2.5 0 0 0-2-1H5.5A1.5 1.5 0 0 1 4 17.5z" />
      <path d="M12 5v15" />
    </>
  ),
};

const FILLED = new Set<IconName>(["play", "send", "shield", "sparkles", "filter"]);

type IconProps = {
  name: IconName;
  size?: number;
  className?: string;
  strokeWidth?: number;
};

export function Icon({ name, size = 18, className, strokeWidth = 1.7 }: IconProps) {
  const filled = FILLED.has(name);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={filled ? "currentColor" : "none"}
      stroke={filled ? "none" : "currentColor"}
      strokeWidth={filled ? undefined : strokeWidth}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      {PATHS[name]}
    </svg>
  );
}
