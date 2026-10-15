/**
 * Editing a recipe together (roadmap Phase 21, C2): the merge rules.
 *
 * The twin of `service_transformations/coedit.py`; `coedit-fixtures.json`
 * holds cases both must agree on. A recipe's working copy is a small CRDT:
 *
 * - steps are stable ids ordered by a fractional position, then by id;
 * - each setting, a step's position, whether it is removed, and the name are
 *   last-writer-wins registers;
 * - every change carries a Lamport stamp [counter, client], compared as a
 *   pair, so "last" means the same on every machine;
 *
 * so changes merge the same whatever order they arrive in. The Studio turns
 * each edit into changes (`diff`), applies them at once, and sends them;
 * others' changes are merged as they arrive. Undo takes back only this
 * person's own changes, and only where nobody has changed the same thing
 * since (`undoable`).
 */

import type { TimelineStep } from "./steps-timeline";

export type Stamp = [number, string];

type Register<T> = { v: T; s: Stamp; x?: true };

export type StepEntry = {
  type: string | null;
  pos: Register<string> | null;
  del: Register<boolean> | null;
  cfg: Record<string, Register<unknown>>;
};

export type Doc = { name: Register<string> | null; steps: Record<string, StepEntry> };

export type Op =
  | { k: "name"; v: string; s: Stamp }
  | { k: "add"; id: string; type: string; pos: string; cfg: Record<string, unknown>; s: Stamp }
  | { k: "set"; id: string; key: string; v?: unknown; x?: true; s: Stamp }
  | { k: "move"; id: string; pos: string; s: Stamp }
  | { k: "del"; id: string; v: boolean; s: Stamp };

/** A change waiting for its stamp: what undo and redo keep. */
export type Unstamped = Op extends infer O ? (O extends Op ? Omit<O, "s"> : never) : never;

const DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz";

/** A position that sorts after `low` and before `high` (null: an open end). */
export function between(low: string | null, high: string | null): string {
  const from = low ?? "";
  if (high !== null && high <= from) throw new Error("between() needs low < high");
  let result = "";
  let upper: string | null = high;
  for (let index = 0; ; index += 1) {
    const a = index < from.length ? DIGITS.indexOf(from[index]) : 0;
    const b = upper !== null && index < upper.length ? DIGITS.indexOf(upper[index]) : DIGITS.length;
    if (b - a > 1) return result + DIGITS[Math.floor((a + b) / 2)];
    result += DIGITS[a];
    // Past this digit the upper bound no longer constrains.
    if (b - a === 1) upper = null;
  }
}

export const newer = (candidate: Stamp, current: Stamp | null | undefined): boolean =>
  !current || candidate[0] > current[0] || (candidate[0] === current[0] && candidate[1] > current[1]);

export const sameStamp = (left: Stamp | null | undefined, right: Stamp | null | undefined): boolean =>
  !!left && !!right && left[0] === right[0] && left[1] === right[1];

export function emptyDoc(): Doc {
  return { name: null, steps: {} };
}

function cloneStep(step: StepEntry | undefined): StepEntry {
  return step ? { ...step, cfg: { ...step.cfg } } : { type: null, pos: null, del: null, cfg: {} };
}

/** Merge one change into a copy of `doc`. The order changes arrive in does not matter. */
export function applyOp(doc: Doc, op: Op): Doc {
  if (op.k === "name") {
    return newer(op.s, doc.name?.s) ? { ...doc, name: { v: op.v, s: op.s } } : doc;
  }
  const step = cloneStep(doc.steps[op.id]);
  if (op.k === "add") {
    if (step.type === null) step.type = op.type;
    if (newer(op.s, step.pos?.s)) step.pos = { v: op.pos, s: op.s };
    if (newer(op.s, step.del?.s)) step.del = { v: false, s: op.s };
    for (const [key, value] of Object.entries(op.cfg)) {
      if (newer(op.s, step.cfg[key]?.s)) step.cfg[key] = { v: value, s: op.s };
    }
  } else if (op.k === "set") {
    if (newer(op.s, step.cfg[op.key]?.s)) step.cfg[op.key] = op.x ? { v: null, s: op.s, x: true } : { v: op.v, s: op.s };
  } else if (op.k === "move") {
    if (newer(op.s, step.pos?.s)) step.pos = { v: op.pos, s: op.s };
  } else if (op.k === "del") {
    if (newer(op.s, step.del?.s)) step.del = { v: op.v, s: op.s };
  }
  return { ...doc, steps: { ...doc.steps, [op.id]: step } };
}

