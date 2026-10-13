from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_notifications import preferences
from service_notifications.schemas import (
    MarkAllNotificationsReadResponse,
    MarkNotificationReadResponse,
    NotificationPreferenceRead,
    NotificationPreferencesResponse,
    NotificationPreferenceUpdate,
    UserNotificationListResponse,
)
from service_notifications.service import (
    list_notifications_for_user,
    mark_all_notifications_read,
    mark_notification_read,
)
from service_notifications.target_schemas import (
    ExternalNotificationTargetCreate,
    ExternalNotificationTargetListResponse,
    ExternalNotificationTargetRead,
    ExternalNotificationTargetTestResponse,
    ExternalNotificationTargetUpdate,
)
from service_notifications.targets_service import (
    create_target,
    delete_target,
    get_target,
    list_targets,
    send_notification_target_test,
    update_target,
)


def build_router(get_db: Callable[..., Session], get_current_user: Callable[..., UserRead]) -> APIRouter:
    router = APIRouter(tags=["notifications"])

    @router.get("/notifications", response_model=UserNotificationListResponse)
    def get_my_notifications(
        limit: int = Query(default=100, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> UserNotificationListResponse:
        return list_notifications_for_user(db, current_user=current_user, project_id=None, limit=limit)

    @router.get("/projects/{project_id}/notifications", response_model=UserNotificationListResponse)
    def get_project_notifications(
        project_id: uuid.UUID,
        limit: int = Query(default=100, ge=1, le=200),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> UserNotificationListResponse:
        return list_notifications_for_user(db, current_user=current_user, project_id=project_id, limit=limit)

    def _preferences_for(db: Session, user_id: uuid.UUID) -> NotificationPreferencesResponse:
        modes = preferences.all_modes(db, user_id)
        return NotificationPreferencesResponse(
            items=[
                NotificationPreferenceRead(
                    category=category.key,
                    label=category.label,
                    description=category.description,
                    mode=modes[category.key],
                    default=category.default,
                )
                for category in preferences.CATEGORIES
            ],
            modes=list(preferences.MODES),
        )

    @router.get("/notifications/preferences", response_model=NotificationPreferencesResponse)
    def get_notification_preferences(
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> NotificationPreferencesResponse:
        return _preferences_for(db, current_user.id)

    @router.put("/notifications/preferences", response_model=NotificationPreferencesResponse)
    def put_notification_preference(
        payload: NotificationPreferenceUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> NotificationPreferencesResponse:
        """Change how one kind of notification arrives, for the signed-in person only."""
        preferences.set_mode(db, current_user.id, payload.category, payload.mode)
        return _preferences_for(db, current_user.id)

    @router.patch("/notifications/read-all", response_model=MarkAllNotificationsReadResponse)
    def patch_notifications_read_all(
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MarkAllNotificationsReadResponse:
        return mark_all_notifications_read(db, current_user=current_user)

    @router.patch("/notifications/{notification_id}/read", response_model=MarkNotificationReadResponse)
    def patch_notification_read(
        notification_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MarkNotificationReadResponse:
        return mark_notification_read(db, notification_id=notification_id, current_user=current_user)

    @router.get(
        "/projects/{project_id}/notification-targets",
        response_model=ExternalNotificationTargetListResponse,
    )
    def get_notification_targets(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExternalNotificationTargetListResponse:
        return list_targets(db, project_id=project_id, current_user=current_user)

    @router.post(
        "/projects/{project_id}/notification-targets",
        response_model=ExternalNotificationTargetRead,
    )
    def post_notification_target(
        project_id: uuid.UUID,
        payload: ExternalNotificationTargetCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExternalNotificationTargetRead:
        return create_target(db, project_id=project_id, current_user=current_user, payload=payload)

    @router.get(
        "/projects/{project_id}/notification-targets/{target_id}",
        response_model=ExternalNotificationTargetRead,
    )
    def get_notification_target(
        project_id: uuid.UUID,
        target_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExternalNotificationTargetRead:
        return get_target(db, project_id=project_id, target_id=target_id, current_user=current_user)

    @router.patch(
        "/projects/{project_id}/notification-targets/{target_id}",
        response_model=ExternalNotificationTargetRead,
    )
    def patch_notification_target(
        project_id: uuid.UUID,
        target_id: uuid.UUID,
        payload: ExternalNotificationTargetUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExternalNotificationTargetRead:
        return update_target(
            db, project_id=project_id, target_id=target_id, current_user=current_user, payload=payload
        )

    @router.delete(
        "/projects/{project_id}/notification-targets/{target_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def remove_notification_target(
        project_id: uuid.UUID,
        target_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        delete_target(
            db, project_id=project_id, target_id=target_id, current_user=current_user
        )

    @router.post(
        "/projects/{project_id}/notification-targets/{target_id}/test",
        response_model=ExternalNotificationTargetTestResponse,
    )
    def post_notification_target_test(
        project_id: uuid.UUID,
        target_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExternalNotificationTargetTestResponse:
        return send_notification_target_test(
            db, project_id=project_id, target_id=target_id, current_user=current_user
        )

    return router
