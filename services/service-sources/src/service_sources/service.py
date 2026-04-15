from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from service_sources.models import Source
from service_sources.schemas import SourceCreate, SourceListResponse, SourceRead


def list_sources_by_project(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> SourceListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    sources = db.scalars(
        select(Source).where(Source.project_id == project_id).order_by(Source.created_at.desc())
    ).all()
    return SourceListResponse(items=[SourceRead.model_validate(source) for source in sources])


def create_source(
    db: Session, project_id: uuid.UUID, payload: SourceCreate, current_user: UserRead
) -> SourceRead:
    ensure_owned_project(db, project_id, current_user.id)
    source = Source(
        project_id=project_id,
        name=payload.name.strip(),
        source_type=payload.source_type,
        description=payload.description.strip() if payload.description else None,
        status=payload.status,
        config_json=payload.config_json,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return SourceRead.model_validate(source)
