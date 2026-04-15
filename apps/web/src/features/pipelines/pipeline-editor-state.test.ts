import type { TransformationPreviewResponse, TransformationStep } from "@platform/shared-types";

import {
  addEditorStep,
  buildPipelineDraftPayload,
  getPreviewTotals,
  moveEditorStep,
  removeEditorStep,
  toApiSteps,
  toEditorSteps,
} from "@/features/pipelines/pipeline-editor-state";

describe("pipeline editor state helpers", () => {
  it("round-trips steps between API and editor state", () => {
    const steps: TransformationStep[] = [
      {
        step_type: "rename_columns",
        config: {
          mappings: {
            old_name: "new_name",
          },
        },
      },
      {
        step_type: "fill_nulls",
        config: {
          strategy: "constant",
          columns: ["amount"],
          constant_value: "0",
        },
      },
    ];

    const editorSteps = toEditorSteps(steps);
    expect(editorSteps).toHaveLength(2);
    expect(editorSteps[0].id).toBeTruthy();
    expect(toApiSteps(editorSteps)).toEqual(steps);
  });

  it("adds, removes, and reorders steps", () => {
    let steps = toEditorSteps([
      { step_type: "trim_strings", config: { columns: ["name"] } },
      { step_type: "drop_columns", config: { columns: ["debug"] } },
    ]);

    steps = addEditorStep(steps, "parse_dates");
    expect(steps).toHaveLength(3);
    expect(steps[2].step_type).toBe("parse_dates");

    steps = moveEditorStep(steps, steps[2].id, "up");
    expect(steps[1].step_type).toBe("parse_dates");

    steps = removeEditorStep(steps, steps[0].id);
    expect(steps).toHaveLength(2);
  });

  it("builds save payloads from editor state", () => {
    const steps = toEditorSteps([
      {
        step_type: "filter_rows",
        config: {
          conditions: [
            {
              column: "status",
              operator: "in",
              value: ["active", "trial"],
            },
          ],
        },
      },
    ]);

    const payload = buildPipelineDraftPayload({
      name: "  Normalize status  ",
      description: "  Filter out inactive records  ",
      status: "active",
      steps,
    });

    expect(payload).toEqual({
      name: "Normalize status",
      description: "Filter out inactive records",
      status: "active",
      steps_json: [
        {
          step_type: "filter_rows",
          config: {
            conditions: [
              {
                column: "status",
                operator: "in",
                value: ["active", "trial"],
              },
            ],
          },
        },
      ],
    });
  });

  it("summarizes preview totals for rendering", () => {
    const preview: TransformationPreviewResponse = {
      preview_rows: [],
      preview_columns: ["name"],
      row_count_before: 20,
      row_count_after: 12,
      column_count_before: 5,
      column_count_after: 3,
      schema_before: { ordered_columns: [], columns: [] },
      schema_after: { ordered_columns: [], columns: [] },
      warnings: [],
    };

    expect(getPreviewTotals(preview)).toEqual({
      rows: "20 -> 12",
      columns: "5 -> 3",
    });
  });
});
