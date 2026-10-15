/**
 * Settings every step has besides its own (E1): turned off, a note, and the
 * group it is in. The server keeps the same names (`steps/flags.py`): a step
 * turned off is kept in the recipe and skipped; a note and a group are for
 * people and never change a result.
 */

export const ENABLED = "_enabled";
export const NOTE = "_note";
export const GROUP = "_group";
const FLAGS = [ENABLED, NOTE, GROUP] as const;
const REMARKS = [NOTE, GROUP] as const;

type Config = Record<string, unknown>;

export function isOff(config: Config): boolean {
  return config[ENABLED] === false;
}

export function noteOf(config: Config): string {
  const note = config[NOTE];
  return typeof note === "string" ? note : "";
}

/** Turned on is the default, so it is not written down. */
export function turned(config: Config, on: boolean): Config {
  const next = { ...config };
  if (on) delete next[ENABLED];
  else next[ENABLED] = false;
  return next;
}

export function groupOf(config: Config): string {
  const group = config[GROUP];
  return typeof group === "string" ? group : "";
}

/** In a group by name, or (an empty name) in none. */
export function grouped(config: Config, name: string): Config {
  const next = { ...config };
  if (name.trim()) next[GROUP] = name.trim();
  else delete next[GROUP];
  return next;
}

/** Steps next to each other in one group: where each group starts, and its steps' ids. */
export function groupRuns(steps: { uid: string; config: Config }[]): Map<string, { name: string; uids: string[] }> {
  const runs = new Map<string, { name: string; uids: string[] }>();
  let current: { name: string; uids: string[] } | null = null;
  for (const step of steps) {
    const name = groupOf(step.config);
    if (name && current && current.name === name) {
      current.uids.push(step.uid);
      continue;
    }
    current = name ? { name, uids: [step.uid] } : null;
    if (current) runs.set(step.uid, current);
  }
  return runs;
}

export function noted(config: Config, note: string): Config {
  const next = { ...config };
  if (note.trim()) next[NOTE] = note;
  else delete next[NOTE];
  return next;
}

/** A step's settings form knows only its own settings: the flags are carried over. */
export function keepFlags(before: Config, after: Config): Config {
  const next = { ...after };
  for (const key of FLAGS) {
    if (!(key in next) && key in before) next[key] = before[key];
  }
  return next;
}

/** The settings without the note and the group, which never change a result. */
export function withoutRemarks(config: Config): Config {
  if (!REMARKS.some((key) => key in config)) return config;
  const next = { ...config };
  for (const key of REMARKS) delete next[key];
  return next;
}
