import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { contrastRatio, WCAG_AA_NORMAL, WCAG_AA_LARGE } from "@/lib/theme/contrast";

const CSS = readFileSync(
  fileURLToPath(new URL("../../app/globals.css", import.meta.url)),
  "utf8"
);

/** Pull the `--name: #hex;` declarations out of one rule body. */
function paletteOf(selector: string): Record<string, string> {
  const start = CSS.indexOf(selector);
  if (start === -1) throw new Error(`Selector not found in globals.css: ${selector}`);
  const open = CSS.indexOf("{", start);
  // Walk braces so a nested block cannot end the match early.
  let depth = 0;
  let end = open;
  for (let i = open; i < CSS.length; i += 1) {
    if (CSS[i] === "{") depth += 1;
    if (CSS[i] === "}") {
      depth -= 1;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const body = CSS.slice(open, end);
  const palette: Record<string, string> = {};
  // Capture EVERY custom property, not only the hex ones. An earlier version of
  // this parser read `#hex` alone, and so did not notice that --scrim and
  // --accent-line (both rgba) were missing from one of the two dark blocks.
  for (const [, name, value] of body.matchAll(/--([a-z0-9-]+):\s*([^;]+);/g)) {
    palette[name] = value.trim();
  }
  return palette;
}

/** Only the tokens that are a flat hex colour, for contrast arithmetic. */
function hexOnly(palette: Record<string, string>): Record<string, string> {
  return Object.fromEntries(
    Object.entries(palette).filter(([, value]) => /^#[0-9a-fA-F]{3,8}$/.test(value))
  );
}

const light = paletteOf(":root {");
const darkExplicit = paletteOf(':root[data-theme="dark"] {');
const darkMedia = paletteOf(':root:not([data-theme="light"]) {');

/** Text and iconography tokens that must be legible on any ground. */
const FOREGROUNDS = [
  "ink",
  "ink-2",
  "ink-3",
  "muted",
  "accent",
  "copper",
  "success",
  "warning",
  "danger",
  "info",
  "flow-extract",
  "flow-transform",
  "flow-quality",
  "flow-publish",
  "flow-notify",
];

/** Every surface a foreground can land on. */
const GROUNDS = ["canvas", "surface", "surface-2", "sunken"];

describe("design tokens: three-state theming", () => {
  it("defines a complete light palette on bare :root", () => {
    // The un-stamped "system" state matches no media query and no attribute,
    // so :root alone must be a usable, complete theme.
    for (const token of [...FOREGROUNDS, ...GROUNDS]) {
      expect(light[token], `--${token} missing from :root`).toBeDefined();
    }
  });

  it("redefines dark under BOTH the media query and the explicit attribute", () => {
    // Only in the media query: the toggle cannot force dark on a light OS.
    // Only on the attribute: the default "system" setting never goes dark.
    expect(Object.keys(darkMedia).length).toBeGreaterThan(20);
    expect(Object.keys(darkExplicit).length).toBeGreaterThan(20);
  });

  it("keeps the two dark blocks identical", () => {
    // They are duplicated deliberately (a shared class would not let an
    // explicit choice beat the OS in both directions), so drift is the risk.
    expect(darkExplicit).toEqual(darkMedia);
  });

  it("gives every light token a dark counterpart", () => {
    // A token defined only in light silently keeps its light value in dark --
    // one theme's text on the other theme's ground, the classic bug.
    //
    // Two legitimate exemptions:
    //   - radius / motion / density are theme-independent by design
    //   - an ALIAS (`--panel: var(--surface)`) inherits whatever its target
    //     resolves to, so it needs no dark value of its own. Checked below.
    const themeIndependent = /^(radius|ease|duration|density)-/;
    const isAlias = (value: string) => /^var\(--[a-z0-9-]+\)$/.test(value);
    const missing = Object.keys(light).filter(
      (token) =>
        !themeIndependent.test(token) &&
        !isAlias(light[token]) &&
        !(token in darkExplicit)
    );
    expect(missing, `tokens with no dark value: ${missing.join(", ")}`).toEqual([]);
  });

  it("points every alias at a token that is itself theme-aware", () => {
    // An alias is only safe if what it points at actually flips. An alias onto
    // a light-only token is the same bug wearing a disguise.
    const aliases = Object.entries(light).filter(([, value]) =>
      /^var\(--[a-z0-9-]+\)$/.test(value)
    );
    expect(aliases.length, "expected the legacy aliases to still exist").toBeGreaterThan(0);

    for (const [name, value] of aliases) {
      const target = value.slice("var(".length, -1);
      const targetName = target.replace(/^--/, "");
      expect(
        darkExplicit[targetName],
        `--${name} aliases --${targetName}, which has no dark value`
      ).toBeDefined();
    }
  });

  it("guards the media query against an explicit light choice", () => {
    expect(CSS).toContain('@media (prefers-color-scheme: dark)');
    expect(CSS).toContain(':root:not([data-theme="light"])');
  });

  it("paints an explicit background on body", () => {
    // The host composites the artifact over its own ground; a transparent
    // body borrows the wrong theme.
    expect(CSS).toMatch(/body\s*\{[^}]*background:\s*var\(--canvas\)/s);
  });

  it("sets color-scheme in every state so native controls follow", () => {
    expect(light["_"]).toBeUndefined(); // sanity: parser returns only tokens
    expect(CSS).toMatch(/:root\s*\{[^}]*color-scheme:\s*light/s);
    expect(CSS).toMatch(/:root\[data-theme="dark"\]\s*\{[^}]*color-scheme:\s*dark/s);
  });
});

describe.each([
  ["light", hexOnly(light)],
  ["dark", hexOnly(darkExplicit)],
])("design tokens: %s contrast", (themeName, palette) => {
  const pairs = FOREGROUNDS.flatMap((fg) => GROUNDS.map((bg) => [fg, bg] as const));

  it.each(pairs)(`%s on %s meets WCAG AA (${WCAG_AA_NORMAL}:1)`, (fg, bg) => {
    const ratio = contrastRatio(palette[fg], palette[bg]);
    expect(
      ratio,
      `--${fg} (${palette[fg]}) on --${bg} (${palette[bg]}) in ${themeName} is ${ratio.toFixed(2)}:1`
    ).toBeGreaterThanOrEqual(WCAG_AA_NORMAL);
  });

  it("keeps body text at AAA on the primary surface", () => {
    expect(contrastRatio(palette.ink, palette.surface)).toBeGreaterThanOrEqual(7);
  });

  it("keeps --faint legible enough for placeholder and decorative use", () => {
    // Not held to AA because it is NOT a text colour: it exists for
    // placeholders and non-text decoration, and no-raw-colours.test.ts enforces
    // that. Held to the 3:1 non-text minimum anyway -- a placeholder nobody can
    // read is a usability bug whatever the spec says.
    for (const bg of GROUNDS) {
      expect(
        contrastRatio(palette.faint, palette[bg]),
        `--faint on --${bg} in ${themeName}`
      ).toBeGreaterThanOrEqual(WCAG_AA_LARGE);
    }
  });

  it("keeps text-on-accent legible for filled buttons", () => {
    for (const [ink, fill] of [
      ["accent-ink", "accent"],
      ["success-ink", "success"],
      ["warning-ink", "warning"],
      ["danger-ink", "danger"],
      ["info-ink", "info"],
      ["copper-ink", "copper"],
    ] as const) {
      const ratio = contrastRatio(palette[ink], palette[fill]);
      expect(ratio, `--${ink} on --${fill} in ${themeName} is ${ratio.toFixed(2)}:1`)
        .toBeGreaterThanOrEqual(WCAG_AA_LARGE);
    }
  });
});

describe("density is wired to something", () => {
  it("defines all three density steps", () => {
    for (const density of ["compact", "dense"]) {
      expect(CSS).toContain(`:root[data-density="${density}"]`);
    }
    // Comfortable is the unstamped default, so it lives on bare :root.
    expect(CSS).toMatch(/:root\s*\{[^}]*--density-row-height/s);
  });

  it("shrinks rows as density increases", () => {
    const heightIn = (selector: string) => {
      const at = CSS.indexOf(selector);
      const match = CSS.slice(at).match(/--density-row-height:\s*(\d+)px/);
      return Number(match![1]);
    };
    const comfortable = heightIn(":root {");
    const compact = heightIn(':root[data-density="compact"]');
    const dense = heightIn(':root[data-density="dense"]');

    expect(compact).toBeLessThan(comfortable);
    expect(dense).toBeLessThan(compact);
  });

  it("exposes a utility that actually consumes the density tokens", () => {
    // Without this the switch stores a preference and changes nothing on
    // screen. Tailwind's padding utilities are classes, so a zero-specificity
    // `:where(td, th)` rule would lose to them and density would be decorative.
    expect(CSS).toMatch(/@utility cell-pad\s*\{[^}]*var\(--density-cell-y\)/s);
  });
});

