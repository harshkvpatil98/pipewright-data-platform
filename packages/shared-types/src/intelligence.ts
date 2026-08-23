/**
 * Contracts for suggestions, detection, and explanation.
 *
 * Every response carries a `method` field. That is deliberate: these are
 * deterministic analyses -- patterns, checksums, set overlap, string similarity,
 * time correlation -- and a suggestion that sounds authoritative and is wrong is
 * worse than one that shows its working.
 */

export type Confidence = "high" | "medium" | "low";
export type MaskingStrategy = "redact" | "hash" | "partial" | "tokenize" | "drop";

export type PiiFinding = {
  column: string;
  kind: string;
  label: string;
  confidence: Confidence;
  name_matched: boolean;
  value_match_rate: number;
  sample_size: number;
  suggested_strategy: MaskingStrategy;
  reason: string;
  guidance: string;
};

export type PiiScanResponse = {
  dataset_id: string;
  dataset_name: string;
  findings: PiiFinding[];
  columns_scanned: number;
  summary: string;
  method: string;
};

export type MaskingResponse = {
  column: string;
  strategy: MaskingStrategy;
  step: Record<string, unknown>;
  note: string;
};

export type JoinCandidate = {
  left_column: string;
  right_column: string;
  overlap: number;
  reverse_overlap: number;
  left_unique: boolean;
  right_unique: boolean;
  name_score: number;
  score: number;
  kind: "one_to_one" | "one_to_many" | "many_to_one" | "many_to_many";
  confidence: Confidence;
  explanation: string;
  warnings: string[];
  step: Record<string, unknown>;
};

export type JoinSuggestionResponse = {
  left_dataset_id: string;
  right_dataset_id: string;
  candidates: JoinCandidate[];
  summary: string;
};

export type MatchCandidate = {
  left_value: string;
  right_value: string;
  left_rows: number[];
  right_rows: number[];
  row_count: number;
  score: number;
  confidence: Confidence;
  reason: string;
};

export type DuplicateResponse = {
  dataset_id: string;
  column: string;
  distinct_values: number;
  candidates: MatchCandidate[];
  comparisons: number;
  truncated: boolean;
  summary: string;
  merge_step: Record<string, unknown> | null;
};

export type ParsedIntent = {
  action: string;
  step: Record<string, unknown>;
  phrase: string;
  explanation: string;
};

export type DescribeResponse = {
  dataset_id: string;
  steps: Record<string, unknown>[];
  understood: ParsedIntent[];
  /** Phrases it could not read; left out rather than guessed at. */
  not_understood: string[];
  unknown_columns: string[];
  complete: boolean;
  summary: string;
  method: string;
};

export type ExplanationCandidate = {
  kind: string;
  at: string;
  summary: string;
  hours_apart: number;
  score: number;
  sentence: string;
  detail: Record<string, unknown>;
};

export type ExplainResponse = {
  dataset_id: string;
  metric: string;
  change_description: string;
  candidates: ExplanationCandidate[];
  summary: string;
  searched_events: number;
  method: string;
};

export type DocumentationDraft = {
  subject: string;
  text: string;
  facts_used: string[];
};

export type DocumentationResponse = {
  dataset_id: string;
  dataset: DocumentationDraft;
  columns: DocumentationDraft[];
  is_draft: boolean;
  summary: string;
};

export type RuleSuggestion = {
  name: string;
  rule_type: string;
  severity: string;
  config: Record<string, unknown>;
  rationale: string;
  confidence: Confidence;
};

export type RuleSuggestionResponse = {
  dataset_id: string;
  items: RuleSuggestion[];
  summary: string;
};
