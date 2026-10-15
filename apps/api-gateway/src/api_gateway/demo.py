"""One-click sample workspace.

A new evaluator's fastest path to understanding the product is a project that
already tells the whole story: real data, a recipe that cleans it, a check
that catches something, a schedule that runs it, an alert on its numbers and
a chart on a dashboard. This composes those from the same service functions a
user's own clicks would call -- no special-case data, nothing that could not
have been built by hand -- so the demo is an honest example, and it is
deletable like any other project.

It does what it says (A9, Z1): the recipe and the check run as the demo is
made, so the cleaned dataset, the failing row and the chart of the cleaned
orders are there when it opens, rather than a dashboard that claims a
cleaning nothing has done. The help's screenshots are taken of this project.

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
from service_observability.alerts import create_alert
from service_observability.schemas import MetricAlertCreate
from service_quality.schemas import DataQualityEvaluationRequest, DataQualityRuleCreate
from service_quality.service import create_rule, evaluate_dataset
from service_reporting.schemas import (
    ChartCreate,
    DashboardCreate,
    MeasureInput,
    QueryInput,
    TileInput,
)
from service_reporting.service import create_chart, create_dashboard
from service_schedules.schemas import ScheduledOperationCreate
from service_schedules.service import create_schedule
from service_transformations.schemas import TransformationPipelineCreate
from service_transformations.run import run_saved_transformation_pipeline
from service_transformations.service import create_transformation_pipeline

# A small, deliberately messy orders file: a missing amount, a missing email, a
# negative refund. Enough for a filter to change the row count and a check to
# fail, so the demo shows the product doing something, not a clean file where
# every check trivially passes.
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
            description=(
                "A worked example: orders from a file, cleaned by a recipe, checked, "
                "run every morning and shown on a dashboard."
            ),
        ),
        current_user,
    )
    raw = ingest_project_file(
        db,
        project_id=project.id,
        dataset_name="Customer orders (sample)",
        upload_file=IngestionUpload(
            file_name="acme_orders.csv", content_type="text/csv", file_bytes=_DEMO_CSV
        ),
        storage_backend=storage_backend,
        settings=settings,
        current_user=current_user,
    ).dataset

    # Clean it: keep orders with a positive amount, a filter whose effect shows
    # in the row count (12 orders in, 10 out). Run once, so the cleaned
    # dataset is there to open.
    recipe = create_transformation_pipeline(
        db,
        project_id=project.id,
        dataset_id=raw.id,
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
    cleaned = run_saved_transformation_pipeline(
        db,
        project_id=project.id,
        pipeline_id=recipe.id,
        current_user=current_user,
        storage_backend=storage_backend,
        settings=settings,
        notify_on_complete=False,
    ).dataset

    # Check it: every order needs a customer email. One of the sample's does
    # not, so the check has something real to catch, and has caught it.
    create_rule(
        db,
        project.id,
        DataQualityRuleCreate(
            name="Every order has a customer email",
            rule_type="not_null",
            severity="error",
            dataset_id=raw.id,
            config={"column": "customer_email"},
        ),
        current_user,
    )
    evaluate_dataset(
        db, project.id, raw.id, DataQualityEvaluationRequest(), current_user, storage_backend, settings
    )

    # Run it every morning.
    create_schedule(
        db,
        project_id=project.id,
        payload=ScheduledOperationCreate(
            name="Daily orders refresh",
            schedule_type="transformation_pipeline_run",
            cron_expression="0 9 * * *",
            target_config={"pipeline_id": str(recipe.id)},
        ),
        current_user=current_user,
    )

    # Watch it: say so if the cleaned orders suddenly halve or double.
    create_alert(
        db,
        project.id,
        cleaned.id,
        MetricAlertCreate(metric_key="row_count", condition="changes_by", threshold=50),
        current_user,
    )

    # Show it: revenue by region from the cleaned orders, on a dashboard, so the
    # demo runs from a raw file to something a stakeholder would open.
    chart = create_chart(
        db,
        project.id,
        ChartCreate(
            dataset_id=cleaned.id,
            name="Revenue by region",
            description="Total amount of the valid orders in each region.",
            chart_type="column",
            query=QueryInput(
                dimensions=["region"],
                measures=[
                    MeasureInput(column="amount", aggregation="sum", label="Total amount")
                ],
            ),
        ),
        current_user,
    )
    create_dashboard(
        db,
        project.id,
        DashboardCreate(
            name="Acme Retail overview",
            description="Revenue from the valid orders, by region.",
            tiles=[TileInput(chart_id=chart.id, position=0, width=12, height=2)],
        ),
        current_user,
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
