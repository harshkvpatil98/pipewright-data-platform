import { describe, expect, it } from "vitest";

import {
  applyDensity,
  applyTheme,
  DEFAULT_PREFERENCES,
  DENSITIES,
  isDensity,
  isTheme,
  NO_FLASH_SCRIPT,
  THEMES,
} from "@/lib/theme/preferences";

/** Minimal stand-in for <html>; the module only touches these two methods. */
function fakeRoot() {
  const attributes = new Map<string, string>();
  return {
    attributes,
    setAttribute: (name: string, value: string) => void attributes.set(name, value),
    removeAttribute: (name: string) => void attributes.delete(name),
  } as unknown as HTMLElement & { attributes: Map<string, string> };
}

describe("theme application", () => {
  it("removes the attribute for 'system' rather than setting it", () => {
    // This IS the mechanism. With nothing stamped, the CSS falls through to
    // @media (prefers-color-scheme: dark) and the page tracks the OS live.
    // Setting data-theme="system" would match no rule and strand the page in
    // whatever the bare :root block happens to define.
    const root = fakeRoot();
    root.setAttribute("data-theme", "dark");

    applyTheme("system", root);

    expect(root.attributes.has("data-theme")).toBe(false);
  });

  it.each(["light", "dark"] as const)("stamps an explicit %s choice", (theme) => {
    const root = fakeRoot();
    applyTheme(theme, root);
    expect(root.attributes.get("data-theme")).toBe(theme);
  });

  it("switches cleanly between explicit themes", () => {
    const root = fakeRoot();
    applyTheme("dark", root);
    applyTheme("light", root);
    expect(root.attributes.get("data-theme")).toBe("light");
  });

  it("treats comfortable density as the unstamped default", () => {
    const root = fakeRoot();
    applyDensity("dense", root);
    applyDensity("comfortable", root);
    expect(root.attributes.has("data-density")).toBe(false);
  });

  it.each(["compact", "dense"] as const)("stamps %s density", (density) => {
    const root = fakeRoot();
    applyDensity(density, root);
    expect(root.attributes.get("data-density")).toBe(density);
  });
});

describe("preference validation", () => {
  it.each(THEMES)("accepts %s as a theme", (theme) => {
    expect(isTheme(theme)).toBe(true);
  });

  it.each(DENSITIES)("accepts %s as a density", (density) => {
    expect(isDensity(density)).toBe(true);
  });

  it.each([null, undefined, 42, "solarized", "", "SYSTEM"])(
    "rejects %s as a theme",
    (value) => {
      expect(isTheme(value)).toBe(false);
    }
  );

  it("defaults to following the system", () => {
    // Not light and not dark: only "system" stays correct when someone changes
    // their OS appearance setting.
    expect(DEFAULT_PREFERENCES.theme).toBe("system");
  });
});

describe("the pre-paint script", () => {
  it("only ever applies values the stylesheet defines", () => {
    // It is inlined into <head> unescaped, so it must not interpolate anything
    // it read. It compares against literals and writes only those literals.
    expect(NO_FLASH_SCRIPT).toContain('"light"');
    expect(NO_FLASH_SCRIPT).toContain('"dark"');
    expect(NO_FLASH_SCRIPT).toContain('"compact"');
    expect(NO_FLASH_SCRIPT).toContain('"dense"');
  });

  it("compares against literals before writing anything", () => {
    // The write is guarded by an equality check against known values, so a
    // stored string can never reach setAttribute unrecognised. The behavioural
    // tests below are what actually prove this; this one documents the shape.
    expect(NO_FLASH_SCRIPT).toMatch(/t==="light"\|\|t==="dark"/);
    expect(NO_FLASH_SCRIPT).toMatch(/d==="compact"\|\|d==="dense"/);
  });

  it("survives localStorage throwing", () => {
    // Private browsing makes localStorage throw on some browsers. A theme
    // preference is never worth a blank page.
    expect(NO_FLASH_SCRIPT).toContain("try{");
    expect(NO_FLASH_SCRIPT).toContain("catch");
  });

  it("contains no closing script tag that would end the inline block early", () => {
    expect(NO_FLASH_SCRIPT.toLowerCase()).not.toContain("</script");
  });

  it("actually applies the stored preference when run", () => {
    const attributes = new Map<string, string>();
    const store: Record<string, string> = { "pw.theme": "dark", "pw.density": "dense" };
    const scope = {
      localStorage: { getItem: (k: string) => store[k] ?? null },
      document: {
        documentElement: {
          setAttribute: (n: string, v: string) => void attributes.set(n, v),
        },
      },
    };
    new Function("localStorage", "document", NO_FLASH_SCRIPT)(
      scope.localStorage,
      scope.document
    );

    expect(attributes.get("data-theme")).toBe("dark");
    expect(attributes.get("data-density")).toBe("dense");
  });

  it("applies nothing when the stored theme is 'system'", () => {
    const attributes = new Map<string, string>();
    const store: Record<string, string> = { "pw.theme": "system" };
    new Function("localStorage", "document", NO_FLASH_SCRIPT)(
      { getItem: (k: string) => store[k] ?? null },
      { documentElement: { setAttribute: (n: string, v: string) => void attributes.set(n, v) } }
    );

    expect(attributes.size).toBe(0);
  });

  it("applies nothing when the stored value is junk", () => {
    const attributes = new Map<string, string>();
    const store: Record<string, string> = { "pw.theme": "'; alert(1); //" };
    new Function("localStorage", "document", NO_FLASH_SCRIPT)(
      { getItem: (k: string) => store[k] ?? null },
      { documentElement: { setAttribute: (n: string, v: string) => void attributes.set(n, v) } }
    );

    expect(attributes.size).toBe(0);
  });
});
