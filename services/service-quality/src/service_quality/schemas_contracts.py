"""What the API says about data contracts (Phase 19, C1)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ColumnKind = Literal["text", "whole_number", "decimal_number", "date", "date_time", "true_false", "any"]

MAX_PROMISED_COLUMNS = 500
MAX_ALLOWED_VALUES = 200


class ContractColumn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    kind: ColumnKind = "any"
    always_filled: bool = False
    no_repeats: bool = False
    allowed_values: list[str] | None = Field(default=None, max_length=MAX_ALLOWED_VALUES)
    lowest: float | None = None
    highest: float | None = None


class ContractTerms(BaseModel):
    columns: list[ContractColumn] = Field(default_factory=list, max_length=MAX_PROMISED_COLUMNS)
    #: `allowed`: new columns may appear. `not_allowed`: only the promised ones.
    other_columns: Literal["allowed", "not_allowed"] = "allowed"
    rows_at_least: int | None = Field(default=None, ge=0)
    rows_at_most: int | None = Field(default=None, ge=0)
    #: The most the row count may fall since the current data, as a percentage.
    largest_drop_percent: float | None = Field(default=None, ge=0, le=100)
    #: Kept as the dataset's freshness promise, which the worker checks.
    new_data_every_hours: float | None = Field(default=None, gt=0, le=8784)


class DataContractWrite(BaseModel):
    description: str | None = Field(default=None, max_length=2000)
    owner_user_id: uuid.UUID | None = None
    enforcement: Literal["stop", "warn"] = "stop"
    terms: ContractTerms


class ContractProblemRead(BaseModel):
    id: uuid.UUID
    kind: str
    outcome: str
    source_type: str | None
    source_id: uuid.UUID | None
    source_name: str | None
    reasons: list[str]
    times_seen: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None
    pipeline_run_id: uuid.UUID | None
    contract_version: int


class ContractVersionRead(BaseModel):
    version: int
    description: str | None
    enforcement: str
    owner_username: str | None
    terms: ContractTerms
    changes: list[str]
    created_by_username: str | None
    created_at: datetime


class ContractConsumer(BaseModel):
    #: recipe, check, chart, dashboard, metric, delivery or workflow.
    kind: str
    id: uuid.UUID
    name: str


class DataContractRead(BaseModel):
    id: uuid.UUID
    project_id: uuid.UUID
    dataset_id: uuid.UUID
    dataset_name: str
    owner_user_id: uuid.UUID | None
    owner_username: str | None
    description: str | None
    enforcement: str
    terms: ContractTerms
    version: int
    #: kept, broken, or not_checked.
    status: str
    open_problems: int
    followers: int
    following: bool
    last_checked_at: datetime | None
    created_at: datetime
    updated_at: datetime


class DataContractDetail(DataContractRead):
    problems: list[ContractProblemRead]
    consumers: list[ContractConsumer]


class ContractPerson(BaseModel):
    id: uuid.UUID
    username: str


class DatasetContractResponse(BaseModel):
    """A dataset's contract, or none, with promises drafted from its data."""

    contract: DataContractDetail | None
    draft: ContractTerms
    #: Who may own it: the project's people.
    people: list[ContractPerson] = Field(default_factory=list)
    #: The caller's role in the project, so the page offers only what it may do.
    your_role: str | None = None


class ContractCheckResponse(BaseModel):
    kept: bool
    reasons: list[str]
    rows_checked: int
    #: The version checked; None for the current data.
    version_number: int | None = None


class ContractSaveResponse(DatasetContractResponse):
    #: Whether the current data keeps the saved contract.
    current: ContractCheckResponse | None


class DataContractListResponse(BaseModel):
    items: list[DataContractRead]


class ContractHistoryResponse(BaseModel):
    items: list[ContractVersionRead]
