// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it } from "vitest";

import type { TimelineStep } from "./steps-timeline";
import { useRecipeEditing } from "./use-recipe-editing";

const start: TimelineStep[] = [
  { uid: "a", step_type: "drop_columns", config: { columns: ["x"] } },
  { uid: "b", step_type: "sort_rows", config: { columns: ["y"], ascending: true } },
];

// React's own act, so the hook runs as it would in a page.
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

/** Render the hook in a component and hand back its latest result. */
function local() {
  const result = { current: null as unknown as ReturnType<typeof useRecipeEditing> };
  function Probe() {
    result.current = useRecipeEditing({
      projectId: "p",
      recipeId: "r",
      initialName: "Clean",
      initialSteps: start,
      live: false,
      initialRevision: 1,
    });
    return null;
  }
  const root = createRoot(document.createElement("div"));
  act(() => root.render(createElement(Probe)));
  return { result, rerender: () => act(() => root.render(createElement(Probe))) };
}

/* The Studio's editing state (C2), in this browser alone. */
describe("editing a recipe", () => {
  it("keeps the same steps from render to render until something changes", () => {
    // Found by the accessibility walk: a new list each render made the
    // Studio preview without end.
    const { result, rerender } = local();
    const first = result.current.steps;
    rerender();
    rerender();
    expect(result.current.steps).toBe(first);
    expect(result.current.dirty).toBe(false);
  });

  it("changes, undoes and redoes, and knows what is unsaved", () => {
    const { result } = local();
    act(() => result.current.change((steps) => steps.filter((step) => step.uid !== "a")));
    expect(result.current.steps.map((step) => step.uid)).toEqual(["b"]);
    expect(result.current.dirty).toBe(true);
    act(() => result.current.undo());
    expect(result.current.steps).toEqual(start);
    expect(result.current.dirty).toBe(false);
    act(() => result.current.redo());
    expect(result.current.steps.map((step) => step.uid)).toEqual(["b"]);
  });

  it("folds typing into one setting into one undo", () => {
    const { result } = local();
    for (const value of ["a", "am", "amo"]) {
      act(() =>
        result.current.change(
          (steps) => steps.map((step) => (step.uid === "b" ? { ...step, config: { ...step.config, columns: [value] } } : step)),
          "config:b",
        ),
      );
    }
    act(() => result.current.undo());
    expect(result.current.steps[1].config.columns).toEqual(["y"]);
    expect(result.current.canUndo).toBe(false);
  });

  it("renames, and a save makes the copy saved", async () => {
    const { result } = local();
    act(() => result.current.rename("Tidy"));
    expect(result.current.name).toBe("Tidy");
    expect(result.current.dirty).toBe(true);
    await act(() => result.current.markSaved(2, "Tidy", result.current.steps));
    expect(result.current.dirty).toBe(false);
    expect(result.current.saved?.revision).toBe(2);
  });
});
