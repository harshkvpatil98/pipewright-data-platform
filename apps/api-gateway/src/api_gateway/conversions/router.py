"""The routes of converting work from another tool (E2, X3).

``…/conversions/preview`` reads the file and says what it would make and
what it reads, part by part, changing nothing (a viewer may). ``…/conversions``
makes it (an editor may). Both take the same upload, and the mapping of what
it reads to the project's datasets, so what the preview says is what the
import does.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Callable

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from shared_python.errors import BadRequestError

from api_gateway.conversions import formats, read_upload
from api_gateway.conversions.apply import Resolver, apply, payload
from api_gateway.conversions.model import NotConverted


class ConversionFormat(BaseModel):
    key: str
    title: str
    upload: str
    extensions: list[str]


class ConversionEntry(BaseModel):
    subject: str
    status: str
    became: list[str]
    reason: str | None = None
    notes: list[str]


class ConversionSection(BaseModel):
    title: str
    entries: list[ConversionEntry]


class ConversionNeed(BaseModel):
    key: str
    name: str
    what: str
    columns: list[str]
    status: str
    dataset_id: str | None = None
    dataset_name: str | None = None
    reason: str | None = None


class ConversionItem(BaseModel):
    key: str
    name: str


class ConversionRecipe(ConversionItem):
    steps: int
    complete: bool
    reads: str
    parameters: list[str]


class ConversionCheck(ConversionItem):
    rule_type: str
    reads: str


class ConversionWorkflow(ConversionItem):
    tasks: int
    trigger_type: str
    cron_expression: str | None = None


class ConversionSeed(ConversionItem):
    what: str
    file_name: str


class ConversionCounts(BaseModel):
    converted: int
    not_converted: int
    nothing_to_do: int


class ConversionChoice(BaseModel):
    id: str
    name: str


class ConversionPreview(BaseModel):
    format: str
    title: str
    needs: list[ConversionNeed]
    seeds: list[ConversionSeed]
    recipes: list[ConversionRecipe]
    checks: list[ConversionCheck]
    workflows: list[ConversionWorkflow]
    sections: list[ConversionSection]
    counts: ConversionCounts
    notes: list[str]
    choices: list[ConversionChoice]


class ConversionMade(BaseModel):
    kind: str
    key: str
    name: str
    status: str
    id: str | None = None
    detail: str | None = None


class ConversionResult(ConversionPreview):
    made: list[ConversionMade]


def _mapping(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise BadRequestError("The datasets chosen are not JSON this can read.") from exc
    if not isinstance(mapping, dict) or not all(isinstance(v, str) for v in mapping.values()):
        raise BadRequestError("The datasets chosen are given as {\"what it reads\": \"dataset id\"}.")
    return {str(key): value for key, value in mapping.items()}


def build_conversions_router(get_db: Callable[..., Session], get_current_user: Callable[..., UserRead],
                             get_storage_backend: Callable[..., Any], settings) -> APIRouter:
    router = APIRouter(tags=["conversions"])

    def converted(project_id: uuid.UUID, file: UploadFile, format_key: str | None, mapping: str | None,
                  db: Session, user: UserRead):
        from service_projects.contracts import ensure_owned_project

        ensure_owned_project(db, project_id, user.id)
        data = file.file.read(settings.max_upload_size_bytes + 1)
        if len(data) > settings.max_upload_size_bytes:
            raise BadRequestError(f"The file is larger than {settings.max_upload_size_bytes // (1024 * 1024)} MB, "
                                  "the most this deployment takes.")
        resolver = Resolver(db, project_id, user, _mapping(mapping))
        try:
            chosen, files = read_upload(file.filename or "upload", data, format_key or None)
            conversion = chosen.convert(files, resolver)
        except NotConverted as exc:
            raise BadRequestError(exc.reason) from exc
        return conversion, resolver

    @router.get("/conversions/formats", response_model=list[ConversionFormat])
    def list_conversion_formats(current_user: UserRead = Depends(get_current_user)) -> list[dict[str, Any]]:
        """The formats work can be converted from, and what to upload for each."""
        return [{"key": item.key, "title": item.title, "upload": item.upload, "extensions": list(item.extensions)}
                for item in formats().values()]

    @router.post("/projects/{project_id}/conversions/preview", response_model=ConversionPreview)
    def preview_conversion(project_id: uuid.UUID, file: UploadFile = File(...), format: str | None = Form(None),
                           mapping: str | None = Form(None), db: Session = Depends(get_db),
                           current_user: UserRead = Depends(get_current_user)) -> dict[str, Any]:
        """What converting the file would make and read, part by part. Changes nothing."""
        conversion, resolver = converted(project_id, file, format, mapping, db, current_user)
        return payload(conversion, resolver)

    @router.post("/projects/{project_id}/conversions", response_model=ConversionResult)
    def make_conversion(project_id: uuid.UUID, file: UploadFile = File(...), format: str | None = Form(None),
                        mapping: str | None = Form(None), db: Session = Depends(get_db),
                        current_user: UserRead = Depends(get_current_user),
                        storage_backend=Depends(get_storage_backend)) -> dict[str, Any]:
        """Make what the preview showed: datasets from its data, recipes (run), checks (run) and workflows."""
        conversion, resolver = converted(project_id, file, format, mapping, db, current_user)
        made = apply(db, project_id, conversion, resolver, storage_backend=storage_backend, settings=settings)
        return {**payload(conversion, resolver), "made": [item.as_dict() for item in made]}

    return router
