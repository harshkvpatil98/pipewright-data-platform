/** Contracts for membership, governance, and environments. */

export type ProjectRole = "viewer" | "operator" | "editor" | "admin";
export type ProjectEnvironment = "development" | "staging" | "production";

export type ProjectMember = {
  id: string | null;
  user_id: string;
  username: string;
  role: ProjectRole;
  /** True for the project's owner, who has no membership row to edit. */
  is_owner: boolean;
  invited_by_username: string | null;
  created_at: string | null;
};

export type MemberListResponse = {
  items: ProjectMember[];
  /** What the caller may do, so the UI can hide controls it would be refused. */
  your_role: ProjectRole;
};

export type RoleReference = {
  role: ProjectRole;
  description: string;
};

export type RoleCatalogResponse = {
  items: RoleReference[];
};

export type ResourceType = "workflow" | "pipeline" | "quality_rule" | "extraction_job";
export type CommentTargetType =
  | "dataset"
  | "workflow"
  | "pipeline"
  | "run"
  | "incident"
  | "change_request"
  | "dashboard"
  | "chart";
export type ChangeStatus = "open" | "approved" | "rejected" | "withdrawn";
export type AuditOutcome = "succeeded" | "denied" | "failed";

export type SnapshotChange = {
  path: string;
  kind: "added" | "removed" | "changed";
  before: unknown;
  after: unknown;
};

export type SnapshotDiff = {
  changes: SnapshotChange[];
  truncated: boolean;
  identical: boolean;
  summary: string;
};

export type ResourceVersion = {
  id: string;
  resource_type: ResourceType;
  resource_id: string;
  version: number;
  name: string;
  change_summary: string | null;
  created_by_user_id: string | null;
  created_by_username: string | null;
  restored_from_version: number | null;
  created_at: string;
};

export type VersionListResponse = {
  items: ResourceVersion[];
  resource_type: ResourceType;
  resource_id: string;
};

export type VersionDiffResponse = {
  left_version: number;
  right_version: number;
  diff: SnapshotDiff;
};

export type RestoreResponse = {
  resource_type: ResourceType;
  resource_id: string;
  restored_from_version: number;
  new_version: number;
  summary: string;
};

export type ChangeRequest = {
  id: string;
  project_id: string;
  resource_type: ResourceType;
  resource_id: string;
  title: string;
  description: string | null;
  status: ChangeStatus;
  change_summary: string | null;
  requested_by_user_id: string | null;
  requested_by_username: string | null;
  reviewed_by_user_id: string | null;
  reviewed_by_username: string | null;
  reviewed_at: string | null;
  review_note: string | null;
  created_at: string;
};

export type ChangeRequestDetail = ChangeRequest & {
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown>;
  diff: SnapshotDiff;
};

export type ChangeRequestListResponse = {
  items: ChangeRequest[];
  open_count: number;
};

export type AuditEntry = {
  id: string;
  project_id: string | null;
  actor_user_id: string | null;
  actor_username: string | null;
  method: string;
  path: string;
  action: string;
  resource_type: string | null;
  resource_id: string | null;
  status_code: number;
  outcome: AuditOutcome;
  correlation_id: string | null;
  duration_ms: number | null;
  created_at: string;
  /** What it did, in words: "ran a recipe". */
  summary?: string;
  /** The name of what it touched, while that still exists. */
  object_name?: string | null;
};

export type AuditListResponse = {
  items: AuditEntry[];
};

/** The cell a thread on a dataset is about (C2). */
export type CellAnchor = {
  column: string;
  /** The row by its identifier's value, which survives new versions... */
  row_key_column: string | null;
  row_key_value: string | null;
  /** ...or by its number in one version. */
  row_number: number | null;
  version: number | null;
};

export type Comment = {
  id: string;
  project_id: string;
  target_type: CommentTargetType;
  target_id: string;
  body: string;
  author_user_id: string | null;
  author_username: string | null;
  mentions: string[];
  resolved_at: string | null;
  resolved_by_username: string | null;
  created_at: string;
  parent_id: string | null;
  anchor: CellAnchor | null;
  /** The step of a recipe a thread is about, by the step's id (E1). */
  step_id?: string | null;
  /** On a thread's first comment, the replies to it, oldest first. */
  replies: Comment[];
};

export type CommentListResponse = {
  /** Threads: each first comment with its replies. */
  items: Comment[];
  open_count: number;
};

export type UnresolvedReference = {
  key: string;
  value: string;
  where: string;
};

export type PromoteResponse = {
  source_project_id: string;
  target_project_id: string;
  resource_type: ResourceType;
  new_resource_id: string;
  /** References with no match in the target; left empty rather than guessed. */
  unresolved: UnresolvedReference[];
  summary: string;
};
