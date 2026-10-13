// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

import { clearDraft, draftKey, readDraft, writeDraft } from "@/features/studio/recipe-draft";

const key = draftKey("p1", null, "d1");
const steps = [{ step_type: "trim_strings", config: { columns: ["email"] } }];

describe("recipe drafts", () => {
  afterEach(() => clearDraft(key));

  it("keys a saved recipe by its id and a new one by its dataset", () => {
    expect(draftKey("p1", "r1", "d1")).toBe("pipewright.studio.draft:p1:r1");
    expect(key).toBe("pipewright.studio.draft:p1:new:d1");
  });

  it("keeps a draft until it is cleared", () => {
    writeDraft(key, { name: "Tidy", steps, at: 1000 });
    expect(readDraft(key, 2000)).toEqual({ name: "Tidy", steps, at: 1000 });
    clearDraft(key);
    expect(readDraft(key)).toBeNull();
  });

  it("forgets a draft after a week", () => {
    writeDraft(key, { name: "Old", steps, at: 0 });
    expect(readDraft(key, 8 * 24 * 60 * 60 * 1000)).toBeNull();
  });

  it("ignores something that is not a draft", () => {
    window.localStorage.setItem(key, "{not json");
    expect(readDraft(key)).toBeNull();
  });
});
