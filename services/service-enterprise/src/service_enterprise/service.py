"""Tenancy, policies, retention, erasure, and usage over real rows."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import UserRead
from service_datasets.models import Dataset, DatasetVersion
from service_projects.contracts import ensure_owned_project, project_role
from service_projects.models import Project
from shared_python.errors import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    InternalServerError,
    NotFoundError,
)

from service_enterprise import retention as retention_ops
from service_enterprise import security, tenancy, usage
from service_enterprise.models import (
    ErasureRequest,
    Organisation,
    RetentionPolicy,
    SecurityPolicy,
)
from service_enterprise.schemas import (
    ErasureCreate,
    ErasureListResponse,
    ErasureRead,
    LimitsResponse,
    OrganisationCreate,
    OrganisationListResponse,
    OrganisationRead,
    OrganisationUpdate,
    PolicyCreate,
    PolicyListResponse,
    PolicyPreviewResponse,
    PolicyRead,
    PolicyUpdate,
    RetentionCreate,
    RetentionListResponse,
    RetentionRead,
    RetentionRunResponse,
    UsageResponse,
)

MAX_ANALYSED_ROWS = 500_000
SAMPLE_ROWS = 5


def _slugify(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return cleaned or "organisation"


# --------------------------------------------------------------------------
# Organisations
# --------------------------------------------------------------------------


def _require_platform_admin(current_user: UserRead) -> None:
    """Creating a tenant is not a project-level action.

    Project roles say what somebody may do inside a project; nothing inside a
    project should be able to create the boundary the project lives in.
    """
    if current_user.role != "admin":
        raise ForbiddenError("Only a platform admin can manage organisations.")


def create_organisation(
    db: Session, payload: OrganisationCreate, current_user: UserRead
) -> OrganisationRead:
    _require_platform_admin(current_user)

    slug = _slugify(payload.name)
    if db.scalar(select(Organisation).where(Organisation.slug == slug)):
        raise BadRequestError(f"An organisation called '{payload.name}' already exists.")

    organisation = Organisation(
        name=payload.name.strip(),
        slug=slug,
        plan=payload.plan,
        max_projects=payload.max_projects,
        max_datasets=payload.max_datasets,
    )
    db.add(organisation)
    db.commit()
    db.refresh(organisation)
    return _organisation_read(db, organisation)


def _organisation_read(db: Session, organisation: Organisation) -> OrganisationRead:
    return OrganisationRead(
        id=organisation.id,
        name=organisation.name,
        slug=organisation.slug,
        plan=organisation.plan,
        max_projects=organisation.max_projects,
        max_datasets=organisation.max_datasets,
        is_active=organisation.is_active,
        project_count=db.scalar(
            select(func.count(Project.id)).where(Project.organisation_id == organisation.id)
        )
        or 0,
        member_count=db.scalar(
            select(func.count(User.id)).where(User.organisation_id == organisation.id)
        )
        or 0,
        created_at=organisation.created_at,
    )


def list_organisations(db: Session, current_user: UserRead) -> OrganisationListResponse:
    _require_platform_admin(current_user)
    rows = db.scalars(select(Organisation).order_by(Organisation.name)).all()
    return OrganisationListResponse(items=[_organisation_read(db, row) for row in rows])


def assign_user(
    db: Session, organisation_id: uuid.UUID, user_id: uuid.UUID, current_user: UserRead
) -> OrganisationRead:
    _require_platform_admin(current_user)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise NotFoundError("Organisation not found.")

    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")

    user.organisation_id = organisation_id
    db.commit()
    return _organisation_read(db, organisation)


def assign_project(
    db: Session, organisation_id: uuid.UUID, project_id: uuid.UUID, current_user: UserRead
) -> OrganisationRead:
    _require_platform_admin(current_user)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise NotFoundError("Organisation not found.")

    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")

    project.organisation_id = organisation_id
    db.commit()
    return _organisation_read(db, organisation)


def unassign_user(
    db: Session, organisation_id: uuid.UUID, user_id: uuid.UUID, current_user: UserRead
) -> OrganisationRead:
    """Take a user back out of an organisation.

    Membership was append-only: `assign_user` put somebody into a tenant and
    nothing took them out again, so an offboarded colleague kept access to
    every project in the organisation for as long as the account existed.

    Revoking is enough to cut that access off. `same_tenant` compares the
    project's organisation with the user's, so a user with no organisation
    stops matching every project that has one -- no membership row needs
    touching.

    The organisation in the path has to be the one they are actually in.
    Without that check, a request naming the wrong tenant would still remove
    them from whichever one they belonged to.
    """
    _require_platform_admin(current_user)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise NotFoundError("Organisation not found.")

    user = db.get(User, user_id)
    if user is None:
        raise NotFoundError("User not found.")
    if user.organisation_id != organisation_id:
        raise NotFoundError("That user is not a member of this organisation.")

    user.organisation_id = None
    db.commit()
    return _organisation_read(db, organisation)


def unassign_project(
    db: Session, organisation_id: uuid.UUID, project_id: uuid.UUID, current_user: UserRead
) -> OrganisationRead:
    """Take a project back out of an organisation.

    Refused when it would strand the project. `same_tenant` compares the
    project's organisation with the caller's, so a project with none is
    reachable only by users who also have none -- and if its owner is in an
    organisation, removing the project from that organisation hides it from
    the owner, its members and every admin at once, with its data still in the
    database.

    Moving it somewhere else is what that case wants, and `assign_project`
    already does it, so the refusal points there rather than inventing a
    second way to do the same thing.
    """
    _require_platform_admin(current_user)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise NotFoundError("Organisation not found.")

    project = db.get(Project, project_id)
    if project is None:
        raise NotFoundError("Project not found.")
    if project.organisation_id != organisation_id:
        raise NotFoundError("That project does not belong to this organisation.")

    owner = db.get(User, project.owner_user_id) if project.owner_user_id else None
    if owner is not None and owner.organisation_id is not None:
        raise ConflictError(
            f"{project.name} would become unreachable: its owner belongs to an "
            f"organisation, and a project with none is only visible to users "
            f"with none. Assign it to another organisation instead."
        )

    project.organisation_id = None
    db.commit()
    return _organisation_read(db, organisation)


def update_organisation(
    db: Session, organisation_id: uuid.UUID, payload: "OrganisationUpdate", current_user: UserRead
) -> OrganisationRead:
    """Rename a tenant or adjust its limits. The slug is left alone, because it
    is what other records refer to it by."""
    _require_platform_admin(current_user)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise NotFoundError("Organisation not found.")
    fields = payload.model_dump(exclude_unset=True)
    if fields.get("name"):
        organisation.name = fields["name"].strip()
    if fields.get("plan"):
        organisation.plan = fields["plan"]
    if "max_projects" in fields:
        organisation.max_projects = fields["max_projects"]
    if "max_datasets" in fields:
        organisation.max_datasets = fields["max_datasets"]
    db.commit()
    db.refresh(organisation)
    return _organisation_read(db, organisation)


def delete_organisation(
    db: Session, organisation_id: uuid.UUID, current_user: UserRead
) -> None:
    """Remove an empty organisation.

    `organisation_id` is a plain column on both `users` and `projects`, with no
    foreign key behind it -- so nothing in the database would stop this from
    leaving rows pointing at a tenant that no longer exists, and nothing would
    report it afterwards. Those users and projects would simply stop matching
    any tenant, which is the same silent disappearance `unassign_project`
    refuses.

    So emptying it first is the caller's job, and the refusal says how much is
    left to move.
    """
    _require_platform_admin(current_user)
    organisation = db.get(Organisation, organisation_id)
    if organisation is None:
        raise NotFoundError("Organisation not found.")

    projects = db.scalar(
        select(func.count(Project.id)).where(Project.organisation_id == organisation_id)
    ) or 0
    members = db.scalar(
        select(func.count(User.id)).where(User.organisation_id == organisation_id)
    ) or 0
    if projects or members:
        raise ConflictError(
            f"{organisation.name} still holds {projects} project(s) and "
            f"{members} member(s). Move them to another organisation first; "
            f"deleting it now would leave them pointing at a tenant that no "
            f"longer exists, reachable by nobody."
        )

    db.delete(organisation)
    db.commit()


def limits(db: Session, current_user: UserRead) -> LimitsResponse:
    organisation_id = tenancy.organisation_of_user(db, current_user.id)
    return LimitsResponse(**tenancy.check_limits(db, organisation_id))


# --------------------------------------------------------------------------
# Security policies
# --------------------------------------------------------------------------


def _get_dataset(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID) -> Dataset:
    dataset = db.scalar(
        select(Dataset).where(Dataset.id == dataset_id, Dataset.project_id == project_id)
    )
    if dataset is None:
        raise NotFoundError("Dataset not found.")
    return dataset


def _dataset_columns(dataset: Dataset) -> list[str]:
    for candidate in (dataset.schema_json, dataset.schema_snapshot):
        if isinstance(candidate, dict):
            ordered = candidate.get("ordered_columns")
            if isinstance(ordered, list) and ordered:
                return [str(name) for name in ordered]
    return []


def _to_policy(row: SecurityPolicy) -> security.Policy:
    return security.Policy(
        name=row.name,
        role=row.role,
        row_rules=[security.RowRule(**rule) for rule in (row.row_rules_json or [])],
        column_rules=[security.ColumnRule(**rule) for rule in (row.column_rules_json or [])],
        enabled=row.enabled,
    )


def _policy_read(row: SecurityPolicy) -> PolicyRead:
    return PolicyRead(
        id=row.id,
        project_id=row.project_id,
        dataset_id=row.dataset_id,
        name=row.name,
        role=row.role,  # type: ignore[arg-type]
        row_rules=[rule for rule in (row.row_rules_json or [])],  # type: ignore[misc]
        column_rules=[rule for rule in (row.column_rules_json or [])],  # type: ignore[misc]
        enabled=row.enabled,
        created_at=row.created_at,
    )


def create_policy(
    db: Session, project_id: uuid.UUID, payload: PolicyCreate, current_user: UserRead
) -> PolicyRead:
    ensure_owned_project(db, project_id, current_user.id)
    dataset = _get_dataset(db, project_id, payload.dataset_id)

    policy = security.Policy(
        name=payload.name,
        role=payload.role,
        row_rules=[security.RowRule(**rule.model_dump()) for rule in payload.row_rules],
        column_rules=[security.ColumnRule(**rule.model_dump()) for rule in payload.column_rules],
    )
    problems = security.validate_policy(policy, _dataset_columns(dataset))
    if problems:
        raise BadRequestError(" ".join(problems))

    row = SecurityPolicy(
        project_id=project_id,
        dataset_id=payload.dataset_id,
        name=payload.name.strip(),
        role=payload.role,
        row_rules_json=[rule.model_dump(mode="json") for rule in payload.row_rules] or None,
        column_rules_json=[rule.model_dump(mode="json") for rule in payload.column_rules] or None,
        enabled=payload.enabled,
        created_by_user_id=current_user.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _policy_read(row)


def list_policies(
    db: Session, project_id: uuid.UUID, current_user: UserRead, *, dataset_id: uuid.UUID | None = None
) -> PolicyListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    statement = select(SecurityPolicy).where(SecurityPolicy.project_id == project_id)
    if dataset_id is not None:
        statement = statement.where(SecurityPolicy.dataset_id == dataset_id)

    rows = list(db.scalars(statement.order_by(SecurityPolicy.created_at)).all())
    warnings: list[str] = []
    if rows and not any(row.enabled for row in rows):
        warnings.append("Every policy here is disabled, so nothing is restricted.")

    return PolicyListResponse(items=[_policy_read(row) for row in rows], warnings=warnings)


def update_policy(
    db: Session,
    project_id: uuid.UUID,
    policy_id: uuid.UUID,
    payload: PolicyUpdate,
    current_user: UserRead,
) -> PolicyRead:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.scalar(
        select(SecurityPolicy).where(
            SecurityPolicy.id == policy_id, SecurityPolicy.project_id == project_id
        )
    )
    if row is None:
        raise NotFoundError("Policy not found.")

    if payload.name is not None:
        row.name = payload.name.strip()
    if payload.row_rules is not None:
        row.row_rules_json = [rule.model_dump(mode="json") for rule in payload.row_rules] or None
    if payload.column_rules is not None:
        row.column_rules_json = [
            rule.model_dump(mode="json") for rule in payload.column_rules
        ] or None
    if payload.enabled is not None:
        row.enabled = payload.enabled

    db.commit()
    db.refresh(row)
    return _policy_read(row)


def delete_policy(
    db: Session, project_id: uuid.UUID, policy_id: uuid.UUID, current_user: UserRead
) -> None:
    ensure_owned_project(db, project_id, current_user.id)
    row = db.scalar(
        select(SecurityPolicy).where(
            SecurityPolicy.id == policy_id, SecurityPolicy.project_id == project_id
        )
    )
    if row is None:
        raise NotFoundError("Policy not found.")
    db.delete(row)
    db.commit()


def _load_frame(db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, storage) -> pd.DataFrame:
    from service_ingestion.parsers import parse_tabular_file

    dataset = _get_dataset(db, project_id, dataset_id)
    if not dataset.file_path or not dataset.file_type:
        raise BadRequestError(f"'{dataset.name}' has no stored file to read.")

    try:
        payload = storage.read_bytes(dataset.file_path)
    except FileNotFoundError as exc:
        raise BadRequestError(f"The stored file for '{dataset.name}' is missing.") from exc

    frame = parse_tabular_file(file_bytes=payload, file_type=dataset.file_type).dataframe
    if len(frame) > MAX_ANALYSED_ROWS:
        raise BadRequestError(f"'{dataset.name}' is too large for this preview.")
    return frame


def preview_policies(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    role: str,
    current_user: UserRead,
    storage,
) -> PolicyPreviewResponse:
    """What somebody with this role would actually see.

    The only way to know a policy does what was intended is to look at the
    result, and looking at it *before* granting the role is the whole point.
    """
    return _run_preview(db, project_id, dataset_id, role, current_user, storage)


def preview_policies_as_user(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    target_user_id: uuid.UUID,
    current_user: UserRead,
    storage,
) -> PolicyPreviewResponse:
    """What one specific person would see -- their project role resolved for them.

    "View as role" answers the abstract question; "view as user" answers the one
    a reviewer actually asks -- *would Dana see the salary column?* -- by
    resolving Dana's effective role in this project rather than making the
    reviewer know it.
    """
    ensure_owned_project(db, project_id, current_user.id)
    target = db.get(User, target_user_id)
    if target is None:
        raise NotFoundError("That user does not exist.")
    project = db.get(Project, project_id)
    # The owner is effectively admin; otherwise the membership role, or viewer.
    if project is not None and project.owner_user_id == target_user_id:
        role = "admin"
    else:
        role = project_role(db, project_id, target_user_id) or "viewer"
    return _run_preview(
        db, project_id, dataset_id, role, current_user, storage,
        viewed_as_username=target.username,
    )


def _run_preview(
    db: Session,
    project_id: uuid.UUID,
    dataset_id: uuid.UUID,
    role: str,
    current_user: UserRead,
    storage,
    *,
    viewed_as_username: str | None = None,
) -> PolicyPreviewResponse:
    ensure_owned_project(db, project_id, current_user.id)
    frame = _load_frame(db, project_id, dataset_id, storage)

    policies = [
        _to_policy(row)
        for row in db.scalars(
            select(SecurityPolicy).where(
                SecurityPolicy.project_id == project_id,
                SecurityPolicy.dataset_id == dataset_id,
            )
        ).all()
    ]
    restricted, applied = security.apply_policies(frame, policies, role=role)

    return PolicyPreviewResponse(
        dataset_id=dataset_id,
        role=role,  # type: ignore[arg-type]
        viewed_as_username=viewed_as_username,
        **{key: value for key, value in applied.to_dict().items() if key != "summary"},
        summary=applied.summary(),
        sample_rows=_records(restricted.head(SAMPLE_ROWS)),
    )


def _records(frame: pd.DataFrame) -> list[dict[str, Any]]:
    import math

    rows: list[dict[str, Any]] = []
    for record in frame.to_dict(orient="records"):
        cleaned: dict[str, Any] = {}
        for key, value in record.items():
            if hasattr(value, "item"):
                value = value.item()
            if value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value))):
                cleaned[str(key)] = None
            elif isinstance(value, (str, int, float, bool)):
                cleaned[str(key)] = value
            else:
                cleaned[str(key)] = str(value)
        rows.append(cleaned)
    return rows


def visible_frame(
    db: Session, project_id: uuid.UUID, dataset_id: uuid.UUID, current_user: UserRead, frame: pd.DataFrame
) -> tuple[pd.DataFrame, security.AppliedPolicy]:
    """Narrow a frame to what this user's role permits.

    Exposed for other services to call on any read path that hands rows to a
    person. A policy only protects the paths that ask.
    """
    role = project_role(db, project_id, current_user.id) or "viewer"
    policies = [
        _to_policy(row)
        for row in db.scalars(
            select(SecurityPolicy).where(
                SecurityPolicy.project_id == project_id,
                SecurityPolicy.dataset_id == dataset_id,
                SecurityPolicy.enabled.is_(True),
            )
        ).all()
    ]
    return security.apply_policies(frame, policies, role=role)


# --------------------------------------------------------------------------
# Retention
# --------------------------------------------------------------------------


def _retention_read(row: RetentionPolicy) -> RetentionRead:
    return RetentionRead(
        id=row.id,
        project_id=row.project_id,
        resource_type=row.resource_type,
        resource_label=retention_ops.resource_type_label(row.resource_type),
        retain_days=row.retain_days,
        enabled=row.enabled,
        dry_run=row.dry_run,
        last_run_at=row.last_run_at,
        last_deleted_count=row.last_deleted_count,
    )


def create_retention(
    db: Session, project_id: uuid.UUID, payload: RetentionCreate, current_user: UserRead
) -> RetentionRead:
    ensure_owned_project(db, project_id, current_user.id)
    if payload.resource_type not in retention_ops.RETAINABLE:
        raise BadRequestError(
            f"'{payload.resource_type}' cannot have a retention policy. "
            f"Options: {', '.join(sorted(retention_ops.RETAINABLE))}."
        )

    existing = db.scalar(
        select(RetentionPolicy).where(
            RetentionPolicy.project_id == project_id,
            RetentionPolicy.resource_type == payload.resource_type,
        )
    )
    if existing is not None:
        raise BadRequestError(
            f"There is already a retention policy for {payload.resource_type}; edit that one."
        )

    row = RetentionPolicy(
        project_id=project_id,
        resource_type=payload.resource_type,
        retain_days=payload.retain_days,
        enabled=payload.enabled,
        dry_run=payload.dry_run,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _retention_read(row)


def list_retention(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> RetentionListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(RetentionPolicy).where(RetentionPolicy.project_id == project_id)
    ).all()
    return RetentionListResponse(
        items=[_retention_read(row) for row in rows],
        retainable=dict(retention_ops.RETAINABLE),
    )


# Which model each retainable kind refers to, and how to date it.
def _retention_target(resource_type: str):
    if resource_type == "workflow_runs":
        from service_workflows.models import WorkflowRun

        return WorkflowRun, WorkflowRun.created_at, WorkflowRun.project_id
    if resource_type == "pipeline_runs":
        from service_pipeline_runs.models import PipelineRun

        return PipelineRun, PipelineRun.created_at, PipelineRun.project_id
    if resource_type == "dataset_metrics":
        from service_observability.models import DatasetMetric

        return DatasetMetric, DatasetMetric.captured_at, DatasetMetric.project_id
    if resource_type == "audit_entries":
        from service_governance.models import AuditEntry

        return AuditEntry, AuditEntry.created_at, AuditEntry.project_id
    if resource_type == "report_deliveries":
        from service_reporting.models import ReportDelivery

        return ReportDelivery, ReportDelivery.created_at, ReportDelivery.project_id
    if resource_type == "incidents":
        from service_observability.models import Incident

        return Incident, Incident.resolved_at, Incident.project_id
    raise BadRequestError(f"'{resource_type}' cannot have a retention policy.")


def run_retention(
    db: Session,
    project_id: uuid.UUID,
    current_user: UserRead | None = None,
    *,
    now: datetime | None = None,
) -> RetentionRunResponse:
    """Apply every enabled policy, deleting only where told to."""
    if current_user is not None:
        ensure_owned_project(db, project_id, current_user.id)

    moment = now or datetime.now(UTC)
    plans: list[retention_ops.DeletionPlan] = []

    for policy in db.scalars(
        select(RetentionPolicy).where(
            RetentionPolicy.project_id == project_id, RetentionPolicy.enabled.is_(True)
        )
    ).all():
        model, date_column, project_column = _retention_target(policy.resource_type)
        cutoff = retention_ops.cutoff_for(policy.retain_days, now=moment)

        condition = (project_column == project_id) & (date_column < cutoff)
        # Incidents are dated by resolution, so an unresolved one has no date
        # and must never be swept -- it is the opposite of expired.
        if policy.resource_type == "incidents":
            condition = condition & date_column.is_not(None)

        matched = db.scalar(select(func.count(model.id)).where(condition)) or 0
        plan = retention_ops.DeletionPlan(
            resource_type=policy.resource_type,
            cutoff=cutoff,
            matched=int(matched),
            dry_run=policy.dry_run,
        )

        if not policy.dry_run and matched:
            db.execute(delete(model).where(condition))
            plan.deleted = int(matched)

        policy.last_run_at = moment
        policy.last_deleted_count = plan.deleted
        plans.append(plan)

    db.commit()

    total_matched = sum(plan.matched for plan in plans)
    total_deleted = sum(plan.deleted for plan in plans)
    if not plans:
        summary = "No retention policies are set for this project."
    elif total_deleted:
        summary = f"Deleted {total_deleted:,} record(s) across {len(plans)} policy(ies)."
    elif total_matched:
        summary = (
            f"{total_matched:,} record(s) are past their retention, and every policy is in "
            "report-only mode. Nothing was deleted."
        )
    else:
        summary = "Nothing is past its retention period."

    return RetentionRunResponse(
        plans=[plan.to_dict() for plan in plans],
        total_matched=total_matched,
        total_deleted=total_deleted,
        summary=summary,
    )


# --------------------------------------------------------------------------
# Erasure
# --------------------------------------------------------------------------


def _erasure_read(row: ErasureRequest) -> ErasureRead:
    return ErasureRead(
        id=row.id,
        project_id=row.project_id,
        subject_kind=row.subject_kind,  # type: ignore[arg-type]
        mode=getattr(row, "mode", None) or "correction",
        status=row.status,
        datasets_searched=row.datasets_searched,
        rows_affected=row.rows_affected,
        report=row.report_json,
        completed_at=row.completed_at,
        created_at=row.created_at,
    )


def request_erasure(
    db: Session,
    project_id: uuid.UUID,
    payload: ErasureCreate,
    current_user: UserRead,
    storage,
) -> ErasureRead:
    """Find a person across every dataset, and optionally redact them.

    Searching always runs; redacting only when asked. An erasure request that
    silently rewrote data on submission would be impossible to review first,
    and reviewing first is what makes it safe.
    """
    ensure_owned_project(db, project_id, current_user.id)
    mode = getattr(payload, "mode", "correction")

    datasets = list(db.scalars(select(Dataset).where(Dataset.project_id == project_id)).all())
    report = retention_ops.ErasureReport(
        subject_value=payload.subject_value,
        subject_kind=payload.subject_kind,
        datasets_searched=0,
        mode=mode,
    )

    for dataset in datasets:
        if not dataset.file_path or not dataset.file_type:
            report.unsearchable.append(dataset.name)
            continue
        try:
            frame = _load_frame(db, project_id, dataset.id, storage)
        except Exception:  # noqa: BLE001 - one unreadable dataset must not stop the search
            report.unsearchable.append(dataset.name)
            continue

        report.datasets_searched += 1
        columns = retention_ops.candidate_columns(
            [str(column) for column in frame.columns], payload.subject_kind
        )
        dataset_hits = list(
            retention_ops.find_subject(frame, payload.subject_value, columns)
        )
        for column, count in dataset_hits:
            report.hits.append(
                retention_ops.ColumnHit(dataset_name=dataset.name, column=column, rows=count)
            )

        if not (payload.apply and dataset_hits):
            continue

        # A destructive erasure must not overwrite a derived artifact in place:
        # it is produced from a pipeline and may share content with a pinned
        # snapshot (see P7). Redact the base, and report the derived one as
        # blocked -- it clears when its pipeline is re-run against the corrected
        # base -- rather than corrupting it or claiming a success that is not one.
        if mode == "destructive" and dataset.is_derived:
            report.blocked.append(
                {
                    "dataset": dataset.name,
                    "reason": "derived artifact — re-run its pipeline after the base is corrected",
                }
            )
            continue

        redacted, affected = retention_ops.redact_subject(
            frame, payload.subject_value, columns
        )
        if not affected:
            continue

        if mode == "destructive":
            _erase_destructively(db, storage, dataset, redacted, payload, report)
        else:
            _erase_by_correction(db, storage, dataset, redacted, current_user)
            report.erased.append(dataset.name)

    if payload.apply:
        # A dataset we could not read is a dataset we cannot claim is clean. Both
        # modes surface it; it is the difference between "completed" and "partial".
        for name in report.unsearchable:
            report.blocked.append(
                {"dataset": name, "reason": "could not be read to search or redact"}
            )

    status = _erasure_status(payload.apply, report)
    row = ErasureRequest(
        project_id=project_id,
        subject_value=payload.subject_value,
        subject_kind=payload.subject_kind,
        mode=mode,
        status=status,
        requested_by_user_id=current_user.id,
        completed_at=datetime.now(UTC) if payload.apply else None,
        datasets_searched=report.datasets_searched,
        rows_affected=report.rows_affected,
        report_json=report.to_dict(),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _erasure_read(row)


def _erasure_status(applied: bool, report: retention_ops.ErasureReport) -> str:
    """Never report success while data remains. Blocked datasets downgrade an
    apply from completed to partial (some erased) or blocked (none erased)."""
    if not applied:
        return "reported"
    if not report.blocked:
        return "completed"
    return "partial" if report.erased else "blocked"


def _store_frame(storage, path: str, frame: pd.DataFrame) -> bytes:
    """Write a redacted frame to storage and return the bytes written.

    Prefers the real backend interface (`save_upload`), falls back to the
    simpler `write_bytes` some test doubles expose, and refuses to proceed if
    neither exists — a storage backend that cannot write must fail the erasure,
    never let it report success with the data still there. (The previous
    `hasattr` guard did exactly that silent skip against the real backend.)
    """
    payload = frame.to_csv(index=False).encode()
    if hasattr(storage, "save_upload"):
        storage.save_upload(relative_path=path, file_bytes=payload)
    elif hasattr(storage, "write_bytes"):
        storage.write_bytes(path, payload)
    else:
        raise InternalServerError("The storage backend cannot write redacted data.")
    return payload


def _erase_by_correction(
    db: Session, storage, dataset: Dataset, redacted: pd.DataFrame, current_user: UserRead
) -> None:
    """Ordinary forward-moving correction: append a corrected version.

    The head advances to a clean artifact; history — including the version that
    still holds the subject's data — remains readable, which is the documented
    difference from a destructive erasure. Publishing through the same seam as
    every producer means the corrected head and its version row land together.

    The corrected artifact is CSV regardless of the original format — the same
    round-trip the legacy in-place path took, and the canonical-type loss §5
    already names.
    """
    from service_datasets.service import apply_dataset_materialization_success
    from service_ingestion.profiling import build_preview, build_profile, infer_schema
    from shared_python.storage import content_digest

    new_path = f"corrected/{dataset.project_id}/{dataset.id}/{uuid.uuid4().hex}.csv"
    payload = _store_frame(storage, new_path, redacted)
    schema = infer_schema(dataframe=redacted)
    dataset.file_type = "csv"
    apply_dataset_materialization_success(
        db,
        dataset=dataset,
        file_path=new_path,
        file_name="corrected.csv",
        schema_json=schema,
        schema_snapshot={"columns": schema["columns"]},
        preview_json=build_preview(dataframe=redacted, limit=50),
        profile_json=build_profile(
            dataframe=redacted, sample_limit=5, file_size_bytes=len(payload)
        ),
        row_count=int(len(redacted)),
        column_count=int(len(redacted.columns)),
        content_hash=content_digest(payload),
        created_by_user_id=current_user.id,
    )


def _erase_destructively(
    db: Session,
    storage,
    dataset: Dataset,
    redacted: pd.DataFrame,
    payload: ErasureCreate,
    report: retention_ops.ErasureReport,
) -> None:
    """Authorised destructive erasure: remove the subject from the live artifact
    AND from every historical version — bytes, previews, and content hashes.

    Appending a redacted head while the old bytes stay readable through history
    is the failure §2 names; this rewrites each version artifact in place (the
    sanctioned exception to version immutability), re-digests it so the recorded
    hash keeps telling the truth, and rebuilds the previews that also carried
    the data. A version whose artifact cannot be read is reported blocked by
    name — never silently skipped.
    """
    from service_ingestion.parsers import parse_tabular_file
    from service_ingestion.profiling import build_preview, build_profile
    from shared_python.storage import content_digest

    head_bytes = _store_frame(storage, dataset.file_path, redacted)
    head_digest = content_digest(head_bytes)
    head_preview = build_preview(dataframe=redacted, limit=50)
    dataset.file_type = "csv"
    dataset.preview_json = head_preview
    dataset.profile_json = build_profile(
        dataframe=redacted, sample_limit=5, file_size_bytes=len(head_bytes)
    )

    versions = list(
        db.scalars(
            select(DatasetVersion).where(DatasetVersion.dataset_id == dataset.id)
        ).all()
    )
    for version in versions:
        if version.file_path == dataset.file_path:
            # The head version's artifact was just rewritten above; keep its
            # recorded hash and preview true to the new bytes.
            version.content_hash = head_digest
            version.file_type = "csv"
            version.preview_json = dict(head_preview)
            continue
        try:
            stored = storage.read_bytes(version.file_path)
            v_frame = parse_tabular_file(
                file_bytes=stored,
                file_type=version.file_type or dataset.file_type or "csv",
            ).dataframe
        except Exception:  # noqa: BLE001 - an unreadable version is reported, not skipped
            report.blocked.append(
                {
                    "dataset": f"{dataset.name} (version {version.version_number})",
                    "reason": "historical artifact could not be read to redact",
                }
            )
            continue
        v_columns = retention_ops.candidate_columns(
            [str(column) for column in v_frame.columns], payload.subject_kind
        )
        v_redacted, v_affected = retention_ops.redact_subject(
            v_frame, payload.subject_value, v_columns
        )
        if not v_affected:
            continue
        v_bytes = _store_frame(storage, version.file_path, v_redacted)
        version.content_hash = content_digest(v_bytes)
        version.file_type = "csv"
        version.preview_json = build_preview(dataframe=v_redacted, limit=50)

    report.erased.append(dataset.name)


def list_erasures(
    db: Session, project_id: uuid.UUID, current_user: UserRead
) -> ErasureListResponse:
    ensure_owned_project(db, project_id, current_user.id)
    rows = db.scalars(
        select(ErasureRequest)
        .where(ErasureRequest.project_id == project_id)
        .order_by(ErasureRequest.created_at.desc())
        .limit(100)
    ).all()
    return ErasureListResponse(items=[_erasure_read(row) for row in rows])


# --------------------------------------------------------------------------
# Usage
# --------------------------------------------------------------------------


def usage_report(
    db: Session, project_id: uuid.UUID, current_user: UserRead, *, period_days: int = 30
) -> UsageResponse:
    ensure_owned_project(db, project_id, current_user.id)
    report = usage.summarise(db, project_id=project_id, period_days=period_days)
    return UsageResponse(**report.to_dict())
