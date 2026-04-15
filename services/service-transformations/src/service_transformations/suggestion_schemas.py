from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

ConfidenceLevel = Literal['low', 'medium', 'high']


class TransformationSourceSignal(BaseModel):
    model_config = {'extra': 'forbid'}

    signal: str
    detail: str | None = None
    value: Any | None = None


class TransformationSuggestion(BaseModel):
    model_config = {'extra': 'forbid'}

    suggestion_id: uuid.UUID
    step_type: str
    title: str
    explanation: str
    confidence: ConfidenceLevel
    config: dict[str, Any]
    source_signals: list[TransformationSourceSignal] = Field(default_factory=list)
    priority: int = Field(default=50, ge=0, le=100)


class DatasetTransformationSuggestionsResponse(BaseModel):
    model_config = {'extra': 'forbid'}

    dataset_id: uuid.UUID
    project_id: uuid.UUID
    suggestions: list[TransformationSuggestion]
