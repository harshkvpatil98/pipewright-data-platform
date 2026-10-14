/**
 * The words of the shell and the navigation, from a catalogue (A8, Y7).
 *
 * `messages/en.json` holds them, nested by where they appear, and `t()`
 * reads one by its dotted key ("shell.topBar.signOut"), filling `{name}`
 * placeholders. A key that is not in the catalogue does not compile: the
 * key types come from the file itself. English is the one language shipped;
 * another would be a copy of the file with the same keys, chosen by
 * `LOCALE`. The rest of the pages still write English inline.
 */

import en from "../../messages/en.json";

type Catalogue = typeof en;

/** Every dotted path in the catalogue that leads to a string. */
type StringKeys<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends string
    ? `${Prefix}${K}`
    : T[K] extends readonly unknown[]
      ? never
      : StringKeys<T[K], `${Prefix}${K}.`>;
}[keyof T & string];

/** Every dotted path that leads to a list of strings. */
type ListKeys<T, Prefix extends string = ""> = {
  [K in keyof T & string]: T[K] extends readonly string[]
    ? `${Prefix}${K}`
    : T[K] extends string
      ? never
      : ListKeys<T[K], `${Prefix}${K}.`>;
}[keyof T & string];

export type MessageKey = Exclude<StringKeys<Catalogue>, "$comment" | "locale">;
export type MessageListKey = ListKeys<Catalogue>;

/** The locale every date and number is written in (src/lib/format.ts). */
export const LOCALE: string = en.locale;

function lookup(key: string): unknown {
  return key.split(".").reduce<unknown>((node, part) => (node as Record<string, unknown> | undefined)?.[part], en);
}

/** One message, with `{name}` placeholders filled from `values`. */
export function t(key: MessageKey, values?: Record<string, string | number>): string {
  const found = lookup(key);
  const text = typeof found === "string" ? found : key;
  return values ? text.replace(/\{(\w+)\}/g, (whole, name: string) => (name in values ? String(values[name]) : whole)) : text;
}

/** A list of messages, such as a page's help lines. */
export function tList(key: MessageListKey): string[] {
  const found = lookup(key);
  return Array.isArray(found) ? found.map(String) : [];
}
