/** Editing a recipe together, presence and a dataset's history (C2). */

import type { ActivityItem } from "./activity";

export type CoeditStamp = [number, string];

export type RecipeEditBatch = {
  seq: number;
  client_id: string;
  actor: string | null;
  /** Changes in the merge rules' own shape (apps/web/src/features/studio/coedit.ts). */
  ops: unknown[];
};

export type SavedRecipeRead = {
  revision: number;
  name: string;
  steps_json: { step_type: string; config: Record<string, unknown> }[];
  step_ids: string[];
  revised_by: string | null;
  revised_at: string | null;
};

export type RecipeSharedCopy = {
  epoch: number;
  seq: number;
  /** The whole merged copy, when the Studio is new, behind or in an old epoch. */
  doc: unknown | null;
  batches: RecipeEditBatch[];
  saved: SavedRecipeRead | null;
  revision: number;
  reset_reason: string | null;
  your_role: "viewer" | "operator" | "editor" | "admin" | null;
  needs_approval: boolean;
  open_suggestions: number;
};

export type DatasetActivityKind =
  | "versions"
  | "runs"
  | "checks"
  | "schema"
  | "contracts"
  | "alerts"
  | "incidents"
  | "comments"
  | "changes";

export type DatasetActivityItem = Omit<ActivityItem, "kind"> & { kind: DatasetActivityKind };

export type DatasetActivityResponse = {
  items: DatasetActivityItem[];
  next_offset: number | null;
};
