import { getPipelineEditorUnsavedChangesGuard } from "@/features/pipelines/pipeline-editor-guard";

describe("pipeline editor unsaved changes guard config", () => {
  it("registers the shared guard only when the editor is dirty", () => {
    expect(getPipelineEditorUnsavedChangesGuard(false).when).toBe(false);
    expect(getPipelineEditorUnsavedChangesGuard(true).when).toBe(true);
  });

  it("uses editor-specific copy for the shared modal", () => {
    expect(getPipelineEditorUnsavedChangesGuard(true)).toEqual({
      when: true,
      title: "Leave the pipeline editor?",
      message:
        "You have unsaved pipeline edits. Leave this page only if you are comfortable discarding those changes.",
    });
  });
});
