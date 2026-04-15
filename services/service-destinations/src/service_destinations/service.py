from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, MisconfiguredEnvironmentError, NotFoundError

from service_destinations.at_rest_config import destination_config_for_internal_use, persist_destination_config_at_rest
from service_destinations.connectors.local_export import check_local_export_connection
from service_destinations.connectors.postgres import check_postgres_connection
from service_destinations.connectors.s3 import check_s3_connection
from service_destinations.models import DestinationConfig
from service_destinations.schemas import (
    DestinationCreate,
    DestinationListResponse,
    DestinationRead,
    DestinationTestResult,
    DestinationUpdate,
)
from service_destinations.validators import (
    BI_INTEGRATION_TYPES,
    DESTINATION_TYPES,
    merge_config_preserving_secrets,
    redact_config,
    validate_config_for_type,
)


def _to_read(dest: DestinationConfig) -> DestinationRead:
    data = DestinationRead.model_validate(dest)
    return data.model_copy(update={"config_json": redact_config(dict(dest.config_json or {}))})


def get_destination_model(
    db: Session, project_id: uuid.UUID, destination_id: uuid.UUID
) -> DestinationConfig:
    row = db.scalar(
        select(DestinationConfig).where(
            DestinationConfig.id == destination_id,
            DestinationConfig.project_id == project_id,
        )
    )
    if row is None:
        raise NotFoundError("Destination not found.")
    return row


def _ensure_delivery_destination(row: DestinationConfig) -> None:
    if row.destination_type in BI_INTEGRATION_TYPES:
        raise NotFoundError("Destination not found.")


def create_destination(
    db: Session, project_id: uuid.UUID, payload: DestinationCreate, current_user: UserRead
) -> DestinationRead:
    ensure_owned_project(db, project_id, current_user.id)
    if payload.destination_type not in DESTINATION_TYPES:
        raise BadRequestError("Unsupported destination type.")
    validated = validate_config_for_type(payload.destination_type, payload.config_json)
    dest = DestinationConfig(
        id=uuid.uuid4(),
        project_id=project_id,
        name=payload.name.strip(),
        destination_type=payload.destination_type,
        status=payload.status,
        config_json=persist_destination_config_at_rest(payload.destination_type, validated),
        created_by_user_id=current_user.id,
    )
    db.add(dest)
    db.commit()
    db.refresh(dest)
    return _to_read(dest)


def list_destinations(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> DestinationListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(DestinationConfig)
        .where(
            DestinationConfig.project_id == project_id,
            DestinationConfig.destination_type.not_in(BI_INTEGRATION_TYPES),
        )
        .order_by(DestinationConfig.updated_at.desc())
    ).all()
    return DestinationListResponse(items=[_to_read(r) for r in rows])


def get_destination(
    db: Session, project_id: uuid.UUID, destination_id: uuid.UUID, current_user: UserRead
) -> DestinationRead:
    ensure_owned_project(db, project_id, current_user.id)
    dest = get_destination_model(db, project_id, destination_id)
    _ensure_delivery_destination(dest)
    return _to_read(dest)


def update_destination(
    db: Session,
    project_id: uuid.UUID,
    destination_id: uuid.UUID,
    payload: DestinationUpdate,
    current_user: UserRead,
) -> DestinationRead:
    ensure_owned_project(db, project_id, current_user.id)
    dest = get_destination_model(db, project_id, destination_id)
    _ensure_delivery_destination(dest)
    if payload.name is not None:
        dest.name = payload.name.strip()
    if payload.status is not None:
        dest.status = payload.status
    if payload.config_json is not None:
        merged = merge_config_preserving_secrets(
            dict(dest.config_json or {}),
            payload.config_json,
            destination_type=dest.destination_type,
        )
        normalized = validate_config_for_type(dest.destination_type, merged)
        dest.config_json = persist_destination_config_at_rest(dest.destination_type, normalized)
    db.commit()
    db.refresh(dest)
    return _to_read(dest)


def _run_connection_test(destination_type: str, config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    if destination_type == "postgres":
        return check_postgres_connection(config)
    if destination_type == "s3":
        return check_s3_connection(config)
    if destination_type == "local_export":
        return check_local_export_connection(config)
    raise BadRequestError("Unsupported destination type for connection test.")


def test_destination_connection(
    db: Session, project_id: uuid.UUID, destination_id: uuid.UUID, current_user: UserRead
) -> DestinationTestResult:
    ensure_owned_project(db, project_id, current_user.id)
    dest = get_destination_model(db, project_id, destination_id)
    _ensure_delivery_destination(dest)
    checked_at = datetime.now(UTC)
    try:
        cfg = destination_config_for_internal_use(dest.destination_type, dict(dest.config_json or {}))
    except MisconfiguredEnvironmentError as exc:
        return DestinationTestResult(
            success=False,
            checked_at=checked_at,
            message=str(exc.detail),
            latency_ms=None,
            warnings=[],
        )
    try:
        ok, message, latency_ms, warnings = _run_connection_test(dest.destination_type, cfg)
    except BadRequestError:
        raise
    except Exception:  # noqa: BLE001
        return DestinationTestResult(
            success=False,
            checked_at=checked_at,
            message="Connection test failed.",
            latency_ms=None,
            warnings=[],
        )
    return DestinationTestResult(
        success=ok,
        checked_at=checked_at,
        message=message,
        latency_ms=latency_ms,
        warnings=warnings,
    )
