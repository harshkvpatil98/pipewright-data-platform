from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_notifications.constants import EXTERNAL_TARGET_EMAIL, EXTERNAL_TARGET_SLACK_WEBHOOK
from service_notifications.at_rest_config import (
    notification_target_config_for_internal_use,
    persist_notification_target_config_at_rest,
)
from service_notifications.models import ExternalNotificationTarget
from service_notifications.redaction import redact_config_for_api
from service_notifications.senders.email_sender import send_email_test_message
from service_notifications.senders.slack_sender import send_slack_test_message
from service_notifications.target_schemas import (
    ExternalNotificationTargetCreate,
    ExternalNotificationTargetListResponse,
    ExternalNotificationTargetRead,
    ExternalNotificationTargetTestResponse,
    ExternalNotificationTargetUpdate,
)
from service_notifications.validators import (
    merge_external_notification_config,
    validate_and_normalize_config,
    validate_subscribed_event_types,
    validate_target_type,
)
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, MisconfiguredEnvironmentError, NotFoundError


def _to_read(row: ExternalNotificationTarget) -> ExternalNotificationTargetRead:
    subscribed = row.subscribed_event_types_json
    if not isinstance(subscribed, list):
        subscribed = []
    evts = [str(x) for x in subscribed]
    cfg = row.config_json if isinstance(row.config_json, dict) else {}
    redacted = redact_config_for_api(target_type=row.target_type, config=cfg)
    return ExternalNotificationTargetRead(
        id=row.id,
        project_id=row.project_id,
        name=row.name,
        target_type=row.target_type,
        enabled=row.enabled,
        config_json=redacted,
        subscribed_event_types=evts,
        created_by_user_id=row.created_by_user_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def list_targets(
    db: Session, *, project_id: uuid.UUID, current_user: UserRead
) -> ExternalNotificationTargetListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    stmt = (
        select(ExternalNotificationTarget)
        .where(ExternalNotificationTarget.project_id == project_id)
        .order_by(ExternalNotificationTarget.created_at.desc())
    )
    rows = db.scalars(stmt).all()
    return ExternalNotificationTargetListResponse(items=[_to_read(r) for r in rows])


def create_target(
    db: Session, *, project_id: uuid.UUID, current_user: UserRead, payload: ExternalNotificationTargetCreate
) -> ExternalNotificationTargetRead:
    ensure_owned_project(db, project_id, current_user.id)
    try:
        ttype = validate_target_type(payload.target_type)
        cfg = validate_and_normalize_config(target_type=ttype, config=payload.config_json)
        evts = validate_subscribed_event_types(payload.subscribed_event_types)
    except ValueError as e:
        raise BadRequestError(str(e)) from e

    row = ExternalNotificationTarget(
        project_id=project_id,
        name=payload.name.strip(),
        target_type=ttype,
        enabled=payload.enabled,
        config_json=persist_notification_target_config_at_rest(ttype, cfg),
        subscribed_event_types_json=evts,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _to_read(row)


def get_target(
    db: Session, *, project_id: uuid.UUID, target_id: uuid.UUID, current_user: UserRead
) -> ExternalNotificationTargetRead:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.get(ExternalNotificationTarget, target_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("Notification target not found.")
    return _to_read(row)


def update_target(
    db: Session,
    *,
    project_id: uuid.UUID,
    target_id: uuid.UUID,
    current_user: UserRead,
    payload: ExternalNotificationTargetUpdate,
) -> ExternalNotificationTargetRead:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.get(ExternalNotificationTarget, target_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("Notification target not found.")

    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.enabled is not None:
        row.enabled = payload.enabled
    if payload.subscribed_event_types is not None:
        try:
            row.subscribed_event_types_json = validate_subscribed_event_types(payload.subscribed_event_types)
        except ValueError as e:
            raise BadRequestError(str(e)) from e
    if payload.config_json is not None:
        try:
            merged = merge_external_notification_config(
                dict(row.config_json or {}),
                payload.config_json,
                target_type=row.target_type,
            )
            normalized = validate_and_normalize_config(target_type=row.target_type, config=merged)
            row.config_json = persist_notification_target_config_at_rest(row.target_type, normalized)
        except ValueError as e:
            raise BadRequestError(str(e)) from e

    db.commit()
    db.refresh(row)
    return _to_read(row)


def send_notification_target_test(
    db: Session, *, project_id: uuid.UUID, target_id: uuid.UUID, current_user: UserRead
) -> ExternalNotificationTargetTestResponse:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.get(ExternalNotificationTarget, target_id)
    if row is None or row.project_id != project_id:
        raise NotFoundError("Notification target not found.")

    raw_cfg: dict[str, Any] = row.config_json if isinstance(row.config_json, dict) else {}
    try:
        cfg = notification_target_config_for_internal_use(row.target_type, raw_cfg)
    except MisconfiguredEnvironmentError as exc:
        return ExternalNotificationTargetTestResponse(success=False, message=str(exc.detail))
    if row.target_type == EXTERNAL_TARGET_EMAIL:
        ok, msg = send_email_test_message(config=cfg)
    elif row.target_type == EXTERNAL_TARGET_SLACK_WEBHOOK:
        ok, msg = send_slack_test_message(config=cfg)
    else:
        raise BadRequestError("Unsupported target type.")

    return ExternalNotificationTargetTestResponse(success=ok, message=msg)
