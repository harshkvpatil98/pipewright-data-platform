import { describe, expect, it } from "vitest";

import fixtures from "./coedit-fixtures.json";
import {
  Clock,
  type Doc,
  type Op,
  applyOps,
  between,
  diff,
  emptyDoc,
  inverse,
  materialise,
  seed,
  undoable,
} from "./coedit";
import type { TimelineStep } from "./steps-timeline";

/** A seeded random number generator, so a failing run can be repeated. */
function random(seedValue: number) {
  let state = seedValue >>> 0;
  return () => {
    state = (state * 1664525 + 1013904223) >>> 0;
    return state / 2 ** 32;
  };
}

const shuffle = <T>(items: T[], next: () => number): T[] => {
  const out = [...items];
  for (let index = out.length - 1; index > 0; index -= 1) {
    const pick = Math.floor(next() * (index + 1));
    [out[index], out[pick]] = [out[pick], out[index]];
  }
  return out;
};

const view = (doc: Doc) => {
  const { name, steps } = materialise(doc);
  return { name, steps: steps.map((step) => ({ id: step.uid, step_type: step.step_type, config: step.config })) };
};

/* Editing a recipe together (C2): the Studio's half of the merge rules. */
describe("recipe merge rules", () => {
  it("places positions as the server does", () => {
    for (const item of fixtures.between) expect(between(item.low, item.high)).toBe(item.expect);
  });

  it("merges every fixture the same in any order, as the server does", () => {
    const next = random(11);
    for (const item of fixtures.cases) {
      const ops = item.ops as Op[];
      for (const order of [ops, [...ops].reverse(), ...Array.from({ length: 20 }, () => shuffle(ops, next))]) {
        expect(view(applyOps(emptyDoc(), order)), item.name).toEqual(item.expect);
      }
      expect(view(applyOps(emptyDoc(), [...ops, ...ops]))).toEqual(item.expect);
    }
  });

  it("turns an edit into changes that reproduce it", () => {
    const start = seed("Clean", [
      { uid: "a", step_type: "drop_columns", config: { columns: ["x"] } },
      { uid: "b", step_type: "sort_rows", config: { columns: ["y"], ascending: true } },
      { uid: "c", step_type: "filter_rows", config: { column: "z" } },
    ]);
    const clock = new Clock("ann");
    const target: TimelineStep[] = [
      { uid: "c", step_type: "filter_rows", config: { column: "z", value: 3 } },
      { uid: "a", step_type: "drop_columns", config: { columns: ["x", "w"] } },
      { uid: "d", step_type: "remove_duplicates", config: {} },
    ];
    const ops = diff(start, { name: "Tidy", steps: target }, clock);
    const after = materialise(applyOps(start, ops));
    expect(after.name).toBe("Tidy");
    expect(after.steps).toEqual(target);
    // Nothing changed is nothing to send.
    expect(diff(applyOps(start, ops), { name: "Tidy", steps: target }, clock)).toEqual([]);
  });

  it("brings three people's edits to the same recipe, whatever order they arrive in", () => {
    for (let trial = 0; trial < 40; trial += 1) {
      const next = random(1000 + trial);
      const start = seed("R", [
        { uid: "s0", step_type: "t0", config: { a: 0 } },
        { uid: "s1", step_type: "t1", config: { a: 1 } },
      ]);
      const people = ["ann", "bob", "cy"].map((name) => ({ clock: new Clock(name), doc: start, sent: [] as Op[] }));
      let made = 0;
      for (let round = 0; round < 12; round += 1) {
        for (const person of people) {
          const shown = materialise(person.doc).steps;
          const steps = [...shown];
          const roll = next();
          if (roll < 0.3 || steps.length === 0) {
            const at = Math.floor(next() * (steps.length + 1));
            steps.splice(at, 0, { uid: `${person.clock.client}-${made++}`, step_type: "t", config: { a: made } });
          } else if (roll < 0.5) {
            steps.splice(Math.floor(next() * steps.length), 1);
          } else if (roll < 0.7 && steps.length > 1) {
            const from = Math.floor(next() * steps.length);
            const [moved] = steps.splice(from, 1);
            steps.splice(Math.floor(next() * (steps.length + 1)), 0, moved);
          } else {
            const at = Math.floor(next() * steps.length);
            steps[at] = { ...steps[at], config: { ...steps[at].config, a: Math.floor(next() * 100) } };
          }
          const ops = diff(person.doc, { name: null, steps }, person.clock);
          person.doc = applyOps(person.doc, ops);
          person.sent.push(...ops);
        }
        // Some of what each sent reaches the others now; the rest later.
        for (const receiver of people) {
          for (const sender of people) {
            if (sender === receiver || next() < 0.4) continue;
            receiver.doc = applyOps(receiver.doc, shuffle(sender.sent, next));
            for (const op of sender.sent) receiver.clock.observe(op.s[0]);
          }
        }
      }
      const everything = people.flatMap((person) => person.sent);
      const finals = people.map((person) => view(applyOps(person.doc, shuffle(everything, next))));
      expect(finals[1]).toEqual(finals[0]);
      expect(finals[2]).toEqual(finals[0]);
    }
  });

  it("undoes only your own change, and leaves someone else's newer one alone", () => {
    const start = seed("R", [{ uid: "s", step_type: "filter_rows", config: { column: "a", value: 1 } }]);
    const ann = new Clock("ann");
    const bob = new Clock("bob");
    // Ann changes the value and the column; Bob then changes the column again.
    const annOps = diff(start, { name: null, steps: [{ uid: "s", step_type: "filter_rows", config: { column: "b", value: 2 } }] }, ann);
    const afterAnn = applyOps(start, annOps);
    const undo = inverse(start, annOps);
    bob.observe(10);
    const bobOps = diff(afterAnn, { name: null, steps: [{ uid: "s", step_type: "filter_rows", config: { column: "c", value: 2 } }] }, bob);
    const shared = applyOps(afterAnn, bobOps);
    ann.observe(11);
    const undone = applyOps(shared, undoable(shared, undo, ann));
    // Her value goes back; his column stays.
    expect(materialise(undone).steps[0].config).toEqual({ column: "c", value: 1 });
  });

  it("undoes an added step by removing it, and a removal by bringing it back", () => {
    const start = seed("R", [{ uid: "s", step_type: "sort_rows", config: { columns: ["a"] } }]);
    const clock = new Clock("ann");
    const removed = diff(start, { name: null, steps: [] }, clock);
    const gone = applyOps(start, removed);
    expect(materialise(gone).steps).toEqual([]);
    const back = applyOps(gone, undoable(gone, inverse(start, removed), clock));
    expect(materialise(back).steps).toEqual([{ uid: "s", step_type: "sort_rows", config: { columns: ["a"] } }]);

    const added = diff(start, { name: null, steps: [...materialise(start).steps, { uid: "n", step_type: "t", config: {} }] }, clock);
    const withNew = applyOps(start, added);
    const withoutNew = applyOps(withNew, undoable(withNew, inverse(start, added), clock));
    expect(materialise(withoutNew).steps.map((step) => step.uid)).toEqual(["s"]);
  });
});
