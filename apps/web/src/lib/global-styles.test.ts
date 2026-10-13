import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

/*
 * Tailwind's utilities live in a cascade layer. A rule outside every layer
 * beats them all, whatever its specificity, so an unlayered `button { font:
 * inherit }` silently cancelled every button's text-size class and `a {
 * color: inherit }` every link's colour (found in A6). Element rules belong
 * in `@layer base`; this reads globals.css and fails on any that is not.
 */

const CSS = readFileSync(fileURLToPath(new URL("../app/globals.css", import.meta.url)), "utf8");

/** Every rule's selector, with the at-rules it sits in, outermost first. */
function rules(css: string): { selector: string; inside: string[] }[] {
  const found: { selector: string; inside: string[] }[] = [];
  const stack: string[] = [];
  let buffer = "";
  for (const char of css.replace(/\/\*[\s\S]*?\*\//g, "")) {
    if (char === "{") {
      const selector = buffer.trim();
      found.push({ selector, inside: [...stack] });
      stack.push(selector);
      buffer = "";
    } else if (char === "}") {
      stack.pop();
      buffer = "";
    } else if (char === ";") {
      buffer = "";
    } else {
      buffer += char;
    }
  }
  return found;
}

const ELEMENTS = /(^|[\s,(>+~])(a|button|input|select|textarea|body|html|label|h[1-6]|p|ul|ol|li|table|th|td)(?=$|[\s,:.[>+~)])/;

describe("global styles", () => {
  it("keeps element rules in the base layer, under the utilities", () => {
    const unlayered = rules(CSS)
      .filter(({ selector, inside }) => !selector.startsWith("@") && !inside.some((at) => at.startsWith("@layer")))
      .filter(({ selector, inside }) => !inside.some((at) => at.startsWith("@keyframes")) && ELEMENTS.test(selector))
      .map(({ selector, inside }) => [...inside, selector].join(" › "));
    expect(unlayered).toEqual([]);
  });
});
