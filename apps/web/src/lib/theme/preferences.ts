/**
 * Theme and density preferences.
 *
 * Two stores, deliberately:
 *
 * - **localStorage** is the fast path. It is read synchronously by a script in
 *   <head> before first paint, which is the only way to avoid a flash of the
 *   wrong theme. An async fetch cannot do this; the page would paint first.
 * - **The server** is the source of truth. It is what makes the setting follow
 *   someone to another machine, and it is reconciled after login.
 */

export const THEMES = ["light", "dark", "system"] as const;
export const DENSITIES = ["comfortable", "compact", "dense"] as const;

export type Theme = (typeof THEMES)[number];
export type Density = (typeof DENSITIES)[number];

export type Preferences = { theme: Theme; density: Density };

/** "system" follows the OS and is the only value that stays correct when the OS changes. */
export const DEFAULT_PREFERENCES: Preferences = { theme: "system", density: "comfortable" };

export const THEME_STORAGE_KEY = "pw.theme";
export const DENSITY_STORAGE_KEY = "pw.density";

export function isTheme(value: unknown): value is Theme {
  return typeof value === "string" && (THEMES as readonly string[]).includes(value);
}

export function isDensity(value: unknown): value is Density {
  return typeof value === "string" && (DENSITIES as readonly string[]).includes(value);
}

/**
 * Write the preference onto <html>.
 *
 * "system" REMOVES the attribute rather than setting data-theme="system".
 * That is the whole mechanism: with nothing stamped, the CSS falls through to
 * `@media (prefers-color-scheme: dark)`, so the page tracks the OS live -- and
 * keeps tracking it if the OS setting changes while the page is open.
 */
export function applyTheme(theme: Theme, root: HTMLElement): void {
  if (theme === "system") {
    root.removeAttribute("data-theme");
  } else {
    root.setAttribute("data-theme", theme);
  }
}

/** Comfortable is the default, so it needs no attribute. */
export function applyDensity(density: Density, root: HTMLElement): void {
  if (density === "comfortable") {
    root.removeAttribute("data-density");
  } else {
    root.setAttribute("data-density", density);
  }
}

/**
 * The script that runs before first paint.
 *
 * Kept small and dependency-free because it is inlined into <head> and blocks
 * rendering. It reads localStorage only -- a fetch here would defeat the point.
 * Wrapped in try/catch because localStorage throws in private browsing on some
 * browsers, and a theme preference is never worth a blank page.
 */
export const NO_FLASH_SCRIPT = `(function(){try{
var t=localStorage.getItem(${JSON.stringify(THEME_STORAGE_KEY)});
var d=localStorage.getItem(${JSON.stringify(DENSITY_STORAGE_KEY)});
var e=document.documentElement;
if(t==="light"||t==="dark")e.setAttribute("data-theme",t);
if(d==="compact"||d==="dense")e.setAttribute("data-density",d);
}catch(_){}})();`;
