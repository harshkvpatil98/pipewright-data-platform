"""Contracts for lineage and impact analysis. Mirrored in shared-types."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

NodeKind = Literal["dataset", "pipeline", "source"]
EdgeKind = Literal["produces", "consumes", "joins", "unions", "derives"]
ImpactSeverity = Literal["breaks", "changes", "informational"]
ConsumerKind = Literal["pipeline", "quality_rule", "workflow", "dataset"]


class ColumnEdgeRead(BaseModel):
    step_index: int
    step_type: str
    from_column: str | None
    to_column: str
    kind: str
    from_dataset_id: str | None = None


class ColumnReadRead(BaseModel):
    step_index: int
    step_type: str
    column: str
    purpose: str


class ColumnOriginRead(BaseModel):
    column: str
    dataset_id: str | None
    dataset_name: str | None = None
    created_at_step: int | None = None


class StepLineageRead(BaseModel):
    step_index: int
    step_type: str
    step_name: str
    input_columns: list[str]
    output_columns: list[str]
    added_columns: list[str]
    removed_columns: list[str]
    edges: list[ColumnEdgeRead]
    reads: list[ColumnReadRead]
    notes: list[str]
    dynamic: bool


class ColumnTraceRead(BaseModel):
    column: str
    origins: list[ColumnOriginRead]
    edges: list[ColumnEdgeRead]
    unresolved: bool
    # A plain-language sentence, because the graph is not the answer people want.
    summary: str


class ColumnSummaryRead(BaseModel):
    column: str
    origins: list[ColumnOriginRead]
    # False when the column is carried through untouched from a source.
    derived: bool


class LineageNodeRead(BaseModel):
    id: str
    kind: NodeKind
    name: str
    subtitle: str | None = None
    # Negative upstream of the focus dataset, 0 for it, positive downstream.
    depth: int
    is_focus: bool = False


class LineageEdgeRead(BaseModel):
    from_id: str
    to_id: str
    kind: EdgeKind
    label: str | None = None


class DatasetLineageResponse(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    nodes: list[LineageNodeRead]
    edges: list[LineageEdgeRead]
    columns: list[ColumnSummaryRead]
    steps: list[StepLineageRead]
    notes: list[str]
    # True when some column list could only be partially resolved.
    partial: bool


class ImpactFindingRead(BaseModel):
    kind: ConsumerKind
    id: str
    name: str
    severity: ImpactSeverity
    detail: str
    columns: list[str]
    project_path: str | None = None


class ImpactRequest(BaseModel):
    columns: list[str] = Field(min_length=1, max_length=100)


class ImpactResponse(BaseModel):
    dataset_id: uuid.UUID
    columns: list[str]
    findings: list[ImpactFindingRead]
    breaks_count: int
    changes_count: int
    summary: str


class LineageColumnListResponse(BaseModel):
    dataset_id: uuid.UUID
    columns: list[str]
    # Column name to inferred type. Callers that have to choose a sensible
    # default -- a chart builder picking a measure, say -- need to know which
    # columns are numbers, and asking for the whole dataset detail to find out
    # is a lot of payload for one fact.
    types: dict[str, str] = {}


def as_dict(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(mode="json")
