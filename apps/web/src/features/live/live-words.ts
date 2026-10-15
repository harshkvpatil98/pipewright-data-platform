import type {
  LiveFamily,
  LiveGuarantee,
  LiveKind,
  LiveKindField,
  LiveRecipe,
  LiveTable,
  LiveWindow,
  StreamSource,
} from "@platform/shared-types";
import type { BadgeTone } from "@platform/shared-ui";

import { countOf } from "@/lib/format";

/** The three families, in the order people look for them. */
export const FAMILIES: { family: LiveFamily; label: string; description: string }[] = [
  {
    family: "change_capture",
    label: "Database changes",
    description: "Follow tables through the database's own change log and keep each one current.",
  },
  {
    family: "queue",
    label: "Message queues",
    description: "Read a topic, stream or queue from where Pipewright last stopped.",
  },
  {
    family: "webhook",
    label: "Webhook",
    description: "An address a partner's system posts events to.",
  },
];

const MINUTE = 60;
const HOUR = 3600;
const DAY = 86400;

/** A length of time in words: "5 seconds", "1 minute", "2 hours". */
export function durationWords(seconds: number): string {
  const value = Math.max(0, Math.round(seconds));
  if (value >= DAY && value % DAY === 0) return countOf(value / DAY, "day");
  if (value >= HOUR && value % HOUR === 0) return countOf(value / HOUR, "hour");
  if (value >= MINUTE && value % MINUTE === 0) return countOf(value / MINUTE, "minute");
  return countOf(value, "second");
}

/** How often something happens: "every 5 seconds", "every minute". */
export function everyWords(seconds: number): string {
  const words = durationWords(seconds);
  return `every ${words.startsWith("1 ") ? words.slice(2) : words}`;
}

/** What a feed is doing, for its badge. */
export function feedState(source: Pick<StreamSource, "status" | "failures" | "last_event_at" | "family">, now = Date.now()): {
  word: string;
  tone: BadgeTone;
} {
  if (source.status === "paused") return { word: "Paused", tone: "neutral" };
  if (source.status === "failing") return { word: "Failing", tone: "danger" };
  if (!source.last_event_at) return { word: "Waiting for its first event", tone: "neutral" };
  const quietFor = (now - new Date(source.last_event_at).getTime()) / 1000;
  return quietFor < 10 * MINUTE ? { word: "Receiving", tone: "success" } : { word: "Quiet", tone: "neutral" };
}

/** Whether the guarantee is the strong kind, for its badge's colour. */
export function guaranteeTone(guarantee: LiveGuarantee): BadgeTone {
  return guarantee === "at_least_once" ? "warning" : "success";
}

/** How far behind a feed is, or null when it has caught up or cannot say. */
export function behindWords(behind: number | null | undefined): string | null {
  if (!behind) return null;
  return `${countOf(behind, "event")} waiting at the source`;
}

const TABLE_STATES: Record<LiveTable["state"], { word: string; tone: BadgeTone }> = {
  waiting: { word: "First copy to take", tone: "neutral" },
  snapshot: { word: "Taking its first copy", tone: "info" },
  following: { word: "Kept current", tone: "success" },
  log_only: { word: "Changes only", tone: "warning" },
  failed: { word: "Failed", tone: "danger" },
};

export function tableState(table: Pick<LiveTable, "state" | "last_error">): { word: string; tone: BadgeTone } {
  if (table.last_error && table.state !== "following") return { word: "Needs attention", tone: "danger" };
  return TABLE_STATES[table.state] ?? { word: table.state, tone: "neutral" };
}

export const WINDOW_LABELS: Record<LiveWindow["kind"], { label: string; help: string }> = {
  tumbling: { label: "Back to back", help: "Fixed windows, one after another: 10:00 to 10:05, then 10:05 to 10:10." },
  hopping: {
    label: "Overlapping",
    help: "Fixed windows that start every so often, so they overlap: 5 minutes long, a new one every minute.",
  },
  sliding: {
    label: "Sliding",
    help: "The last so many minutes, at every moment an event arrives or drops out of it.",
  },
  session: { label: "Sessions", help: "Activity separated by a quiet gap: a session ends once nothing arrives for the gap." },
};

/** A window in words: "Back to back windows of 5 minutes". */
export function windowWords(window: LiveWindow): string {
  if (window.kind === "session") return `Sessions ending after ${durationWords(window.gap_seconds ?? 0)} of quiet`;
  const size = durationWords(window.size_seconds ?? 0);
  if (window.kind === "hopping") {
    return `Windows of ${size}, a new one ${everyWords(window.advance_seconds ?? 0)}`;
  }
  if (window.kind === "sliding") return `The last ${size}, at every change`;
  return `Back to back windows of ${size}`;
}

/** What happens to an event that arrives after its window is final. */
export function lateWords(window: LiveWindow): string {
  const waits = window.lateness_seconds
    ? `Waits ${durationWords(window.lateness_seconds)} for late events. `
    : "Does not wait for late events. ";
  if (window.late === "restate") {
    return `${waits}One later still updates a window closed within ${durationWords(window.restate_for_seconds)}.`;
  }
  return `${waits}One later still is counted and left out.`;
}

export function recipeState(recipe: Pick<LiveRecipe, "status" | "last_error">): { word: string; tone: BadgeTone } {
  if (recipe.status === "failed") return { word: "Stopped", tone: "danger" };
  if (recipe.status === "paused") return { word: "Paused", tone: "neutral" };
  return { word: "Running", tone: "success" };
}

/** The settings form's starting values: what is saved, or each field's default, as text. */
export function fieldValues(fields: LiveKindField[], saved: Record<string, unknown> = {}): Record<string, string> {
  return Object.fromEntries(
    fields.map((field) => {
      if (field.kind === "secret") return [field.key, ""];
      const value = saved[field.key] ?? field.default;
      return [field.key, value === null || value === undefined ? "" : String(value)];
    }),
  );
}

/** The settings to send: empty fields left out, numbers and switches typed. A secret left
 * empty is left out, which keeps the saved one. */
export function settingsFrom(fields: LiveKindField[], values: Record<string, string>): Record<string, unknown> {
  const settings: Record<string, unknown> = {};
  for (const field of fields) {
    const raw = values[field.key] ?? "";
    if (field.kind === "boolean") {
      settings[field.key] = raw === "true";
      continue;
    }
    if (!raw.trim()) continue;
    settings[field.key] = field.kind === "number" ? Number(raw) : field.kind === "secret" ? raw : raw.trim();
  }
  return settings;
}

/** The first required field left empty, by its label. A saved secret counts as filled. */
export function firstMissing(
  fields: LiveKindField[],
  values: Record<string, string>,
  saved: Record<string, unknown> = {},
): string | null {
  const missing = fields.find(
    (field) =>
      field.required &&
      field.default === null &&
      field.kind !== "boolean" &&
      !(values[field.key] ?? "").trim() &&
      !(field.kind === "secret" && saved[field.key] === true),
  );
  return missing ? missing.label : null;
}

/** Table names from a comma- or line-separated list, each once. */
export function tableList(text: string): string[] {
  return Array.from(new Set(text.split(/[\n,]/).map((item) => item.trim()).filter(Boolean)));
}

/** Kinds of one family, ones that work here first, then by name. */
export function kindsOf(kinds: LiveKind[], family: LiveFamily): LiveKind[] {
  return kinds
    .filter((kind) => kind.family === family)
    .sort((a, b) => Number(b.available) - Number(a.available) || a.label.localeCompare(b.label));
}
