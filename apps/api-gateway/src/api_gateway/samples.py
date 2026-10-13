"""Sample datasets a project can start from.

A person trying the product for the first time often has no file to hand, or
does not want to put real data into something they are still evaluating. These
three small files (orders, customers and invoices for one made-up shop) are
enough to build a recipe, a check and a chart, and they are deliberately a
little untidy -- stray spaces, mixed-case emails, a duplicate row, a missing
amount, a refund -- so the cleaning tools and the checks have something real to
find. They share customer ids, so joins work across them.

Adding one goes through the same ingestion a user's own upload takes, so the
result is an ordinary dataset with a run, a profile and a version. The gateway
holds them because it is the one layer that already composes every service.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from importlib import resources

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_ingestion.schemas import DatasetUploadResponse, IngestionUpload
from service_ingestion.service import ingest_project_file
from shared_python.errors import NotFoundError


@dataclass(frozen=True)
class Sample:
    id: str
    name: str
    description: str
    file_name: str


SAMPLES: tuple[Sample, ...] = (
    Sample(
        id="orders",
        name="Sample orders",
        description="Orders from July to September: products, quantities, amounts and regions.",
        file_name="orders.csv",
    ),
    Sample(
        id="customers",
        name="Sample customers",
        description="Customers with names, emails, phone numbers and cities. Some need tidying.",
        file_name="customers.csv",
    ),
    Sample(
        id="invoices",
        name="Sample invoices",
        description="Invoices with amounts, due dates and whether they were paid.",
        file_name="invoices.csv",
    ),
)

_BY_ID = {sample.id: sample for sample in SAMPLES}


def sample_bytes(sample: Sample) -> bytes:
    return resources.files("api_gateway").joinpath("sample_data", sample.file_name).read_bytes()


class SampleRead(BaseModel):
    id: str
    name: str
    description: str
    file_name: str
    columns: list[str]
    row_count: int


class SampleListResponse(BaseModel):
    items: list[SampleRead]


def describe(sample: Sample) -> SampleRead:
    lines = sample_bytes(sample).decode("utf-8").strip().splitlines()
    return SampleRead(
        id=sample.id,
        name=sample.name,
        description=sample.description,
        file_name=sample.file_name,
        columns=lines[0].split(","),
        row_count=len(lines) - 1,
    )


def add_sample_to_project(
    db: Session,
    *,
    project_id: uuid.UUID,
    sample_id: str,
    current_user: UserRead,
    storage_backend,
    settings,
) -> DatasetUploadResponse:
    sample = _BY_ID.get(sample_id)
    if sample is None:
        raise NotFoundError(f"There is no sample called '{sample_id}'.")
    # Ownership and membership are checked inside ingestion, the same as for
    # an upload, so a sample can only land in a project the user may edit.
    return ingest_project_file(
        db,
        project_id=project_id,
        dataset_name=sample.name,
        upload_file=IngestionUpload(
            file_name=sample.file_name, content_type="text/csv", file_bytes=sample_bytes(sample)
        ),
        storage_backend=storage_backend,
        settings=settings,
        current_user=current_user,
    )


def build_samples_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., object],
    settings,
) -> APIRouter:
    router = APIRouter(tags=["samples"])

    @router.get("/samples", response_model=SampleListResponse)
    def list_samples(
        current_user: UserRead = Depends(get_current_user),
    ) -> SampleListResponse:
        return SampleListResponse(items=[describe(sample) for sample in SAMPLES])

    @router.post(
        "/projects/{project_id}/samples/{sample_id}",
        response_model=DatasetUploadResponse,
        status_code=201,
    )
    def add_sample(
        project_id: uuid.UUID,
        sample_id: str,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend=Depends(get_storage_backend),
    ) -> DatasetUploadResponse:
        return add_sample_to_project(
            db,
            project_id=project_id,
            sample_id=sample_id,
            current_user=current_user,
            storage_backend=storage_backend,
            settings=settings,
        )

    return router
