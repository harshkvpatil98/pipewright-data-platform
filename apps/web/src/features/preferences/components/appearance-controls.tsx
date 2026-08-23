"use client";

import { useTheme } from "@/components/providers/theme-provider";
import { Tooltip } from "@/components/ui/tooltip";
import { DENSITIES, THEMES, type Density, type Theme } from "@/lib/theme/preferences";
import { cx } from "@/lib/utils";

/* Icons are hand-drawn SVG: the project carries no icon library, and three
   glyphs are not a reason to start. `currentColor` lets them inherit state. */

function SunIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <circle cx="8" cy="8" r="3.1" />
      <path strokeLinecap="round" d="M8 1.4v1.6M8 13v1.6M14.6 8H13M3 8H1.4M12.7 3.3l-1.1 1.1M4.4 11.6l-1.1 1.1M12.7 12.7l-1.1-1.1M4.4 4.4L3.3 3.3" />
    </svg>
  );
}

function MoonIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <path strokeLinejoin="round" d="M13.4 9.6A5.8 5.8 0 0 1 6.4 2.6a5.9 5.9 0 1 0 7 7Z" />
    </svg>
  );
}

function SystemIcon() {
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      <rect x="1.8" y="2.6" width="12.4" height="8.4" rx="1.3" />
      <path strokeLinecap="round" d="M5.6 13.6h4.8" />
    </svg>
  );
}

/** Row height shrinks as density increases, so the icon shows the idea directly. */
function DensityIcon({ rows }: { rows: number }) {
  const gap = rows === 2 ? 4.6 : rows === 3 ? 3.4 : 2.6;
  const top = 8 - ((rows - 1) * gap) / 2;
  return (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.4" aria-hidden="true">
      {Array.from({ length: rows }, (_, index) => (
        <path key={index} strokeLinecap="round" d={`M2.8 ${top + index * gap}h10.4`} />
      ))}
    </svg>
  );
}

const THEME_META: Record<Theme, { label: string; icon: React.ReactNode; hint: string }> = {
  light: { label: "Light", icon: <SunIcon />, hint: "Always light" },
  dark: { label: "Dark", icon: <MoonIcon />, hint: "Always dark" },
  system: { label: "System", icon: <SystemIcon />, hint: "Follow your device setting" },
};

const DENSITY_META: Record<Density, { label: string; icon: React.ReactNode; hint: string }> = {
  comfortable: { label: "Comfortable", icon: <DensityIcon rows={2} />, hint: "Roomy spacing" },
  compact: { label: "Compact", icon: <DensityIcon rows={3} />, hint: "More on screen" },
  dense: { label: "Dense", icon: <DensityIcon rows={4} />, hint: "Maximum rows per screen" },
};

function Segmented<T extends string>({
  legend,
  description,
  options,
  value,
  onChange,
  meta,
}: {
  legend: string;
  description: string;
  options: readonly T[];
  value: T;
  onChange: (next: T) => void;
  meta: Record<T, { label: string; icon: React.ReactNode; hint: string }>;
}) {
  return (
    <fieldset className="min-w-0">
      <legend className="text-[13px] font-semibold text-ink">{legend}</legend>
      <p className="mt-1 mb-3 text-[12.5px] text-muted">{description}</p>
      <div
        role="radiogroup"
        aria-label={legend}
        // A grid, not flex-wrap: three equal columns keep the options on one
        // row at any width, where wrapping stranded the last one across its own
        // full-width row and made it look selected.
        className="grid grid-cols-3 gap-1.5 rounded-2xl border border-line bg-surface-2 p-1.5"
      >
        {options.map((option) => {
          const isActive = option === value;
          return (
            <button
              key={option}
              type="button"
              role="radio"
              aria-checked={isActive}
              title={meta[option].hint}
              onClick={() => onChange(option)}
              className={cx(
                "flex items-center justify-center gap-1.5 rounded-xl px-2 py-2 text-[12.5px] font-medium",
                "transition duration-[var(--duration-fast)] ease-[var(--ease-out)]",
                isActive
                  ? "bg-[color:var(--accent)] text-accent-ink shadow-[var(--shadow-sm)]"
                  : "text-ink-2 hover:bg-surface hover:text-ink",
              )}
            >
              {meta[option].icon}
              <span>{meta[option].label}</span>
            </button>
          );
        })}
      </div>
    </fieldset>
  );
}

/** Full appearance controls, for the settings page. */
export function AppearanceControls() {
  const { theme, density, setTheme, setDensity } = useTheme();

  return (
    <div className="grid gap-6 sm:grid-cols-2">
      <Segmented
        legend="Theme"
        description="System follows your device, and keeps following it if you change that setting."
        options={THEMES}
        value={theme}
        onChange={setTheme}
        meta={THEME_META}
      />
      <Segmented
        legend="Density"
        description="How much vertical space rows and panels take. Dense fits the most on screen."
        options={DENSITIES}
        value={density}
        onChange={setDensity}
        meta={DENSITY_META}
      />
    </div>
  );
}

/**
 * Compact theme cycle for the top bar.
 *
 * Cycles rather than opening a menu: three states in a toolbar, where a popover
 * would cost more clicks than it saves. The tooltip names both the current
 * state and what pressing it will do, because a lone icon cannot say either.
 */
export function ThemeToggle({ className }: { className?: string }) {
  const { theme, resolvedTheme, setTheme } = useTheme();
  const order: Theme[] = ["light", "dark", "system"];
  const next = order[(order.indexOf(theme) + 1) % order.length];
  const current =
    theme === "system" ? `System (currently ${resolvedTheme})` : THEME_META[theme].label;

  return (
    <Tooltip label={`Theme: ${current}`} side="bottom">
      <button
        type="button"
        onClick={() => setTheme(next)}
        aria-label={`Theme: ${current}. Switch to ${THEME_META[next].label}.`}
        className={cx(
          "flex h-9 w-9 items-center justify-center rounded-xl text-ink-3",
          "transition duration-[var(--duration-fast)] ease-[var(--ease-out)]",
          "hover:bg-surface-2 hover:text-ink",
          className,
        )}
      >
        {THEME_META[theme].icon}
      </button>
    </Tooltip>
  );
}