export function applyOps(doc: Doc, ops: Op[]): Doc {
  return ops.reduce(applyOp, doc);
}

type Placed = { id: string; pos: string; step: TimelineStep };

function placed(doc: Doc): Placed[] {
  const out: Placed[] = [];
  for (const [id, entry] of Object.entries(doc.steps)) {
    if (entry.type === null || entry.pos === null || entry.del?.v) continue;
    const config: Record<string, unknown> = {};
    for (const key of Object.keys(entry.cfg).sort()) {
      if (!entry.cfg[key].x) config[key] = entry.cfg[key].v;
    }
    out.push({ id, pos: entry.pos.v, step: { uid: id, step_type: entry.type, config } });
  }
  // Byte order, as Python sorts strings, so both sides agree.
  return out.sort((a, b) => (a.pos < b.pos ? -1 : a.pos > b.pos ? 1 : a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
}

/** The recipe a copy describes: its name and its steps, in order. */
export function materialise(doc: Doc): { name: string | null; steps: TimelineStep[] } {
  return { name: doc.name?.v ?? null, steps: placed(doc).map((item) => item.step) };
}

/** A copy holding exactly a saved recipe, stamped before any change. */
export function seed(name: string, steps: TimelineStep[]): Doc {
  const stamp: Stamp = [0, "saved"];
  let doc = applyOp(emptyDoc(), { k: "name", v: name, s: stamp });
  let position: string | null = null;
  for (const step of steps) {
    position = between(position, null);
    doc = applyOp(doc, { k: "add", id: step.uid, type: step.step_type, pos: position, cfg: step.config, s: stamp });
  }
  return doc;
}

/** The highest stamp counter in a copy, so a clock starts past it. */
export function maxCounter(doc: Doc): number {
  let highest = doc.name?.s[0] ?? 0;
  for (const entry of Object.values(doc.steps)) {
    for (const register of [entry.pos, entry.del, ...Object.values(entry.cfg)]) {
      if (register) highest = Math.max(highest, register.s[0]);
    }
  }
  return highest;
}

/** A Lamport clock: each stamp is past everything this Studio has seen. */
export class Clock {
  constructor(
    readonly client: string,
    private counter = 0,
  ) {}

  observe(counter: number): void {
    this.counter = Math.max(this.counter, counter);
  }

  next(): Stamp {
    this.counter += 1;
    return [this.counter, this.client];
  }
}

/**
 * JSON with every object's keys in order, so two settings that differ only
 * in the order their keys were written compare equal. The shared copy keeps
 * a step's settings sorted and the saved recipe keeps them as written; a
 * plain comparison called them different (found rehearsing C2).
 */
export function stableJson(value: unknown): string {
  return JSON.stringify(value, (_key, item: unknown) =>
    item && typeof item === "object" && !Array.isArray(item)
      ? Object.fromEntries(Object.entries(item as Record<string, unknown>).sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0)))
      : item,
  );
}

const same = (left: unknown, right: unknown) => stableJson(left) === stableJson(right);

