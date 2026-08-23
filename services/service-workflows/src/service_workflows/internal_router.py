"""Token-gated endpoint that drives the queue.

The same shared secret the scheduler uses guards this, so an external process
(cron, Kubernetes CronJob, or the bundled worker) can ask the gateway to drain
the queue without exposing run execution to ordinary API callers.
"""

from __future__ import annotations

import secrets
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.orm import Session

from service_workflows.queue import drain_queue, queue_depth, running_count
from service_workflows.schemas import WorkerTickResponse


def build_internal_router(
    get_db: Callable[..., Session],
    get_storage_backend: Callable[..., Any],
    settings: Any,
) -> APIRouter:
    router = APIRouter(tags=["internal-workflows"])

    def _require_token(x_internal_token: Annotated[str | None, Header()] = None) -> None:
        expected = getattr(settings, "scheduler_internal_token", None)
        if not expected:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=(
                    "Workflow worker API is not configured (set SCHEDULER_INTERNAL_TOKEN)."
                ),
            )
        if not x_internal_token or not secrets.compare_digest(x_internal_token, expected):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail="Invalid internal token."
            )

    @router.post("/internal/workflows/run-queue-once", response_model=WorkerTickResponse)
    def post_run_queue_once(
        max_runs: int = Query(default=5, ge=1, le=50),
        db: Session = Depends(get_db),
        storage_backend=Depends(get_storage_backend),
        _: None = Depends(_require_token),
    ) -> WorkerTickResponse:
        completed = drain_queue(
            db, storage_backend=storage_backend, settings=settings, max_runs=max_runs
        )
        return WorkerTickResponse(
            runs_processed=len(completed),
            run_ids=[run.id for run in completed],
            queue_depth=queue_depth(db),
        )

    @router.get("/internal/workflows/queue-status", response_model=dict)
    def get_queue_status(
        db: Session = Depends(get_db),
        _: None = Depends(_require_token),
    ) -> dict:
        return {"queued": queue_depth(db), "running": running_count(db)}

    return router
