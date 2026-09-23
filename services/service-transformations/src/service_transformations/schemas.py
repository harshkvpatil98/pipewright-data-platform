from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from service_datasets.schemas import DatasetDetailRead
from service_pipeline_runs.schemas import PipelineRunRead


class TransformationStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    step_type: str
    config: dict[str, Any]


class TransformationPipelineCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active"] = "draft"
    steps_json: list[dict[str, Any]] = Field(default_factory=list)


class TransformationPipelineUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    status: Literal["draft", "active"] | None = None
    steps_json: list[dict[str, Any]] | None = None


class TransformationPipelineRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    base_dataset_id: uuid.UUID
    created_by_user_id: uuid.UUID | None
    name: str
    description: str | None
    status: Literal["draft", "active"]
    steps_json: list[TransformationStep]
    step_count: int
    created_at: datetime
    updated_at: datetime


class TransformationPipelineListResponse(BaseModel):
    items: list[TransformationPipelineRead]


class TransformationPreviewRequest(BaseModel):
    steps: list[dict[str, Any]] = Field(default_factory=list)


class TransformationPreviewSchemaColumn(BaseModel):
    name: str
    #: The seven-word vocabulary the API has always spoken. Kept because stored
    #: dataset schemas and two dozen call sites still read it.
    inferred_type: str
    #: The same column read into the canonical lattice, where the answer can
    #: carry precision, timezone awareness and exactness. Optional so responses
    #: written before the lattice existed still validate.
    canonical_type: str | None = None
    nullable: bool | None = None


class TransformationStepOutcome(BaseModel):
    """What one step did, so the Studio can show its effect beside it."""

    index: int
    step_type: str
    rows_before: int
    rows_after: int
    columns_before: int
    columns_after: int


class ExecutionStepPlacement(BaseModel):
    """Where one step would run, and why."""

    node: str
    pushed: bool
    reason: str


class ExecutionPlanRead(BaseModel):
    """Where the work would happen on a full run against this dataset's source.

    Reported honestly and labelled: a preview always reads the materialised
    file, so what it describes is the *run*, not the preview. Saying "nothing
    pushed down, because this dataset is a stored file" is useful information --
    it is the reason a pipeline over a hundred million rows would be slow.
    """

    source_type: str
    surface: str
    pushed_steps: int
    local_steps: int
    sql: str | None = None
    placements: list[ExecutionStepPlacement] = []
    note: str = ""


class TransformationPreviewSchema(BaseModel):
    ordered_columns: list[str]
    columns: list[TransformationPreviewSchemaColumn]


class TransformationPreviewResponse(BaseModel):
    preview_rows: list[dict[str, Any]]
    preview_columns: list[str]
    row_count_before: int
    row_count_after: int
    column_count_before: int
    column_count_after: int
    schema_before: TransformationPreviewSchema
    schema_after: TransformationPreviewSchema
    warnings: list[str]
    #: One entry per applied step, in order. Empty when there are no steps.
    step_outcomes: list[TransformationStepOutcome] = []
    #: Where the work would run on a full run. None when it cannot be determined.
    execution_plan: ExecutionPlanRead | None = None


class TransformationRunResponse(BaseModel):
    run: PipelineRunRead
    dataset: DatasetDetailRead


class ReplayComparison(BaseModel):
    """How a replay's output compared with the original run's (phase-18 §3).
    Equivalence is: same ordered columns, same canonical types, same row
    multiset (values as text, null equal to null, order ignored)."""

    method: str
    columns_equal: bool
    types_equal: bool
    rows_equal: bool
    rows_original: int | None = None
    rows_replay: int | None = None
    differences: list[str] = Field(default_factory=list)

    @property
    def equivalent(self) -> bool:
        return self.columns_equal and self.types_equal and self.rows_equal


class ReplayResult(BaseModel):
    #: `equivalent` / `divergent` (it ran; compared); `incompatible` (semantics
    #: changed -- cannot be reproduced); `unavailable` (an input is gone);
    #: `failed` (the replay run itself failed); `unverifiable` (it ran but the
    #: original output is gone, so there is nothing to compare with).
    status: Literal["equivalent", "divergent", "incompatible", "unavailable", "failed", "unverifiable"]
    reason: str | None = None
    original_run_id: uuid.UUID
    replay_run_id: uuid.UUID | None = None
    replay_dataset_id: uuid.UUID | None = None
    original_output: dict[str, Any] | None = None
    replay_output: dict[str, Any] | None = None
    comparison: ReplayComparison | None = None
    #: The instant the original run froze -- and the replay evaluated at.
    evaluated_at: datetime | None = None
    semantic_version: str | None = None


# ------------------------------------------------------------- tool library


class ToolParamRead(BaseModel):
    key: str
    label: str
    kind: str
    required: bool
    default: Any = None
    options: list[str] = Field(default_factory=list)
    help: str = ""
    placeholder: str = ""
    minimum: float | None = None
    maximum: float | None = None


class ToolExampleRead(BaseModel):
    rows: list[dict[str, Any]]
    params: dict[str, Any]
    column: str | None
    output: str | None
    expect: list[Any]
    note: str = ""


class ToolRead(BaseModel):
    name: str
    title: str
    category: str
    summary: str
    synonyms: list[str]
    accepts: str
    column_scoped: bool
    params: list[ToolParamRead]
    example: ToolExampleRead


class ToolCatalogueResponse(BaseModel):
    categories: list[str]
    items: list[ToolRead]


class ToolPreviewRequest(BaseModel):
    """Apply one tool to a handful of rows, to show what it would do."""

    tool: str = Field(min_length=1, max_length=120)
    column: str | None = Field(default=None, max_length=300)
    into: str | None = Field(default=None, max_length=300)
    params: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list, max_length=200)


class ToolPreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict[str, Any]]
    warnings: list[str] = Field(default_factory=list)
