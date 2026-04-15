import type { UnsavedChangesGuardOptions } from "@/features/navigation/unsaved-changes-guard-controller";

export function getPipelineEditorUnsavedChangesGuard(
  hasUnsavedChanges: boolean,
): UnsavedChangesGuardOptions {
  return {
    when: hasUnsavedChanges,
    title: "Leave the pipeline editor?",
    message:
      "You have unsaved pipeline edits. Leave this page only if you are comfortable discarding those changes.",
  };
}
