"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { apiFetch } from "@/lib/api/client";
import { getAccessToken } from "@/lib/auth/session";
import {
  applyDensity,
  applyTheme,
  DEFAULT_PREFERENCES,
  DENSITY_STORAGE_KEY,
  isDensity,
  isTheme,
  THEME_STORAGE_KEY,
  type Density,
  type Preferences,
  type Theme,
} from "@/lib/theme/preferences";

type ThemeContextValue = Preferences & {
  setTheme: (theme: Theme) => void;
  setDensity: (density: Density) => void;
  /** What "system" currently resolves to, for UI that must name the active theme. */
  resolvedTheme: "light" | "dark";
};

const ThemeContext = createContext<ThemeContextValue | null>(null);

function readStored(): Preferences {
  if (typeof window === "undefined") return DEFAULT_PREFERENCES;
  try {
    const theme = window.localStorage.getItem(THEME_STORAGE_KEY);
    const density = window.localStorage.getItem(DENSITY_STORAGE_KEY);
    return {
      theme: isTheme(theme) ? theme : DEFAULT_PREFERENCES.theme,
      density: isDensity(density) ? density : DEFAULT_PREFERENCES.density,
    };
  } catch {
    // Private browsing can make localStorage throw. Defaults are fine.
    return DEFAULT_PREFERENCES;
  }
}

function systemPrefersDark(): boolean {
  if (typeof window === "undefined" || !window.matchMedia) return false;
  return window.matchMedia("(prefers-color-scheme: dark)").matches;
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  // Start from the defaults so the server render and the first client render
  // agree; the effect below adopts what the no-flash script already applied.
  const [preferences, setPreferences] = useState<Preferences>(DEFAULT_PREFERENCES);
  const [systemDark, setSystemDark] = useState(false);

  useEffect(() => {
    setPreferences(readStored());
    setSystemDark(systemPrefersDark());
  }, []);

  // Track the OS while the page is open. Without this, someone switching their
  // system to dark at sunset keeps looking at a light page until they reload.
  useEffect(() => {
    if (typeof window === "undefined" || !window.matchMedia) return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const onChange = (event: MediaQueryListEvent) => setSystemDark(event.matches);
    query.addEventListener("change", onChange);
    return () => query.removeEventListener("change", onChange);
  }, []);

  // Adopt the server's copy once, on load. The server wins because a local
  // change writes through immediately, so the two can only disagree when this
  // is a machine the person has not used before -- which is exactly the case
  // this is here to serve.
  useEffect(() => {
    if (!getAccessToken()) return;
    let cancelled = false;

    void apiFetch<Partial<Preferences>>("/auth/me/preferences")
      .then((remote) => {
        if (cancelled) return;
        const theme = isTheme(remote?.theme) ? remote.theme : null;
        const density = isDensity(remote?.density) ? remote.density : null;
        if (theme === null && density === null) return;

        setPreferences((current) => ({
          theme: theme ?? current.theme,
          density: density ?? current.density,
        }));
        if (theme !== null) {
          applyTheme(theme, document.documentElement);
          try {
            window.localStorage.setItem(THEME_STORAGE_KEY, theme);
          } catch {
            // Session-only is acceptable.
          }
        }
        if (density !== null) {
          applyDensity(density, document.documentElement);
          try {
            window.localStorage.setItem(DENSITY_STORAGE_KEY, density);
          } catch {
            // Session-only is acceptable.
          }
        }
      })
      .catch(() => undefined);

    return () => {
      cancelled = true;
    };
  }, []);

  const persist = useCallback((next: Partial<Preferences>) => {
    // Signed out, there is nobody to save against -- the local copy is the
    // whole story until they log in.
    if (!getAccessToken()) return;
    // Fire-and-forget: the preference is already applied locally, and failing
    // to reach the server is not a reason to refuse someone a dark theme.
    void apiFetch("/auth/me/preferences", {
      method: "PATCH",
      body: JSON.stringify(next),
    }).catch(() => undefined);
  }, []);

  const setTheme = useCallback(
    (theme: Theme) => {
      setPreferences((current) => ({ ...current, theme }));
      applyTheme(theme, document.documentElement);
      try {
        window.localStorage.setItem(THEME_STORAGE_KEY, theme);
      } catch {
        // Preference still applies for this session.
      }
      persist({ theme });
    },
    [persist]
  );

  const setDensity = useCallback(
    (density: Density) => {
      setPreferences((current) => ({ ...current, density }));
      applyDensity(density, document.documentElement);
      try {
        window.localStorage.setItem(DENSITY_STORAGE_KEY, density);
      } catch {
        // Preference still applies for this session.
      }
      persist({ density });
    },
    [persist]
  );

  const value = useMemo<ThemeContextValue>(
    () => ({
      ...preferences,
      setTheme,
      setDensity,
      resolvedTheme:
        preferences.theme === "system" ? (systemDark ? "dark" : "light") : preferences.theme,
    }),
    [preferences, setTheme, setDensity, systemDark]
  );

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme(): ThemeContextValue {
  const context = useContext(ThemeContext);
  if (context === null) {
    throw new Error("useTheme must be used inside a ThemeProvider.");
  }
  return context;
}
