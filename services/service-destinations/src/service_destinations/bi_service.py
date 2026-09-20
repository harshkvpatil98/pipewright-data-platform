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
from service_destinations.bi_schemas import (
    BiConnectionMetadataResponse,
    BiIntegrationCreate,
    BiIntegrationListResponse,
    BiIntegrationRead,
    BiIntegrationUpdate,
    BiMetadataItem,
)
from service_destinations.connectors.power_bi import check_power_bi_connection, discover_power_bi_workspaces
from service_destinations.connectors.tableau import check_tableau_connection, discover_tableau_projects
from service_destinations.models import DestinationConfig
from service_destinations.schemas import DestinationTestResult
from service_destinations.validators import (
    BI_INTEGRATION_TYPES,
    merge_config_preserving_secrets,
    redact_config,
    validate_config_for_type,
)


def _to_bi_read(row: DestinationConfig) -> BiIntegrationRead:
    return BiIntegrationRead(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        integration_type=row.destination_type,
        status=row.status,
        config_json=redact_config(dict(row.config_json or {})),
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def get_bi_connection_model(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID
) -> DestinationConfig:
    row = db.scalar(
        select(DestinationConfig).where(
            DestinationConfig.id == connection_id,
            DestinationConfig.project_id == project_id,
            DestinationConfig.destination_type.in_(BI_INTEGRATION_TYPES),
        )
    )
    if row is None:
        raise NotFoundError("BI connection not found.")
    return row


def create_bi_connection(
    db: Session, project_id: uuid.UUID, payload: BiIntegrationCreate, current_user: UserRead
) -> BiIntegrationRead:
    ensure_owned_project(db, project_id, current_user.id)
    itype = payload.integration_type
    validated = validate_config_for_type(itype, payload.config_json)
    row = DestinationConfig(
        id=uuid.uuid4(),
        project_id=project_id,
        name=payload.name.strip(),
        destination_type=itype,
        status=payload.status,
        config_json=persist_destination_config_at_rest(itype, validated),
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_bi_read(row)


def list_bi_connections(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> BiIntegrationListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(DestinationConfig)
        .where(
            DestinationConfig.project_id == project_id,
            DestinationConfig.destination_type.in_(BI_INTEGRATION_TYPES),
        )
        .order_by(DestinationConfig.updated_at.desc())
    ).all()
    return BiIntegrationListResponse(items=[_to_bi_read(r) for r in rows])


def get_bi_connection(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, current_user: UserRead
) -> BiIntegrationRead:
    ensure_owned_project(db, project_id, current_user.id)
    row = get_bi_connection_model(db, project_id, connection_id)
    return _to_bi_read(row)


def delete_bi_connection(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, current_user: UserRead
) -> None:
    """Remove a BI connection.

    Its row is a `DestinationConfig` of a BI type, so the lookup goes through
    `get_bi_connection_model` rather than deleting by id: that keeps a request
    naming an ordinary destination from removing it through the BI endpoint.
    """
    ensure_owned_project(db, project_id, current_user.id)
    row = get_bi_connection_model(db, project_id, connection_id)
    db.delete(row)
    db.commit()


def update_bi_connection(
    db: Session,
    project_id: uuid.UUID,
    connection_id: uuid.UUID,
    payload: BiIntegrationUpdate,
    current_user: UserRead,
) -> BiIntegrationRead:
    ensure_owned_project(db, project_id, current_user.id)
    row = get_bi_connection_model(db, project_id, connection_id)
    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.status is not None:
        row.status = payload.status
    if payload.config_json is not None:
        merged = merge_config_preserving_secrets(
            dict(row.config_json or {}),
            payload.config_json,
            destination_type=row.destination_type,
        )
        normalized = validate_config_for_type(row.destination_type, merged)
        row.config_json = persist_destination_config_at_rest(row.destination_type, normalized)
    db.commit()
    db.refresh(row)
    return _to_bi_read(row)


def _run_bi_test(destination_type: str, config: dict[str, Any]) -> tuple[bool, str, float | None, list[str]]:
    if destination_type == "power_bi":
        return check_power_bi_connection(config)
    if destination_type == "tableau":
        return check_tableau_connection(config)
    raise BadRequestError("Unsupported BI integration type.")


def check_bi_connection(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, current_user: UserRead
) -> DestinationTestResult:
    ensure_owned_project(db, project_id, current_user.id)
    row = get_bi_connection_model(db, project_id, connection_id)
    checked_at = datetime.now(UTC)
    try:
        cfg = destination_config_for_internal_use(row.destination_type, dict(row.config_json or {}))
    except MisconfiguredEnvironmentError as exc:
        return DestinationTestResult(
            success=False,
            checked_at=checked_at,
            message=str(exc.detail),
            latency_ms=None,
            warnings=[],
        )
    try:
        ok, message, latency_ms, warnings = _run_bi_test(row.destination_type, cfg)
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


def discover_bi_metadata(
    db: Session, project_id: uuid.UUID, connection_id: uuid.UUID, current_user: UserRead
) -> BiConnectionMetadataResponse:
    ensure_owned_project(db, project_id, current_user.id)
    row = get_bi_connection_model(db, project_id, connection_id)
    try:
        cfg = destination_config_for_internal_use(row.destination_type, dict(row.config_json or {}))
    except MisconfiguredEnvironmentError as exc:
        raise BadRequestError(str(exc.detail)) from exc
    try:
        if row.destination_type == "power_bi":
            raw = discover_power_bi_workspaces(cfg)
            items = [BiMetadataItem(id=i["id"], name=i["name"]) for i in raw]
            return BiConnectionMetadataResponse(
                integration_type="power_bi",
                metadata_kind="power_bi_workspaces",
                items=items,
            )
        if row.destination_type == "tableau":
            raw = discover_tableau_projects(cfg)
            items = [BiMetadataItem(id=i["id"], name=i["name"]) for i in raw]
            return BiConnectionMetadataResponse(
                integration_type="tableau",
                metadata_kind="tableau_projects",
                items=items,
            )
    except BadRequestError:
        raise
    except Exception:  # noqa: BLE001
        raise BadRequestError("Metadata discovery failed.") from None
    raise BadRequestError("Unsupported BI integration type.")
