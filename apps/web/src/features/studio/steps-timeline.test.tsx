// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { StepsTimeline, type TimelineStep } from "./steps-timeline";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
// jsdom has no layout: opening a step scrolls it into view.
Element.prototype.scrollIntoView = () => {};

const plain: TimelineStep[] = [
  { uid: "a", step_type: "limit_rows", config: { count: 5, _enabled: false, _note: "Only a few while we check" } },
  { uid: "new", step_type: "drop_columns", config: { columns: ["x"] } },
];

const tidy: TimelineStep[] = [
  { uid: "g1", step_type: "trim_strings", config: { columns: ["x"], _group: "Tidy" } },
  { uid: "g2", step_type: "drop_columns", config: { columns: ["y"], _group: "Tidy", _enabled: false } },
  { uid: "after", step_type: "limit_rows", config: { count: 5 } },
];

function render(openUid: string | null, steps: TimelineStep[] = plain) {
  const handlers = {
    onChange: vi.fn(),
    onDuplicate: vi.fn(),
    onComment: vi.fn(),
    onMove: vi.fn(),
    onChangeMany: vi.fn(),
    onSaveGroup: vi.fn(),
  };
  const container = document.createElement("div");
  document.body.append(container);
  const root = createRoot(container);
  act(() =>
    root.render(
      createElement(StepsTimeline, {
        sourceName: "Orders",
        source: null,
        result: null,
        steps,
        outcomes: undefined,
        openUid,
        onOpen: () => {},
        onRemove: () => {},
        onAdd: () => {},
        onTemplates: null,
        problem: null,
        tools: [],
        columns: [{ name: "x" }],
        datasets: [],
        savedStepIds: new Set(["a"]),
        ...handlers,
      }),
    ),
  );
  const button = (label: string) =>
    container.querySelector<HTMLButtonElement>(`button[aria-label="${label}"]`) as HTMLButtonElement;
  return { container, handlers, button, unmount: () => act(() => root.unmount()) };
}

describe("the steps", () => {
  it("say a step is off, and show its note", () => {
    const { container, unmount } = render(null);
    expect(container.textContent).toContain("Off");
    expect(container.textContent).toContain("Only a few while we check");
    unmount();
  });

  it("turn a step on keeping its note, duplicate it, and start a thread on it", () => {
    const { button, handlers, unmount } = render("a");
    act(() => button("Turn this step on").click());
    expect(handlers.onChange).toHaveBeenCalledWith("a", { count: 5, _note: "Only a few while we check" });
    act(() => button("Duplicate this step").click());
    expect(handlers.onDuplicate).toHaveBeenCalledWith("a");
    act(() => button("Comment on this step").click());
    expect(handlers.onComment).toHaveBeenCalledWith("a");
    unmount();
  });

  it("offer a thread only on a step that has been saved", () => {
    const { button, unmount } = render("new");
    expect(button("Save the recipe to comment on this step").disabled).toBe(true);
    unmount();
  });

  it("move a step up and down", () => {
    const { button, handlers, unmount } = render("new");
    act(() => button("Move this step up").click());
    expect(handlers.onMove).toHaveBeenCalledWith("new", -1);
    expect(button("Move this step down").disabled).toBe(true);
    unmount();
  });

  it("group steps under one name, and turn off, save, fold and ungroup the group", () => {
    const { container, button, handlers, unmount } = render(null, tidy);
    expect(container.querySelector('[aria-label="Group Tidy"]')?.textContent).toContain("2 steps");
    act(() => button("Turn Tidy off").click());
    expect(handlers.onChangeMany).toHaveBeenLastCalledWith({
      g1: { columns: ["x"], _group: "Tidy", _enabled: false },
      g2: { columns: ["y"], _group: "Tidy", _enabled: false },
    });
    act(() => button("Save Tidy as a template").click());
    expect(handlers.onSaveGroup).toHaveBeenCalledWith("Tidy", ["g1", "g2"]);
    act(() => button("Ungroup Tidy").click());
    expect(handlers.onChangeMany).toHaveBeenLastCalledWith({
      g1: { columns: ["x"] },
      g2: { columns: ["y"], _enabled: false },
    });
    const shown = () => container.querySelectorAll("li").length;
    const before = shown();
    act(() => button("Fold away the steps in Tidy").click());
    expect(shown()).toBe(before - 2);
    unmount();
  });

  it("start a group from a step and the next", () => {
    const { button, handlers, unmount } = render("one", [
      { uid: "one", step_type: "limit_rows", config: { count: 1 } },
      { uid: "two", step_type: "limit_rows", config: { count: 2 } },
    ]);
    act(() => button("Group this step with the next").click());
    expect(handlers.onChangeMany).toHaveBeenCalledWith({
      one: { count: 1, _group: "Group 1" },
      two: { count: 2, _group: "Group 1" },
    });
    unmount();
  });

  it("keep a step off when its settings change", () => {
    const { container, handlers, unmount } = render("a");
    const count = container.querySelector<HTMLInputElement>('input[type="number"]');
    expect(count).not.toBeNull();
    act(() => {
      const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
      setter?.call(count, "7");
      count?.dispatchEvent(new Event("input", { bubbles: true }));
    });
    const [uid, config] = handlers.onChange.mock.calls.at(-1) ?? [];
    expect(uid).toBe("a");
    expect(config).toMatchObject({ _enabled: false, _note: "Only a few while we check" });
    unmount();
  });
});
