// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

const calls: { path: string; method: string }[] = [];

// The server, as the dialog reads it: one saved template, no common jobs.
vi.mock("@/lib/api/client", () => ({
  apiFetch: vi.fn(async (path: string, init?: { method?: string }) => {
    calls.push({ path, method: init?.method ?? "GET" });
    if (path.endsWith("/recipe-templates")) {
      return {
        items: [
          {
            id: "t1",
            name: "Tidy names",
            description: "Trim and title-case",
            step_count: 2,
            steps_json: [
              { step_type: "trim_strings", config: { columns: ["name"], _group: "Tidy names" } },
              { step_type: "tool", config: { tool: "text.title_case", column: "name", _group: "Tidy names" } },
            ],
          },
        ],
      };
    }
    if (path.includes("/lineage/columns")) return { columns: ["name"], types: {} };
    if (path.endsWith("/templates/match")) return { items: [] };
    return {};
  }),
}));

import { RecipeTemplatesDialog } from "./recipe-templates-dialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

describe("templates saved in a project", () => {
  it("are offered, and applying one adds its steps as a group", async () => {
    const onApply = vi.fn();
    const container = document.createElement("div");
    document.body.append(container);
    const root = createRoot(container);
    await act(async () => {
      root.render(
        createElement(RecipeTemplatesDialog, {
          open: true,
          onClose: () => {},
          projectId: "p",
          datasetId: "d",
          onApply,
        }),
      );
    });
    const saved = [...document.querySelectorAll("button")].find((button) => button.textContent?.includes("Tidy names"));
    expect(saved?.textContent).toContain("2 steps");
    await act(async () => saved?.click());
    expect(onApply).toHaveBeenCalledWith(
      [
        { step_type: "trim_strings", config: { columns: ["name"], _group: "Tidy names" } },
        { step_type: "tool", config: { tool: "text.title_case", column: "name", _group: "Tidy names" } },
      ],
      "Tidy names",
    );
    expect(calls.some((call) => call.path === "/projects/p/recipe-templates")).toBe(true);
    act(() => root.unmount());
  });
});
