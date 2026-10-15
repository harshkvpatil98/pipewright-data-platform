/** Data contracts: promises about a dataset that new data must keep (Phase 19, C1). */

export type ContractColumnKind =
  | "text"
  | "whole_number"
  | "decimal_number"
  | "date"
  | "date_time"
  | "true_false"
  | "any";

export type ContractColumn = {
  name: string;
  kind: ContractColumnKind;
  always_filled: boolean;
  no_repeats: boolean;
  allowed_values: string[] | null;
  lowest: number | null;
  highest: number | null;
};

export type ContractTerms = {
  columns: ContractColumn[];
  other_columns: "allowed" | "not_allowed";
  rows_at_least: number | null;
  rows_at_most: number | null;
  largest_drop_percent: number | null;
  new_data_every_hours: number | null;
};

export type ContractEnforcement = "stop" | "warn";

export type ContractStatus = "kept" | "broken" | "not_checked";

export type ContractProblem = {
  id: string;
  kind: "new_data" | "overdue";
  outcome: "stopped" | "let_through" | "overdue";
  source_type: "recipe" | "import" | "stream" | "rollback" | "erasure" | "check" | null;
  source_id: string | null;
  source_name: string | null;
  reasons: string[];
  times_seen: number;
  first_seen_at: string;
  last_seen_at: string;
  resolved_at: string | null;
  pipeline_run_id: string | null;
  contract_version: number;
};

export type ContractConsumer = {
  kind: "recipe" | "check" | "chart" | "dashboard" | "metric" | "delivery" | "workflow";
  id: string;
  name: string;
};

export type DataContract = {
  id: string;
  project_id: string;
  dataset_id: string;
  dataset_name: string;
  owner_user_id: string | null;
  owner_username: string | null;
  description: string | null;
  enforcement: ContractEnforcement;
  terms: ContractTerms;
  version: number;
  status: ContractStatus;
  open_problems: number;
  followers: number;
  following: boolean;
  last_checked_at: string | null;
  created_at: string;
  updated_at: string;
};

export type DataContractDetail = DataContract & {
  problems: ContractProblem[];
  consumers: ContractConsumer[];
};

export type ContractPerson = { id: string; username: string };

export type DatasetContractResponse = {
  contract: DataContractDetail | null;
  draft: ContractTerms;
  /** Who may own it: the project's people. */
  people: ContractPerson[];
  /** The caller's role in the project, so the page offers only what it may do. */
  your_role: "viewer" | "operator" | "editor" | "admin" | null;
};

export type ContractCheck = {
  kept: boolean;
  reasons: string[];
  rows_checked: number;
  version_number: number | null;
};

export type ContractSaveResponse = DatasetContractResponse & {
  current: ContractCheck | null;
};

export type DataContractWrite = {
  description: string | null;
  owner_user_id: string | null;
  enforcement: ContractEnforcement;
  terms: ContractTerms;
};

export type DataContractListResponse = { items: DataContract[] };

export type ContractVersion = {
  version: number;
  description: string | null;
  enforcement: ContractEnforcement;
  owner_username: string | null;
  terms: ContractTerms;
  changes: string[];
  created_by_username: string | null;
  created_at: string;
};

export type ContractHistoryResponse = { items: ContractVersion[] };
