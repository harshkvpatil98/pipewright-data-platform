/** Contracts for column lineage and impact analysis. Mirrors service-lineage. */

export type LineageNodeKind = "dataset" | "pipeline" | "source";
export type LineageEdgeKind = "produces" | "consumes" | "joins" | "unions" | "derives";
export type ImpactSeverity = "breaks" | "changes" | "informational";
export type ConsumerKind = "pipeline" | "quality_rule" | "workflow" | "dataset";

export type ColumnEdge = {
  step_index: number;
  step_type: string;
  from_column: string | null;
  to_column: string;
  kind: string;
  from_dataset_id: string | null;
};

export type ColumnRead = {
  step_index: number;
  step_type: string;
  column: string;
  purpose: string;
};

export type ColumnOrigin = {
  column: string;
  dataset_id: string | null;
  dataset_name: string | null;
  created_at_step: number | null;
};

export type StepLineage = {
  step_index: number;
  step_type: string;
  step_name: string;
  input_columns: string[];
  output_columns: string[];
  added_columns: string[];
  removed_columns: string[];
  edges: ColumnEdge[];
  reads: ColumnRead[];
  notes: string[];
  dynamic: boolean;
};

export type ColumnTrace = {
  column: string;
  origins: ColumnOrigin[];
  edges: ColumnEdge[];
  unresolved: boolean;
  summary: string;
};

export type ColumnSummary = {
  column: string;
  origins: ColumnOrigin[];
  /** False when the column is carried through untouched from a source. */
  derived: boolean;
};

export type LineageNode = {
  id: string;
  kind: LineageNodeKind;
  name: string;
  subtitle: string | null;
  /** Negative upstream of the focus dataset, 0 for it, positive downstream. */
  depth: number;
  is_focus: boolean;
};

export type LineageEdge = {
  from_id: string;
  to_id: string;
  kind: LineageEdgeKind;
  label: string | null;
};

export type DatasetLineage = {
  dataset_id: string;
  dataset_name: string;
  nodes: LineageNode[];
  edges: LineageEdge[];
  columns: ColumnSummary[];
  steps: StepLineage[];
  notes: string[];
  partial: boolean;
};

export type ImpactFinding = {
  kind: ConsumerKind;
  id: string;
  name: string;
  severity: ImpactSeverity;
  detail: string;
  columns: string[];
  project_path: string | null;
};

export type ImpactAnalysis = {
  dataset_id: string;
  columns: string[];
  findings: ImpactFinding[];
  breaks_count: number;
  changes_count: number;
  summary: string;
};

export type LineageColumnListResponse = {
  dataset_id: string;
  columns: string[];
  /** Column name to inferred type, so callers can pick a sensible default. */
  types: Record<string, string>;
};
