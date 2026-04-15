from __future__ import annotations

import uuid

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from service_sources.models import Source
from shared_python.errors import NotFoundError


def project_source_count_expression(project_model) -> Select:
    return (
        select(func.count(Source.id))
        .where(Source.project_id == project_model.id)
        .correlate(project_model)
        .scalar_subquery()
    )


def get_source_for_project(db: Session, source_id: uuid.UUID, project_id: uuid.UUID) -> Source:
    source = db.get(Source, source_id)
    if source is None or source.project_id != project_id:
        raise NotFoundError("Source not found for this project.")
    return source


def total_sources(db: Session) -> int:
    return db.scalar(select(func.count(Source.id))) or 0
