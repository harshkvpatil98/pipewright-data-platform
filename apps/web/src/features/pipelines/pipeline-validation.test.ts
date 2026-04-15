import type { TransformationStep } from "@platform/shared-types";

import {
  createDefaultStep,
  isPipelineDraftValid,
  serializePipelineEditorBaseline,
  toEditorSteps,
  validateEditorStep,
  validatePipelineName,
} from "@/features/pipelines/pipeline-editor-state";

describe("validatePipelineName", () => {
  it("rejects empty and whitespace-only names", () => {
    expect(validatePipelineName("")).toBe("Pipeline name is required.");
    expect(validatePipelineName("   ")).toBe("Pipeline name is required.");
  });

  it("rejects names shorter than two characters after trim", () => {
    expect(validatePipelineName("a")).toBe("Pipeline name must be at least 2 characters.");
    expect(validatePipelineName(" a ")).toBe("Pipeline name must be at least 2 characters.");
  });

  it("accepts valid trimmed names", () => {
    expect(validatePipelineName("ab")).toBeNull();
    expect(validatePipelineName("  My pipeline  ")).toBeNull();
  });
});

describe("validateEditorStep", () => {
  it("flags incomplete rename mappings", () => {
    const step = toEditorSteps([
      { step_type: "rename_columns", config: { mappings: { a: "b" } } },
    ])[0];
    const cleared = {
      ...step,
      config: { rows: [{ from: "", to: "x" }] },
    };
    const v = validateEditorStep(cleared);
    expect(v.valid).toBe(false);
    expect(v.fields.mapping_0_from).toBeTruthy();
    expect(v.summary).toBeTruthy();
  });

  it("accepts valid trim_strings when columns are present", () => {
    const step = createDefaultStep("trim_strings");
    const v = validateEditorStep({
      ...step,
      config: { ...step.config, columns: "id, name" },
    });
    expect(v.valid).toBe(true);
  });

  it("requires columns for column-based steps", () => {
    const step = createDefaultStep("drop_columns");
    const v = validateEditorStep(step);
    expect(v.valid).toBe(false);
    expect(v.fields.columns).toBeTruthy();
  });
});

describe("isPipelineDraftValid", () => {
  it("is false when name is invalid", () => {
    const steps = toEditorSteps([
      { step_type: "trim_strings", config: { columns: ["x"] } } as TransformationStep,
    ]);
    expect(isPipelineDraftValid({ name: "", steps })).toBe(false);
  });

  it("is false when any step is invalid", () => {
    const steps = toEditorSteps([{ step_type: "trim_strings", config: { columns: [] } }]);
    expect(isPipelineDraftValid({ name: "OK name", steps })).toBe(false);
  });

  it("is true when name and steps validate", () => {
    const steps = toEditorSteps([
      { step_type: "trim_strings", config: { columns: ["a"] } } as TransformationStep,
    ]);
    expect(isPipelineDraftValid({ name: "Valid", steps })).toBe(true);
  });
});

describe("serializePipelineEditorBaseline and dirty detection", () => {
  it("matches when state is unchanged", () => {
    const steps = toEditorSteps([
      { step_type: "trim_strings", config: { columns: ["a"] } } as TransformationStep,
    ]);
    const a = serializePipelineEditorBaseline({
      name: "P",
      description: "",
      status: "draft",
      baseDatasetId: "ds1",
      steps,
    });
    const b = serializePipelineEditorBaseline({
      name: "P",
      description: "",
      status: "draft",
      baseDatasetId: "ds1",
      steps,
    });
    expect(a).toBe(b);
  });

  it("detects metadata changes", () => {
    const steps = toEditorSteps([]);
    const base = serializePipelineEditorBaseline({
      name: "P",
      description: "",
      status: "draft",
      baseDatasetId: null,
      steps,
    });
    const next = serializePipelineEditorBaseline({
      name: "Q",
      description: "",
      status: "draft",
      baseDatasetId: null,
      steps,
    });
    expect(base).not.toBe(next);
  });
});

describe("action gating helpers (pure)", () => {
  function saveDisabled(args: {
    saving: boolean;
    previewLoading: boolean;
    hasUnsavedChanges: boolean;
    draftValid: boolean;
    baseDatasetId: string | null;
  }) {
    return (
      args.saving ||
      args.previewLoading ||
      !args.hasUnsavedChanges ||
      !args.draftValid ||
      !args.baseDatasetId
    );
  }

  function previewDisabled(args: {
    saving: boolean;
    previewLoading: boolean;
    draftValid: boolean;
    baseDatasetId: string | null;
  }) {
    return args.previewLoading || args.saving || !args.baseDatasetId || !args.draftValid;
  }

  it("disables save when unchanged or invalid", () => {
    expect(
      saveDisabled({
        saving: false,
        previewLoading: false,
        hasUnsavedChanges: false,
        draftValid: true,
        baseDatasetId: "x",
      }),
    ).toBe(true);
    expect(
      saveDisabled({
        saving: false,
        previewLoading: false,
        hasUnsavedChanges: true,
        draftValid: false,
        baseDatasetId: "x",
      }),
    ).toBe(true);
    expect(
      saveDisabled({
        saving: false,
        previewLoading: false,
        hasUnsavedChanges: true,
        draftValid: true,
        baseDatasetId: "x",
      }),
    ).toBe(false);
  });

  it("blocks preview when invalid even if dataset is set", () => {
    expect(
      previewDisabled({
        saving: false,
        previewLoading: false,
        draftValid: false,
        baseDatasetId: "x",
      }),
    ).toBe(true);
  });
});
