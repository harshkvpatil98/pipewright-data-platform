"""HTTP surface for the workbench.

Read-only by default runs all the way through here: `allow_writes` has to be
asked for on every request, the service narrows it to what the role carries, and
the response says which policy was actually in force. A client cannot end up
believing it is in read-only mode when it is not.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_workbench import service
from service_workbench.temporal import temporal_query
from service_workbench.schemas import (
    TemporalQueryRequest,
    TemporalQueryResponse,
    CellRead,
    CellResultRead,
    CompletionRead,
    CompletionRequest,
    CompletionResponse,
    ExplainRequest,
    ExplainResponse,
    NotebookCreate,
    NotebookListResponse,
    NotebookRead,
    NotebookRunRequest,
    NotebookRunResponse,
    NotebookUpdate,
    PolicyRead,
    QueryRunListResponse,
    QueryRunRead,
    RecipeParseRequest,
    RecipeParseResponse,
    RecipeYamlRequest,
    RecipeYamlResponse,
    RunRequest,
    RunResponse,
    SandboxStatusResponse,
    SavedQueryCreate,
    SavedQueryListResponse,
    SavedQueryRead,
    SavedQueryUpdate,
    SchemaResponse,
    ScriptPlanRequest,
    ScriptPlanResponse,
    StatementRead,
    StatementResultRead,
    TableRead,
    VerdictRead,
)


def _statement(entry: Any) -> StatementRead:
    return StatementRead(
        index=entry.index,
        sql=entry.sql,
        summary=entry.summary,
        kind=entry.kind.value,
        line=entry.line,
        start=entry.start,
        end=entry.end,
        parameters=list(entry.parameters),
    )


def _policy(policy: Any) -> PolicyRead:
    return PolicyRead(
        allow_writes=policy.allow_writes,
        allow_ddl=policy.allow_ddl,
        environment=policy.environment,
        row_limit=policy.row_limit,
        description=policy.describe(),
    )


def _table(table: Any) -> TableRead:
    return TableRead(
        name=table.name,
        table_schema=table.schema,
        kind=table.kind,
        qualified=table.qualified,
        loaded=table.loaded,
        columns=[
            {
                "name": column.name,
                "type": column.type,
                "nullable": column.nullable,
                "primary_key": column.primary_key,
            }
            for column in table.columns
        ],
    )


def _saved(entry: Any) -> SavedQueryRead:
    return SavedQueryRead(
        id=entry.id,
        project_id=entry.project_id,
        connection_id=entry.connection_id,
        name=entry.name,
        description=entry.description,
        sql=entry.sql,
        parameters=entry.parameters_json or {},
        run_count=entry.run_count,
        last_run_at=entry.last_run_at,
        created_at=entry.created_at,
    )


def _notebook(entry: Any) -> NotebookRead:
    return NotebookRead(
        id=entry.id,
        project_id=entry.project_id,
        connection_id=entry.connection_id,
        name=entry.name,
        description=entry.description,
        created_at=entry.created_at,
        updated_at=entry.updated_at,
        cells=[
            CellRead(
                id=cell.id,
                position=cell.position,
                kind=cell.kind,
                source=cell.source,
                output_name=cell.output_name,
                config=cell.config_json or {},
            )
            for cell in sorted(entry.cells, key=lambda cell: cell.position)
        ],
    )


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
    get_storage_backend: Callable[..., Any] | None = None,
) -> APIRouter:
    router = APIRouter(tags=["workbench"])
    base = "/projects/{project_id}/workbench"

    # --------------------------------------------------- temporal SQL (AS OF)
    # Reads a stored version's artifact, so it exists only when this router was
    # built with a storage backend -- the same rule the datasets router follows.
    if get_storage_backend is not None:

        @router.post(
            "/projects/{project_id}/datasets/{dataset_id}/versions/query",
            response_model=TemporalQueryResponse,
        )
        def query_dataset_version(
            project_id: uuid.UUID,
            dataset_id: uuid.UUID,
            payload: TemporalQueryRequest,
            db: Session = Depends(get_db),
            user: UserRead = Depends(get_current_user),
            storage=Depends(get_storage_backend),
        ) -> TemporalQueryResponse:
            """SQL over a dataset as of a version or an instant. A read (viewer):
            `query` is a read-only segment in the central matrix."""
            return temporal_query(db, project_id, dataset_id, payload, user, storage)

    # ------------------------------------------------------------- analysing

    @router.post(f"{base}/preview", response_model=ScriptPlanResponse)
    def post_preview(
        project_id: uuid.UUID,
        payload: ScriptPlanRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ScriptPlanResponse:
        """Split a script and say what would be allowed. Nothing runs."""
        planned = service.preview_policy(
            db,
            project_id,
            sql=payload.sql,
            allow_writes=payload.allow_writes,
            allow_ddl=payload.allow_ddl,
            user=current_user,
        )
        verdict = planned["verdict"]
        return ScriptPlanResponse(
            statements=[_statement(entry) for entry in planned["statements"]],
            parameters=planned["parameters"],
            policy=_policy(planned["policy"]),
            verdict=VerdictRead(
                allowed=verdict.allowed,
                reason=verdict.reason,
                warnings=verdict.warnings,
                needs_confirmation=verdict.needs_confirmation,
            ),
        )

    @router.post(f"{base}/run", response_model=RunResponse)
    def post_run(
        project_id: uuid.UUID,
        payload: RunRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> RunResponse:
        result, policy = service.run(
            db,
            project_id,
            connection_id=payload.connection_id,
            sql=payload.sql,
            parameters=payload.parameters,
            allow_writes=payload.allow_writes,
            allow_ddl=payload.allow_ddl,
            user=current_user,
            saved_query_id=payload.saved_query_id,
        )
        return RunResponse(
            statements=[
                StatementResultRead(
                    index=entry.index,
                    sql=entry.sql,
                    summary=entry.summary,
                    kind=entry.kind,
                    duration_ms=entry.duration_ms,
                    columns=entry.columns,
                    rows=entry.rows,
                    row_count=entry.row_count,
                    truncated=entry.truncated,
                    rows_affected=entry.rows_affected,
                    error=entry.error,
                    skipped=entry.skipped,
                )
                for entry in result.statements
            ],
            duration_ms=result.duration_ms,
            committed=result.committed,
            warnings=result.warnings,
            policy=policy.describe(),
        )

    @router.post(f"{base}/explain", response_model=ExplainResponse)
    def post_explain(
        project_id: uuid.UUID,
        payload: ExplainRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ExplainResponse:
        plan = service.explain(
            db,
            project_id,
            connection_id=payload.connection_id,
            sql=payload.sql,
            parameters=payload.parameters,
            user=current_user,
        )
        return ExplainResponse(
            dialect=plan.dialect,
            text=plan.text,
            rows=plan.rows,
            estimated_cost=plan.estimated_cost,
            estimated_rows=plan.estimated_rows,
            notes=plan.notes,
        )

    # ----------------------------------------------------------------- schema

    @router.get(f"{base}/schema/{{connection_id}}", response_model=SchemaResponse)
    def get_schema(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        table: str | None = Query(default=None, max_length=300),
        refresh: bool = Query(default=False),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SchemaResponse:
        """The live schema. `table` loads that one's columns."""
        found = service.browse(
            db, project_id, connection_id, current_user, table=table, refresh=refresh
        )
        return SchemaResponse(
            dialect=found.dialect,
            default_schema=found.default_schema,
            tables=[_table(entry) for entry in found.tables],
            truncated=found.truncated,
        )

    @router.post(f"{base}/completions/{{connection_id}}", response_model=CompletionResponse)
    def post_completions(
        project_id: uuid.UUID,
        connection_id: uuid.UUID,
        payload: CompletionRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> CompletionResponse:
        """Suggestions for a cursor position. A POST because the script is the input."""
        items = service.completions(
            db,
            project_id,
            connection_id,
            current_user,
            sql=payload.sql,
            offset=payload.offset,
            limit=payload.limit,
        )
        return CompletionResponse(
            items=[
                CompletionRead(
                    label=entry.label, kind=entry.kind, detail=entry.detail, insert=entry.insert
                )
                for entry in items
            ]
        )

    # ---------------------------------------------------------- saved queries

    @router.get(f"{base}/queries", response_model=SavedQueryListResponse)
    def get_queries(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SavedQueryListResponse:
        return SavedQueryListResponse(
            items=[_saved(entry) for entry in service.list_saved(db, project_id, current_user)]
        )

    @router.post(
        f"{base}/queries", response_model=SavedQueryRead, status_code=status.HTTP_201_CREATED
    )
    def post_query(
        project_id: uuid.UUID,
        payload: SavedQueryCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SavedQueryRead:
        return _saved(
            service.save(
                db,
                project_id,
                current_user,
                name=payload.name,
                sql=payload.sql,
                description=payload.description,
                connection_id=payload.connection_id,
                parameters=payload.parameters,
            )
        )

    @router.patch(f"{base}/queries/{{saved_id}}", response_model=SavedQueryRead)
    def patch_query(
        project_id: uuid.UUID,
        saved_id: uuid.UUID,
        payload: SavedQueryUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SavedQueryRead:
        return _saved(
            service.update_saved(
                db, project_id, saved_id, current_user, **payload.model_dump(exclude_unset=True)
            )
        )

    @router.delete(f"{base}/queries/{{saved_id}}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_query(
        project_id: uuid.UUID,
        saved_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        service.delete_saved(db, project_id, saved_id, current_user)

    @router.get(f"{base}/history", response_model=QueryRunListResponse)
    def get_history(
        project_id: uuid.UUID,
        limit: int = Query(default=50, ge=1, le=500),
        mine_only: bool = Query(default=False),
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> QueryRunListResponse:
        """What was run, and how it went. Never what it returned."""
        return QueryRunListResponse(
            items=[
                QueryRunRead(
                    id=entry.id,
                    sql=entry.sql,
                    statement_count=entry.statement_count,
                    wrote=entry.wrote,
                    succeeded=entry.succeeded,
                    duration_ms=entry.duration_ms,
                    rows_returned=entry.rows_returned,
                    rows_affected=entry.rows_affected,
                    error=entry.error,
                    created_at=entry.created_at,
                )
                for entry in service.history(
                    db, project_id, current_user, limit=limit, mine_only=mine_only
                )
            ]
        )

    # -------------------------------------------------------------- notebooks

    @router.get(f"{base}/notebooks", response_model=NotebookListResponse)
    def get_notebooks(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> NotebookListResponse:
        return NotebookListResponse(
            items=[_notebook(entry) for entry in service.list_notebooks(db, project_id, current_user)]
        )

    @router.post(
        f"{base}/notebooks", response_model=NotebookRead, status_code=status.HTTP_201_CREATED
    )
    def post_notebook(
        project_id: uuid.UUID,
        payload: NotebookCreate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> NotebookRead:
        return _notebook(
            service.create_notebook(
                db,
                project_id,
                current_user,
                name=payload.name,
                description=payload.description,
                connection_id=payload.connection_id,
                cells=[cell.model_dump() for cell in payload.cells],
            )
        )

    @router.get(f"{base}/notebooks/{{notebook_id}}", response_model=NotebookRead)
    def get_one_notebook(
        project_id: uuid.UUID,
        notebook_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> NotebookRead:
        return _notebook(service.get_notebook(db, project_id, notebook_id, current_user))

    @router.patch(f"{base}/notebooks/{{notebook_id}}", response_model=NotebookRead)
    def patch_notebook(
        project_id: uuid.UUID,
        notebook_id: uuid.UUID,
        payload: NotebookUpdate,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> NotebookRead:
        changes = payload.model_dump(exclude_unset=True)
        if "cells" in changes and changes["cells"] is not None:
            changes["cells"] = [dict(cell) for cell in changes["cells"]]
        return _notebook(
            service.update_notebook(db, project_id, notebook_id, current_user, **changes)
        )

    @router.delete(
        f"{base}/notebooks/{{notebook_id}}", status_code=status.HTTP_204_NO_CONTENT
    )
    def delete_one_notebook(
        project_id: uuid.UUID,
        notebook_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> None:
        service.delete_notebook(db, project_id, notebook_id, current_user)

    @router.post(
        f"{base}/notebooks/{{notebook_id}}/run", response_model=NotebookRunResponse
    )
    def post_notebook_run(
        project_id: uuid.UUID,
        notebook_id: uuid.UUID,
        payload: NotebookRunRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> NotebookRunResponse:
        result = service.run_notebook_for(
            db,
            project_id,
            notebook_id,
            current_user,
            allow_writes=payload.allow_writes,
            only_to=payload.only_to,
        )
        return NotebookRunResponse(
            cells=[
                CellResultRead(
                    position=cell.position,
                    kind=cell.kind,
                    ok=cell.ok,
                    duration_ms=cell.duration_ms,
                    output_name=cell.output_name,
                    columns=cell.columns,
                    rows=cell.rows,
                    row_count=cell.row_count,
                    truncated=cell.truncated,
                    stdout=cell.stdout,
                    error=cell.error,
                    skipped=cell.skipped,
                    bindings=cell.bindings,
                )
                for cell in result.cells
            ],
            duration_ms=result.duration_ms,
        )

    # ------------------------------------------------------ platform surfaces

    @router.get("/workbench/sandbox", response_model=SandboxStatusResponse)
    def get_sandbox(
        current_user: UserRead = Depends(get_current_user),
    ) -> SandboxStatusResponse:
        """What this deployment can enforce, and what it therefore refuses.

        Not project-scoped: the answer is a property of the machine the gateway
        runs on, and the editor needs it before a project is even chosen.
        """
        return SandboxStatusResponse(**service.sandbox_status())

    @router.post("/workbench/recipe/yaml", response_model=RecipeYamlResponse)
    def post_recipe_yaml(
        payload: RecipeYamlRequest,
        current_user: UserRead = Depends(get_current_user),
    ) -> RecipeYamlResponse:
        from service_transformations.recipe_yaml import to_yaml

        return RecipeYamlResponse(
            yaml=to_yaml(
                payload.steps,
                name=payload.name,
                description=payload.description,
                dataset=payload.dataset,
            )
        )

    @router.post("/workbench/recipe/parse", response_model=RecipeParseResponse)
    def post_recipe_parse(
        payload: RecipeParseRequest,
        current_user: UserRead = Depends(get_current_user),
    ) -> RecipeParseResponse:
        from service_transformations.recipe_yaml import from_yaml

        return RecipeParseResponse(**from_yaml(payload.yaml))

    return router
