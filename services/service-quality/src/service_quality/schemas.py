from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from service_quality.rules.base import SEVERITIES
from service_quality.rules.evaluators import SUPPORTED_RULE_TYPES

_RULE_TYPE_PATTERN = "^(" + "|".join(SUPPORTED_RULE_TYPES) + ")$"
_SEVERITY_PATTERN = "^(" + "|".join(SEVERITIES) + ")$"


class DataQualityRuleCreate(BaseModel):
    name: str = Field(min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    rule_type: str = Field(pattern=_RULE_TYPE_PATTERN)
    severity: str = Field(default="error", pattern=_SEVERITY_PATTERN)
    dataset_id: uuid.UUID | None = None
    config: dict[str, Any] = Field(default_factory=dict)


class DataQualityRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    severity: str | None = Field(default=None, pattern=_SEVERITY_PATTERN)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class DataQualityRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID | None
    name: str
    description: str | None
    rule_type: str
    severity: str
    config_json: dict[str, Any]
    enabled: bool
    last_evaluated_at: datetime | None
    last_status: str | None
    created_at: datetime
    updated_at: datetime


class DataQualityRuleListResponse(BaseModel):
    items: list[DataQualityRuleRead]


class RuleResultRead(BaseModel):
    rule_id: uuid.UUID | None = None
    name: str
    rule_type: str
    severity: str
    status: str
    evaluated_rows: int
    failed_rows: int
    failure_rate: float
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class DataQualityEvaluationRequest(BaseModel):
    """Evaluate the dataset's saved rules, optionally quarantining bad rows."""

    quarantine: bool = Field(
        default=False,
        description="Split rows failing error-severity rules into a new quarantine dataset.",
    )
    rule_ids: list[uuid.UUID] | None = Field(
        default=None, description="Restrict evaluation to these rules; defaults to all enabled rules."
    )


class DataQualityEvaluationResponse(BaseModel):
    evaluation_id: uuid.UUID
    dataset_id: uuid.UUID
    status: str
    rules_evaluated: int
    rules_failed: int
    error_failures: int
    warning_failures: int
    rows_in: int
    rows_passing: int
    rows_quarantined: int
    quarantine_dataset_id: uuid.UUID | None = None
    results: list[RuleResultRead]
    warnings: list[str] = Field(default_factory=list)


class AdHocRuleCheck(BaseModel):
    """Try a rule against a dataset without saving it."""

    rule_type: str = Field(pattern=_RULE_TYPE_PATTERN)
    severity: str = Field(default="error", pattern=_SEVERITY_PATTERN)
    config: dict[str, Any] = Field(default_factory=dict)


class DataQualityResultRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    evaluation_id: uuid.UUID
    rule_id: uuid.UUID | None
    dataset_id: uuid.UUID | None
    rule_name: str
    rule_type: str
    severity: str
    status: str
    evaluated_rows: int
    failed_rows: int
    failure_rate: float
    message: str | None
    details_json: dict[str, Any] | None
    created_at: datetime


class DataQualityResultListResponse(BaseModel):
    items: list[DataQualityResultRead]


class RuleTypeInfo(BaseModel):
    rule_type: str
    description: str
    required_config: list[str]
    optional_config: list[str]
    row_level: bool


class RuleCatalogResponse(BaseModel):
    items: list[RuleTypeInfo]
