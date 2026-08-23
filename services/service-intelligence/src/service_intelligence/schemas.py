"""Contracts for suggestions, detection, and explanation."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]
MaskingStrategy = Literal["redact", "hash", "partial", "tokenize", "drop"]


class PiiFindingRead(BaseModel):
    column: str
    kind: str
    label: str
    confidence: Confidence
    name_matched: bool
    value_match_rate: float
    sample_size: int
    suggested_strategy: MaskingStrategy
    reason: str
    guidance: str


class PiiScanResponse(BaseModel):
    dataset_id: uuid.UUID
    dataset_name: str
    findings: list[PiiFindingRead]
    columns_scanned: int
    summary: str
    # The detectors are patterns and checksums, not a model. Stated in the
    # payload so a caller cannot mistake this for something it is not.
    method: str = "pattern and checksum matching over sampled values"


class MaskingRequest(BaseModel):
    column: str = Field(min_length=1, max_length=200)
    kind: str = Field(min_length=1, max_length=40)
    strategy: MaskingStrategy | None = None


class MaskingResponse(BaseModel):
    column: str
    strategy: MaskingStrategy
    step: dict[str, Any]
    note: str


class JoinSuggestionRequest(BaseModel):
    right_dataset_id: uuid.UUID
    limit: int = Field(default=5, ge=1, le=20)


class JoinCandidateRead(BaseModel):
    left_column: str
    right_column: str
    overlap: float
    reverse_overlap: float
    left_unique: bool
    right_unique: bool
    name_score: float
    score: float
    kind: str
    confidence: Confidence
    explanation: str
    warnings: list[str]
    step: dict[str, Any]


class JoinSuggestionResponse(BaseModel):
    left_dataset_id: uuid.UUID
    right_dataset_id: uuid.UUID
    candidates: list[JoinCandidateRead]
    summary: str


class DuplicateRequest(BaseModel):
    column: str = Field(min_length=1, max_length=200)
    threshold: float = Field(default=0.86, ge=0.5, le=1.0)
    limit: int = Field(default=50, ge=1, le=200)


class MatchCandidateRead(BaseModel):
    left_value: str
    right_value: str
    left_rows: list[int]
    right_rows: list[int]
    row_count: int
    score: float
    confidence: Confidence
    reason: str


class DuplicateResponse(BaseModel):
    dataset_id: uuid.UUID
    column: str
    distinct_values: int
    candidates: list[MatchCandidateRead]
    comparisons: int
    truncated: bool
    summary: str
    merge_step: dict[str, Any] | None = None


class DescribeRequest(BaseModel):
    dataset_id: uuid.UUID
    sentence: str = Field(min_length=1, max_length=1000)


class ParsedIntentRead(BaseModel):
    action: str
    step: dict[str, Any]
    phrase: str
    explanation: str


class DescribeResponse(BaseModel):
    dataset_id: uuid.UUID
    steps: list[dict[str, Any]]
    understood: list[ParsedIntentRead]
    not_understood: list[str]
    unknown_columns: list[str]
    complete: bool
    summary: str
    # Said out loud in the response: this reads a fixed set of phrasings.
    method: str = "phrase matching against a fixed vocabulary, not a language model"


class ExplanationCandidateRead(BaseModel):
    kind: str
    at: str
    summary: str
    hours_apart: float
    score: float
    sentence: str
    detail: dict[str, Any]


class ExplainResponse(BaseModel):
    dataset_id: uuid.UUID
    metric: str
    change_description: str
    candidates: list[ExplanationCandidateRead]
    summary: str
    searched_events: int
    # Correlation, and labelled as such.
    method: str = "events correlated by time; this shows what changed together, not what caused what"


class DraftRead(BaseModel):
    subject: str
    text: str
    facts_used: list[str]


class DocumentationResponse(BaseModel):
    dataset_id: uuid.UUID
    dataset: DraftRead
    columns: list[DraftRead]
    # A draft, offered for editing rather than presented as authoritative.
    is_draft: bool = True
    summary: str


class RuleSuggestionRead(BaseModel):
    name: str
    rule_type: str
    severity: str
    config: dict[str, Any]
    rationale: str
    confidence: Confidence


class RuleSuggestionResponse(BaseModel):
    dataset_id: uuid.UUID
    items: list[RuleSuggestionRead]
    summary: str
