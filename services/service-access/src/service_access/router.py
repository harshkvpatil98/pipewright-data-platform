from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_access.schemas import (
    MemberInvite,
    MemberListResponse,
    MemberRead,
    MemberRoleUpdate,
    RoleCatalogResponse,
)
from service_access.service import (
    invite_member,
    list_members,
    remove_member,
    role_catalog,
    update_member_role,
)


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["access"])

    @router.get("/access/roles", response_model=RoleCatalogResponse)
    def read_roles(
        _current_user: UserRead = Depends(get_current_user),
    ) -> RoleCatalogResponse:
        return role_catalog()

    @router.get("/projects/{project_id}/members", response_model=MemberListResponse)
    def read_members(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MemberListResponse:
        return list_members(db, project_id, current_user)

    @router.post(
        "/projects/{project_id}/members",
        response_model=MemberRead,
        status_code=status.HTTP_201_CREATED,
    )
    def add_member(
        project_id: uuid.UUID,
        payload: MemberInvite,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MemberRead:
        return invite_member(db, project_id, payload, current_user)

    @router.patch(
        "/projects/{project_id}/members/{membership_id}", response_model=MemberRead
    )
    def change_role(
        project_id: uuid.UUID,
        membership_id: uuid.UUID,
        payload: MemberRoleUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> MemberRead:
        return update_member_role(db, project_id, membership_id, payload, current_user)

    @router.delete(
        "/projects/{project_id}/members/{membership_id}",
        status_code=status.HTTP_204_NO_CONTENT,
    )
    def revoke(
        project_id: uuid.UUID,
        membership_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> Response:
        remove_member(db, project_id, membership_id, current_user)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    return router
