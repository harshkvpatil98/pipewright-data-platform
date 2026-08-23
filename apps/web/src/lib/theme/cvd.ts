/**
 * Dichromat (colour-blindness) simulation, used to hold the chart series
 * palette to a measured standard.
 *
 * Viénot, Brettel & Mollon (1999): convert to LMS cone space, collapse the
 * missing cone's contribution, convert back. Doing this by applying the LMS
 * matrices straight to RGB -- skipping the cone-space transform -- produces
 * numbers that look plausible and are wrong; an earlier draft did exactly that
 * and scored Okabe-Ito, a palette designed for colour blindness, as unusable.
 */

import { parseHex } from "@/lib/theme/contrast";

export type Deficiency = "protanopia" | "deuteranopia" | "tritanopia";

type M3 = readonly [
  readonly [number, number, number],
  readonly [number, number, number],
  readonly [number, number, number],
];

const RGB_TO_LMS: M3 = [
  [17.8824, 43.5161, 4.11935],
  [3.45565, 27.1554, 3.86714],
  [0.0299566, 0.184309, 1.46709],
];

const LMS_TO_RGB: M3 = [
  [0.0809445, -0.130504, 0.116721],
  [-0.0102485, 0.0540194, -0.113615],
  [-0.000365294, -0.00412163, 0.693513],
];

const COLLAPSE: Record<Deficiency, M3> = {
  protanopia: [
    [0, 2.02344, -2.52581],
    [0, 1, 0],
    [0, 0, 1],
  ],
  deuteranopia: [
    [1, 0, 0],
    [0.494207, 0, 1.24827],
    [0, 0, 1],
  ],
  tritanopia: [
    [1, 0, 0],
    [0, 1, 0],
    [-0.395913, 0.801109, 0],
  ],
};

function apply(m: M3, v: readonly number[]): number[] {
  return [0, 1, 2].map((i) => m[i][0] * v[0] + m[i][1] * v[1] + m[i][2] * v[2]);
}

function toLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

function fromLinear(value: number): number {
  const c = Math.min(1, Math.max(0, value));
  return 255 * (c <= 0.0031308 ? 12.92 * c : 1.055 * c ** (1 / 2.4) - 0.055);
}

function toHex(rgb: readonly number[]): string {
  return `#${rgb
    .map((v) => Math.round(Math.min(255, Math.max(0, v))).toString(16).padStart(2, "0"))
    .join("")}`;
}

/** How `hex` appears to someone with the given deficiency. */
export function simulate(hex: string, deficiency: Deficiency): string {
  const { r, g, b } = parseHex(hex);
  const linear = [toLinear(r), toLinear(g), toLinear(b)];
  const lms = apply(RGB_TO_LMS, linear);
  const collapsed = apply(COLLAPSE[deficiency], lms);
  return toHex(apply(LMS_TO_RGB, collapsed).map(fromLinear));
}

/** CIELAB coordinates, for perceptual rather than channel-wise distance. */
export function toLab(hex: string): [number, number, number] {
  const { r, g, b } = parseHex(hex);
  const [lr, lg, lb] = [toLinear(r), toLinear(g), toLinear(b)];
  let x = (lr * 0.4124 + lg * 0.3576 + lb * 0.1805) / 0.95047;
  const y = lr * 0.2126 + lg * 0.7152 + lb * 0.0722;
  let z = (lr * 0.0193 + lg * 0.1192 + lb * 0.9505) / 1.08883;
  const f = (t: number) => (t > 0.008856 ? Math.cbrt(t) : 7.787 * t + 16 / 116);
  [x, z] = [f(x), f(z)];
  const fy = f(y);
  return [116 * fy - 16, 500 * (x - fy), 200 * (fy - z)];
}

/** Perceptual distance (CIE76). Roughly: <2 identical, ~10 noticeable, >20 clearly distinct. */
export function deltaE(a: string, b: string): number {
  const [l1, a1, b1] = toLab(a);
  const [l2, a2, b2] = toLab(b);
  return Math.hypot(l1 - l2, a1 - a2, b1 - b2);
}

/** Distance between two colours under the harshest of normal vision and all three deficiencies. */
export function worstCaseDeltaE(a: string, b: string): number {
  const deficiencies: Deficiency[] = ["protanopia", "deuteranopia", "tritanopia"];
  return Math.min(
    deltaE(a, b),
    ...deficiencies.map((d) => deltaE(simulate(a, d), simulate(b, d)))
  );
}
