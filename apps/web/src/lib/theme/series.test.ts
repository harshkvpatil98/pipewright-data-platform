import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

import { contrastRatio } from "@/lib/theme/contrast";
import { deltaE, simulate, worstCaseDeltaE } from "@/lib/theme/cvd";

const CSS = readFileSync(fileURLToPath(new URL("../../app/globals.css", import.meta.url)), "utf8");

function seriesIn(selector: string): string[] {
  const start = CSS.indexOf(selector);
  expect(start, `selector not found: ${selector}`).toBeGreaterThan(-1);
  const open = CSS.indexOf("{", start);
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
  return Array.from({ length: 8 }, (_, i) => {
    const match = body.match(new RegExp(`--series-${i + 1}:\\s*(#[0-9a-fA-F]{6})`));
    expect(match, `--series-${i + 1} missing from ${selector}`).not.toBeNull();
    return match![1];
  });
}

const light = seriesIn(":root {");
const dark = seriesIn(':root[data-theme="dark"] {');

/**
 * How many series hue alone can carry before a second channel (dash pattern,
 * marker shape) is required. Measured, not assumed -- see the roadmap note in
 * globals.css. Lowering these numbers is a regression; raising one means
 * proving it with the simulation.
 */
const SAFE_SERIES = { light: 5, dark: 6 } as const;
const SEPARATION = 12;

describe("chart series palette", () => {
  it("simulates dichromacy correctly", () => {
    // Guard on the simulation itself: red/green must collapse and blue/yellow
    // must survive. A simulation that fails this scores good palettes as bad.
    const redGreenNormal = deltaE("#ff0000", "#00ff00");
    const redGreenDeutan = deltaE(
      simulate("#ff0000", "deuteranopia"),
      simulate("#00ff00", "deuteranopia")
    );
    expect(redGreenDeutan).toBeLessThan(redGreenNormal / 3);

    const blueYellow = deltaE(
      simulate("#0000ff", "deuteranopia"),
      simulate("#ffff00", "deuteranopia")
    );
    expect(blueYellow).toBeGreaterThan(100);
  });

  it.each([
    ["light", light, "#ffffff", SAFE_SERIES.light],
    ["dark", dark, "#0d1113", SAFE_SERIES.dark],
  ])("keeps %s series distinguishable under colour blindness", (_name, palette, _ground, safe) => {
    for (let i = 0; i < safe; i += 1) {
      for (let j = i + 1; j < safe; j += 1) {
        const separation = worstCaseDeltaE(palette[i], palette[j]);
        expect(
          separation,
          `series-${i + 1} (${palette[i]}) and series-${j + 1} (${palette[j]}) are ` +
            `${separation.toFixed(1)} apart in the worst deficiency`
        ).toBeGreaterThanOrEqual(SEPARATION);
      }
    }
  });

  it.each([
    ["light", light, "#ffffff"],
    ["dark", dark, "#0d1113"],
  ])("keeps every %s series visible against its ground", (_name, palette, ground) => {
    // Not 3:1: a series is identified by its legend and distinguished from the
    // OTHER series, not from the background. Forcing 3:1 on white crushes the
    // palette into one dark band and destroys the separation above. This is
    // the floor at which a mark is plainly visible.
    for (const [index, colour] of palette.entries()) {
      const ratio = contrastRatio(colour, ground);
      expect(ratio, `--series-${index + 1} (${colour}) on ${ground}`).toBeGreaterThanOrEqual(2.2);
    }
  });

  it("orders the palette so short charts get the most distinct hues", () => {
    // A 3-series chart uses series 1-3, so those must be the FURTHEST apart,
    // not merely the first declared.
    for (const palette of [light, dark]) {
      const firstThree = Math.min(
        worstCaseDeltaE(palette[0], palette[1]),
        worstCaseDeltaE(palette[0], palette[2]),
        worstCaseDeltaE(palette[1], palette[2])
      );
      expect(firstThree).toBeGreaterThanOrEqual(20);
    }
  });

  it("documents the limit next to the tokens", () => {
    // The palette cannot carry 8 series on hue alone and the CSS must say so,
    // or the next person will add series-9 and quietly break it.
    expect(CSS).toMatch(/second channel|dash pattern/i);
  });
});