/** The changes that turn what `doc` shows into `next`, stamped by `clock`. */
export function diff(doc: Doc, next: { name: string | null; steps: TimelineStep[] }, clock: Clock): Op[] {
  const ops: Op[] = [];
  const current = placed(doc);
  const byId = new Map(current.map((item) => [item.id, item]));
  const wanted = new Set(next.steps.map((step) => step.uid));

  if (next.name !== null && next.name !== (doc.name?.v ?? null)) ops.push({ k: "name", v: next.name, s: clock.next() });

  for (const item of current) {
    if (!wanted.has(item.id)) ops.push({ k: "del", id: item.id, v: true, s: clock.next() });
  }

  // Steps that keep their position: the longest run whose positions already
  // rise in the new order. Every other step gets a new position between its
  // new neighbours, so equal positions are never relied on.
  const keep = steady(next.steps.map((step) => byId.get(step.uid)?.pos ?? null));
  const positions: (string | null)[] = next.steps.map((step, index) =>
    keep.has(index) ? (byId.get(step.uid)?.pos ?? null) : null,
  );
  for (let index = 0; index < next.steps.length; index += 1) {
    if (positions[index] !== null) continue;
    const low = index > 0 ? positions[index - 1] : null;
    let high: string | null = null;
    for (let after = index + 1; after < next.steps.length; after += 1) {
      if (positions[after] !== null) {
        high = positions[after];
        break;
      }
    }
    positions[index] = between(low, high);
  }

  next.steps.forEach((step, index) => {
    const position = positions[index] as string;
    const existing = doc.steps[step.uid];
    const shown = byId.get(step.uid);
    if (!existing || existing.type === null) {
      ops.push({ k: "add", id: step.uid, type: step.step_type, pos: position, cfg: { ...step.config }, s: clock.next() });
      return;
    }
    if (!shown) {
      // A removed step coming back (an undo, a restored draft): back in place, with its settings.
      ops.push({ k: "del", id: step.uid, v: false, s: clock.next() });
    }
    if (!shown || shown.pos !== position) ops.push({ k: "move", id: step.uid, pos: position, s: clock.next() });
    const before: Record<string, unknown> = shown?.step.config ?? {};
    for (const key of new Set([...Object.keys(before), ...Object.keys(step.config)])) {
      if (!(key in step.config)) {
        if (shown && key in before) ops.push({ k: "set", id: step.uid, key, x: true, s: clock.next() });
      } else if (!shown || !(key in before) || !same(before[key], step.config[key])) {
        ops.push({ k: "set", id: step.uid, key, v: step.config[key], s: clock.next() });
      }
    }
  });
  return ops;
}

/** Indices of the longest subsequence of known positions that strictly rises. */
function steady(positions: (string | null)[]): Set<number> {
  const tails: number[] = [];
  const previous: number[] = new Array(positions.length).fill(-1);
  positions.forEach((position, index) => {
    if (position === null) return;
    let low = 0;
    let high = tails.length;
    while (low < high) {
      const middle = (low + high) >> 1;
      if ((positions[tails[middle]] as string) < position) low = middle + 1;
      else high = middle;
    }
    if (low > 0) previous[index] = tails[low - 1];
    tails[low] = index;
  });
  const kept = new Set<number>();
  let at = tails.length ? tails[tails.length - 1] : -1;
  while (at !== -1) {
    kept.add(at);
    at = previous[at];
  }
  return kept;
}

/**
 * What would take back `ops`, read from the copy as it was before them.
 * Paired with each change's own stamp, so undo can leave alone anything
 * someone else has changed since.
 */
export function inverse(before: Doc, ops: Op[]): { op: Unstamped; after: Stamp }[] {
  const out: { op: Unstamped; after: Stamp }[] = [];
  for (const op of ops) {
    const step = op.k === "name" ? undefined : before.steps[op.id];
    if (op.k === "name") {
      out.push({ op: { k: "name", v: before.name?.v ?? "" }, after: op.s });
    } else if (op.k === "add") {
      out.push({ op: { k: "del", id: op.id, v: true }, after: op.s });
    } else if (op.k === "set") {
      const previous = step?.cfg[op.key];
      out.push({
        op: previous && !previous.x ? { k: "set", id: op.id, key: op.key, v: previous.v } : { k: "set", id: op.id, key: op.key, x: true },
        after: op.s,
      });
    } else if (op.k === "move") {
      if (step?.pos) out.push({ op: { k: "move", id: op.id, pos: step.pos.v }, after: op.s });
    } else if (op.k === "del") {
      out.push({ op: { k: "del", id: op.id, v: step?.del?.v ?? true }, after: op.s });
    }
  }
  return out.reverse();
}

function registerStamp(doc: Doc, op: Unstamped): Stamp | null {
  if (op.k === "name") return doc.name?.s ?? null;
  const step = doc.steps[op.id];
  if (!step) return null;
  if (op.k === "set") return step.cfg[op.key]?.s ?? null;
  if (op.k === "move") return step.pos?.s ?? null;
  if (op.k === "del") return step.del?.s ?? null;
  return step.pos?.s ?? null;
}

/**
 * Stamp the parts of an undo (or redo) that still apply: those whose
 * register still holds this person's change. Anything someone else has
 * changed since is theirs now, and is left alone.
 */
export function undoable(doc: Doc, entries: { op: Unstamped; after: Stamp }[], clock: Clock): Op[] {
  const ops: Op[] = [];
  for (const entry of entries) {
    if (!sameStamp(registerStamp(doc, entry.op), entry.after)) continue;
    ops.push({ ...entry.op, s: clock.next() } as Op);
  }
  return ops;
}
