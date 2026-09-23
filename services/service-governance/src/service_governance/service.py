"""Governance over real rows: versions, approvals, the audit log, comments."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_projects.contracts import ensure_owned_project
from shared_python.errors import BadRequestError, NotFoundError

from service_governance import versions as version_ops
from service_governance.diff import diff_snapshots
from service_governance.models import AuditEntry, ChangeRequest, Comment
from service_governance.schemas import (
    AuditEntryRead,
    AuditListResponse,
    ChangeRead,
    ChangeRequestCreate,
    ChangeRequestDetail,
    ChangeRequestListResponse,
    ChangeRequestRead,
    ChangeRequestReview,
    CommentCreate,
    CommentListResponse,
    PromoteRequest,
    PromoteResponse,
    CommentRead,
    RestoreRequest,
    RestoreResponse,
    SnapshotDiffRead,
    UnresolvedReferenceRead,
    VersionDetail,
    VersionDiffResponse,
    VersionListResponse,
    VersionRead,
)

MENTION_PATTERN = re.compile(r"@([A-Za-z0-9][A-Za-z0-9._-]{0,79})")
MAX_AUDIT_ROWS = 200


def _usernames(db: Session, user_ids: list[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    unique = [user_id for user_id in dict.fromkeys(user_ids) if user_id is not None]
    if not unique:
        return {}
    rows = db.execute(select(User.id, User.username).where(User.id.in_(unique))).all()
    return {row[0]: row[1] for row in rows}


def _diff_read(before: Any, after: Any) -> SnapshotDiffRead:
    payload = diff_snapshots(before, after).to_dict()
    return SnapshotDiffRead(
        changes=[ChangeRead(**change) for change in payload["changes"]],
        truncated=payload["truncated"],
        identical=payload["identical"],
        summary=payload["summary"],
    )


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------


def _version_read(row, names: dict[uuid.UUID, str]) -> VersionRead:
    return VersionRead(
        id=row.id,
        resource_type=row.resource_type,
        resource_id=row.resource_id,
        version=row.version,
        name=row.name,
        change_summary=row.change_summary,
        created_by_user_id=row.created_by_user_id,
        created_by_username=names.get(row.created_by_user_id) if row.created_by_user_id else None,
        restored_from_version=row.restored_from_version,
        created_at=row.created_at,
    )


def list_resource_versions(
    db: Session,
    project_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    current_user: UserRead,
) -> VersionListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = version_ops.list_versions(db, project_id, resource_type, resource_id)
    names = _usernames(db, [row.created_by_user_id for row in rows])
    return VersionListResponse(
        items=[_version_read(row, names) for row in rows],
        resource_type=resource_type,  # type: ignore[arg-type]
        resource_id=resource_id,
    )


def get_resource_version(
    db: Session,
    project_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    version: int,
    current_user: UserRead,
) -> VersionDetail:
    ensure_owned_project(db, project_id, current_user.id)
    row = version_ops.get_version(db, project_id, resource_type, resource_id, version)
    names = _usernames(db, [row.created_by_user_id])
    return VersionDetail(
        **_version_read(row, names).model_dump(), snapshot_json=row.snapshot_json
    )


def diff_resource_versions(
    db: Session,
    project_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    left: int,
    right: int,
    current_user: UserRead,
) -> VersionDiffResponse:
    ensure_owned_project(db, project_id, current_user.id)
    if left == right:
        raise BadRequestError("Pick two different versions to compare.")

    before = version_ops.get_version(db, project_id, resource_type, resource_id, left)
    after = version_ops.get_version(db, project_id, resource_type, resource_id, right)
    return VersionDiffResponse(
        left_version=left,
        right_version=right,
        diff=_diff_read(before.snapshot_json, after.snapshot_json),
    )


def restore_resource_version(
    db: Session,
    project_id: uuid.UUID,
    resource_type: str,
    resource_id: uuid.UUID,
    payload: RestoreRequest,
    current_user: UserRead,
) -> RestoreResponse:
    ensure_owned_project(db, project_id, current_user.id)
    new_version, summary = version_ops.restore_version(
        db,
        project_id=project_id,
        resource_type=resource_type,
        resource_id=resource_id,
        version=payload.version,
        actor_user_id=current_user.id,
    )
    return RestoreResponse(
        resource_type=resource_type,  # type: ignore[arg-type]
        resource_id=resource_id,
        restored_from_version=payload.version,
        new_version=new_version,
        summary=summary,
    )


# --------------------------------------------------------------------------
# Change requests
# --------------------------------------------------------------------------


def _change_read(row: ChangeRequest, names: dict[uuid.UUID, str]) -> ChangeRequestRead:
    return ChangeRequestRead(
        id=row.id,
        project_id=row.project_id,
        resource_type=row.resource_type,  # type: ignore[arg-type]
        resource_id=row.resource_id,
        title=row.title,
        description=row.description,
        status=row.status,  # type: ignore[arg-type]
        change_summary=row.change_summary,
        requested_by_user_id=row.requested_by_user_id,
        requested_by_username=(
            names.get(row.requested_by_user_id) if row.requested_by_user_id else None
        ),
        reviewed_by_user_id=row.reviewed_by_user_id,
        reviewed_by_username=(
            names.get(row.reviewed_by_user_id) if row.reviewed_by_user_id else None
        ),
        reviewed_at=row.reviewed_at,
        review_note=row.review_note,
        created_at=row.created_at,
    )


def propose_change(
    db: Session, project_id: uuid.UUID, payload: ChangeRequestCreate, current_user: UserRead
) -> ChangeRequestDetail:
    ensure_owned_project(db, project_id, current_user.id)

    before = version_ops.current_snapshot(
        db, payload.resource_type, project_id, payload.resource_id
    )
    difference = diff_snapshots(before, payload.after_json)
    if difference.identical:
        raise BadRequestError("This proposal does not change anything.")

    request = ChangeRequest(
        project_id=project_id,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        title=payload.title.strip(),
        description=payload.description,
        before_json=before,
        after_json=payload.after_json,
        change_summary=difference.summary(),
        status="open",
        requested_by_user_id=current_user.id,
    )
    db.add(request)
    db.commit()
    db.refresh(request)
    return _change_detail(db, request)


def _change_detail(db: Session, row: ChangeRequest) -> ChangeRequestDetail:
    names = _usernames(db, [row.requested_by_user_id, row.reviewed_by_user_id])
    return ChangeRequestDetail(
        **_change_read(row, names).model_dump(),
        before_json=row.before_json,
        after_json=row.after_json,
        diff=_diff_read(row.before_json, row.after_json),
    )


def _get_change(db: Session, project_id: uuid.UUID, change_id: uuid.UUID) -> ChangeRequest:
    row = db.scalar(
        select(ChangeRequest).where(
            ChangeRequest.id == change_id, ChangeRequest.project_id == project_id
        )
    )
    if row is None:
        raise NotFoundError("Change request not found.")
    return row


def list_change_requests(
    db: Session, project_id: uuid.UUID, current_user: UserRead, *, status: str | None = None
) -> ChangeRequestListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    statement = select(ChangeRequest).where(ChangeRequest.project_id == project_id)
    if status:
        statement = statement.where(ChangeRequest.status == status)
    rows = list(db.scalars(statement.order_by(ChangeRequest.created_at.desc()).limit(200)).all())

    names = _usernames(
        db, [row.requested_by_user_id for row in rows] + [row.reviewed_by_user_id for row in rows]
    )
    open_count = (
        db.scalar(
            select(func.count(ChangeRequest.id)).where(
                ChangeRequest.project_id == project_id, ChangeRequest.status == "open"
            )
        )
        or 0
    )
    return ChangeRequestListResponse(
        items=[_change_read(row, names) for row in rows], open_count=int(open_count)
    )


def get_change_request(
    db: Session, project_id: uuid.UUID, change_id: uuid.UUID, current_user: UserRead
) -> ChangeRequestDetail:
    ensure_owned_project(db, project_id, current_user.id)
    return _change_detail(db, _get_change(db, project_id, change_id))


def approve_change(
    db: Session,
    project_id: uuid.UUID,
    change_id: uuid.UUID,
    payload: ChangeRequestReview,
    current_user: UserRead,
) -> ChangeRequestDetail:
    """Apply a proposed change, and record it as a version."""
    ensure_owned_project(db, project_id, current_user.id)
    request = _get_change(db, project_id, change_id)
    if request.status != "open":
        raise BadRequestError(f"This change was already {request.status}.")
    if request.requested_by_user_id == current_user.id:
        # The whole point of review is a second pair of eyes.
        raise BadRequestError("You cannot approve your own change.")

    restorer = version_ops._restorers.get(request.resource_type)
    if restorer is None:
        raise BadRequestError(
            f"'{request.resource_type}' changes cannot be applied automatically."
        )

    restorer(db, project_id, request.resource_id, dict(request.after_json), current_user.id)
    version_ops.record_version(
        db,
        project_id=project_id,
        resource_type=request.resource_type,
        resource_id=request.resource_id,
        name=request.title,
        snapshot=dict(request.after_json),
        actor_user_id=request.requested_by_user_id,
    )

    request.status = "approved"
    request.reviewed_by_user_id = current_user.id
    request.reviewed_at = datetime.now(UTC)
    request.review_note = payload.note
    db.commit()
    db.refresh(request)
    return _change_detail(db, request)


def reject_change(
    db: Session,
    project_id: uuid.UUID,
    change_id: uuid.UUID,
    payload: ChangeRequestReview,
    current_user: UserRead,
) -> ChangeRequestDetail:
    ensure_owned_project(db, project_id, current_user.id)
    request = _get_change(db, project_id, change_id)
    if request.status != "open":
        raise BadRequestError(f"This change was already {request.status}.")

    request.status = "rejected"
    request.reviewed_by_user_id = current_user.id
    request.reviewed_at = datetime.now(UTC)
    request.review_note = payload.note
    db.commit()
    db.refresh(request)
    return _change_detail(db, request)


def withdraw_change(
    db: Session, project_id: uuid.UUID, change_id: uuid.UUID, current_user: UserRead
) -> ChangeRequestDetail:
    ensure_owned_project(db, project_id, current_user.id)
    request = _get_change(db, project_id, change_id)
    if request.status != "open":
        raise BadRequestError(f"This change was already {request.status}.")
    if request.requested_by_user_id != current_user.id:
        raise BadRequestError("Only the person who proposed a change can withdraw it.")

    request.status = "withdrawn"
    request.reviewed_at = datetime.now(UTC)
    db.commit()
    db.refresh(request)
    return _change_detail(db, request)


def promote(
    db: Session, project_id: uuid.UUID, payload: "PromoteRequest", current_user: UserRead
) -> "PromoteResponse":
    """Copy a resource into another project, usually the next environment along."""
    from service_governance.promotion import promote_resource

    ensure_owned_project(db, project_id, current_user.id)
    # The caller must be able to write to the target as well as read the source;
    # promoting into a project you cannot see would be a way around access control.
    ensure_owned_project(db, payload.target_project_id, current_user.id)

    new_id, unresolved, summary = promote_resource(
        db,
        source_project_id=project_id,
        target_project_id=payload.target_project_id,
        resource_type=payload.resource_type,
        resource_id=payload.resource_id,
        actor_user_id=current_user.id,
    )
    return PromoteResponse(
        source_project_id=project_id,
        target_project_id=payload.target_project_id,
        resource_type=payload.resource_type,
        new_resource_id=new_id,
        unresolved=[UnresolvedReferenceRead(**item.to_dict()) for item in unresolved],
        summary=summary,
    )


# --------------------------------------------------------------------------
# Audit log
# --------------------------------------------------------------------------


def list_audit_entries(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead,
    *,
    outcome: str | None = None,
    limit: int = 100,
) -> AuditListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    statement = select(AuditEntry).where(AuditEntry.project_id == project_id)
    if outcome:
        statement = statement.where(AuditEntry.outcome == outcome)
    rows = db.scalars(
        statement.order_by(AuditEntry.created_at.desc()).limit(max(1, min(limit, MAX_AUDIT_ROWS)))
    ).all()
    return AuditListResponse(
        items=[AuditEntryRead.model_validate(row, from_attributes=True) for row in rows]
    )


def total_audit_entries(db: Session) -> int:
    return db.scalar(select(func.count(AuditEntry.id))) or 0


# --------------------------------------------------------------------------
# Comments
# --------------------------------------------------------------------------


def extract_mentions(body: str) -> list[str]:
    """Usernames mentioned with @, deduplicated and in the order written."""
    return list(dict.fromkeys(match.lower() for match in MENTION_PATTERN.findall(body)))


def _comment_read(row: Comment, names: dict[uuid.UUID, str]) -> CommentRead:
    return CommentRead(
        id=row.id,
        project_id=row.project_id,
        target_type=row.target_type,  # type: ignore[arg-type]
        target_id=row.target_id,
        body=row.body,
        author_user_id=row.author_user_id,
        author_username=names.get(row.author_user_id) if row.author_user_id else None,
        mentions=list(row.mentions_json or []),
        resolved_at=row.resolved_at,
        created_at=row.created_at,
    )


def add_comment(
    db: Session, project_id: uuid.UUID, payload: CommentCreate, current_user: UserRead
) -> CommentRead:
    ensure_owned_project(db, project_id, current_user.id)
    body = payload.body.strip()
    if not body:
        raise BadRequestError("A comment cannot be empty.")

    mentions = extract_mentions(body)
    comment = Comment(
        project_id=project_id,
        target_type=payload.target_type,
        target_id=payload.target_id,
        body=body,
        author_user_id=current_user.id,
        mentions_json=mentions or None,
    )
    db.add(comment)
    db.flush()
    _notify_mentions(db, comment, mentions, current_user)
    db.commit()
    db.refresh(comment)

    return _comment_read(comment, {current_user.id: current_user.username})


def _notify_mentions(
    db: Session, comment: Comment, mentions: list[str], author: UserRead
) -> None:
    """Tell the people named in a comment.

    A mention nobody is told about is just decoration. Best effort: a comment
    that saved but failed to notify is better than one that refused to save.
    """
    if not mentions:
        return
    try:
        from service_notifications.service import create_user_notification

        rows = db.scalars(
            select(User).where(func.lower(User.username).in_(mentions))
        ).all()
        # The notification carries the thing the comment is on, so the bell can
        # take the person straight to it rather than to a bare sentence.
        related = {
            "dataset": {"related_dataset_id": comment.target_id},
            "pipeline": {"related_pipeline_id": comment.target_id},
            "run": {"related_run_id": comment.target_id},
        }.get(comment.target_type, {})
        where = comment.target_type.replace("_", " ")
        for user in rows:
            if user.id == author.id:
                continue  # Mentioning yourself is not news.
            create_user_notification(
                db,
                user_id=user.id,
                project_id=comment.project_id,
                type="mention",
                level="info",
                title=f"{author.username} mentioned you on a {where}",
                message=comment.body[:500],
                **related,
            )
    except Exception:  # noqa: BLE001 - see docstring
        from shared_python.logging import get_logger

        get_logger(__name__).exception("comment_mention_notify_failed")


def list_comments(
    db: Session,
    project_id: uuid.UUID,
    target_type: str,
    target_id: uuid.UUID,
    current_user: UserRead,
) -> CommentListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = list(
        db.scalars(
            select(Comment)
            .where(
                Comment.project_id == project_id,
                Comment.target_type == target_type,
                Comment.target_id == target_id,
            )
            .order_by(Comment.created_at.asc())
        ).all()
    )
    names = _usernames(db, [row.author_user_id for row in rows])
    return CommentListResponse(
        items=[_comment_read(row, names) for row in rows],
        open_count=sum(1 for row in rows if row.resolved_at is None),
    )


def resolve_comment(
    db: Session, project_id: uuid.UUID, comment_id: uuid.UUID, current_user: UserRead
) -> CommentRead:
    ensure_owned_project(db, project_id, current_user.id)
    comment = db.scalar(
        select(Comment).where(Comment.id == comment_id, Comment.project_id == project_id)
    )
    if comment is None:
        raise NotFoundError("Comment not found.")

    comment.resolved_at = datetime.now(UTC)
    comment.resolved_by_user_id = current_user.id
    db.commit()
    db.refresh(comment)
    names = _usernames(db, [comment.author_user_id])
    return _comment_read(comment, names)


def total_comments(db: Session) -> int:
    return db.scalar(select(func.count(Comment.id))) or 0
