from __future__ import annotations

import uuid
from typing import Literal

from datetime import datetime

from pydantic import BaseModel, Field


class ComparisonDatasetSide(BaseModel):
    id: uuid.UUID
    name: str
    is_derived: bool
    row_count: int | None
    column_count: int | None


class ProfileComparisonDelta(BaseModel):
    duplicate_row_count_before: int | None
    duplicate_row_count_after: int | None
    completeness_score_before: float | None
    completeness_score_after: float | None


class SchemaTypeChange(BaseModel):
    column_name: str
    before_type: str
    after_type: str


class SchemaComparisonDelta(BaseModel):
    added_columns: list[str]
    removed_columns: list[str]
    changed_type_columns: list[SchemaTypeChange]


class LineageComparisonContext(BaseModel):
    related_by_parent_child: bool
    parent_dataset_id: uuid.UUID | None = None
    created_from_pipeline_id: uuid.UUID | None = None
    related_run_id: uuid.UUID | None = None


class DatasetComparisonSummary(BaseModel):
    left_dataset: ComparisonDatasetSide
    right_dataset: ComparisonDatasetSide
    row_count_delta: int | None
    column_count_delta: int | None
    profile_delta: ProfileComparisonDelta
    schema_delta: SchemaComparisonDelta
    lineage_context: LineageComparisonContext
    comparison_notes: list[str]


class RunComparisonDatasetRef(BaseModel):
    id: uuid.UUID
    name: str = ""


class RunComparisonSummary(BaseModel):
    run_id: uuid.UUID
    run_type: str
    status: str
    pipeline_id: uuid.UUID | None = None
    base_dataset: RunComparisonDatasetRef | None = None
    derived_dataset: RunComparisonDatasetRef | None = None
    row_count_before: int | None = None
    row_count_after: int | None = None
    column_count_before: int | None = None
    column_count_after: int | None = None
    step_count: int | None = None
    summary_available: bool = False
    comparison_notes: list[str] = Field(default_factory=list)
    raw_summary_present: bool = False


StatisticalTestType = Literal["welch_t_test", "proportion_z_test", "chi_square_distribution"]


class DatasetStatisticalTestRequest(BaseModel):
    test_type: StatisticalTestType
    column_name: str = Field(..., min_length=1, max_length=255)


class StatisticalTestDatasetSide(BaseModel):
    id: uuid.UUID
    name: str
    sample_size: int


class DatasetStatisticalTestResult(BaseModel):
    test_type: str
    column_name: str
    left_dataset: StatisticalTestDatasetSide
    right_dataset: StatisticalTestDatasetSide
    statistic: float | None = None
    p_value: float | None = None
    effect_summary: str = ""
    assumptions_notes: list[str] = Field(default_factory=list)
    interpretation: str = ""
    warnings: list[str] = Field(default_factory=list)
    left_mean: float | None = None
    right_mean: float | None = None
    left_proportion: float | None = None
    right_proportion: float | None = None
    category_count: int | None = None


class SavedStatisticalTestCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    description: str | None = Field(None, max_length=4000)
    left_dataset_id: uuid.UUID
    right_dataset_id: uuid.UUID
    test_type: StatisticalTestType
    column_name: str = Field(..., min_length=1, max_length=255)
    options_json: dict | list | None = None


class SavedStatisticalTestUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=160)
    description: str | None = Field(None, max_length=4000)


class SavedStatisticalTestRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: str | None
    test_type: str
    column_name: str
    options_json: dict | list | None
    left_dataset_id: uuid.UUID
    right_dataset_id: uuid.UUID
    left_dataset_name: str
    right_dataset_name: str
    created_by_user_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class SavedStatisticalTestListItem(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    test_type: str
    column_name: str
    left_dataset_id: uuid.UUID
    right_dataset_id: uuid.UUID
    left_dataset_name: str
    right_dataset_name: str
    last_run_at: datetime | None
    updated_at: datetime


class SavedStatisticalTestListResponse(BaseModel):
    items: list[SavedStatisticalTestListItem]


class SavedStatisticalTestRunRead(BaseModel):
    id: uuid.UUID
    saved_test_id: uuid.UUID
    project_id: uuid.UUID
    status: str
    executed_by_user_id: uuid.UUID | None
    result: DatasetStatisticalTestResult | None = None
    error_message: str | None = None
    warnings_json: list[str] | None = None
    created_at: datetime


class SavedStatisticalTestRunsResponse(BaseModel):
    items: list[SavedStatisticalTestRunRead]


class SavedStatisticalTestDetail(BaseModel):
    saved_test: SavedStatisticalTestRead
    runs: list[SavedStatisticalTestRunRead]
    comparison_note: str | None = None
