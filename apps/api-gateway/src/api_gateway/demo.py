"""One-click sample workspace.

A new evaluator's fastest path to understanding the product is a project that
already tells the whole story: real data, a shaping pipeline, a quality rule
that catches something, and a schedule that runs it. This composes those from
the same service functions a user's own clicks would call — no special-case
data, nothing that could not have been built by hand — so the demo is an honest
example, and it is deletable like any other project.

The gateway is the right home: it is the one layer that already depends on
every service, so composing them here introduces no new coupling between them.
"""

from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead
from service_ingestion.schemas import IngestionUpload
from service_ingestion.service import ingest_project_file
from service_projects.schemas import ProjectCreate, ProjectDetail
from service_projects.service import create_project
from service_quality.schemas import DataQualityRuleCreate
from service_quality.service import create_rule
from service_schedules.schemas import ScheduledOperationCreate
from service_schedules.service import create_schedule
from service_transformations.schemas import TransformationPipelineCreate
from service_transformations.service import create_transformation_pipeline

# A small, deliberately messy orders file: a missing amount, a missing email, a
# negative refund. Enough for a filter to change the row count and a not-null
# rule to fail — so the demo shows the product doing something, not a clean
# file where every check trivially passes.
_DEMO_CSV = b"""order_id,order_date,region,customer_email,amount,status
1001,2026-08-01,North,alice@acme.com,120.50,shipped
1002,2026-08-01,South,bob@acme.com,89.99,shipped
1003,2026-08-02,North,carol@acme.com,,pending
1004,2026-08-02,East,dan@acme.com,240.00,shipped
1005,2026-08-03,South,,55.25,cancelled
1006,2026-08-03,West,frank@acme.com,310.75,shipped
1007,2026-08-04,North,grace@acme.com,-15.00,refunded
1008,2026-08-04,East,heidi@acme.com,99.99,shipped
1009,2026-08-05,South,ivan@acme.com,180.00,pending
1010,2026-08-05,West,judy@acme.com,75.50,shipped
1011,2026-08-06,North,ken@acme.com,220.00,shipped
1012,2026-08-06,East,laura@acme.com,140.25,shipped
"""


def create_demo_project(
    db: Session, *, current_user: UserRead, storage_backend, settings
) -> ProjectDetail:
    project = create_project(
        db,
        ProjectCreate(
            name="Acme Retail (demo)",
            description="A worked example: orders from a file, shaped, guarded by a rule, and scheduled.",
        ),
        current_user,
    )

    dataset = ingest_project_file(
        db,
        project_id=project.id,
        dataset_name="Customer orders — sample",
        upload_file=IngestionUpload(
            file_name="acme_orders.csv", content_type="text/csv", file_bytes=_DEMO_CSV
        ),
        storage_backend=storage_backend,
        settings=settings,
        current_user=current_user,
    )

    # Shape it: keep only orders with a positive amount — a filter whose effect
    # is visible in the row count.
    pipeline = create_transformation_pipeline(
        db,
        project_id=project.id,
        dataset_id=dataset.dataset.id,
        payload=TransformationPipelineCreate(
            name="Valid orders",
            description="Keep orders with a positive amount.",
            steps_json=[
                {
                    "step_type": "filter_rows",
                    "config": {
                        "conditions": [
                            {"column": "amount", "operator": "greater_than", "value": 0}
                        ]
                    },
                }
            ],
        ),
        current_user=current_user,
    )

    # Guard it: every order must have a customer email. The sample has one that
    # does not, so the rule has something real to catch.
    create_rule(
        db,
        project.id,
        DataQualityRuleCreate(
            name="Every order has a customer email",
            rule_type="not_null",
            severity="error",
            dataset_id=dataset.dataset.id,
            config={"column": "customer_email"},
        ),
        current_user,
    )

    # Schedule it: run the pipeline every morning, so the demo covers the whole
    # path from raw file to an automated, validated run.
    create_schedule(
        db,
        project_id=project.id,
        payload=ScheduledOperationCreate(
            name="Daily orders refresh",
            schedule_type="transformation_pipeline_run",
            cron_expression="0 9 * * *",
            target_config={"pipeline_id": str(pipeline.id)},
        ),
        current_user=current_user,
    )

    from service_projects.service import get_project_by_id

    # Re-read so the returned detail carries the counts the seed just created.
    return get_project_by_id(db, project.id, current_user)


def build_demo_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., object],
    settings,
) -> APIRouter:
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.post("/demo", response_model=ProjectDetail, status_code=201)
    def create_demo(
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
        storage_backend=Depends(get_storage_backend),
    ) -> ProjectDetail:
        return create_demo_project(
            db, current_user=current_user, storage_backend=storage_backend, settings=settings
        )

    return router
