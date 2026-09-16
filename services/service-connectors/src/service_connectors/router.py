from __future__ import annotations

import uuid
from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_connectors import adapters  # noqa: F401  - registers the catalogue
from service_connectors.conformance import check_spec
from service_connectors.formats import COMPRESSIONS, FORMATS
from service_connectors.protocol import CATEGORIES
from service_connectors.registry import get, specs, validate_config
from service_connectors.health import overview, usage
from service_connectors.schemas import (
    ConformanceResponse,
    SweepRequest,
    SweepResponse,
    WatchStatusResponse,
    WatchedStreamRead,
    ConnectorCatalogResponse,
    ConnectorHealthResponse,
    ConnectorUsageResponse,
    ConnectorSpecRead,
    ConnectorTestRequest,
    ConnectorTestResponse,
    FormatCatalogResponse,
    FormatRead,
    StreamListResponse,
    StreamRead,
)
from service_projects.contracts import ensure_owned_project

from shared_python.errors import BadRequestError


def build_router(
    get_db: Callable[..., Session],
    get_current_user: Callable[..., UserRead],
) -> APIRouter:
    router = APIRouter(tags=["connectors"])

    @router.get("/connectors", response_model=ConnectorCatalogResponse)
    def catalogue(
        _current_user: UserRead = Depends(get_current_user),
    ) -> ConnectorCatalogResponse:
        """Every connector, with the settings each one needs.

        The UI renders its forms from this rather than hard-coding them, which
        is why a new connector needs no frontend change.
        """
        return ConnectorCatalogResponse(
            items=[ConnectorSpecRead(**spec.to_dict()) for spec in specs()],
            categories=list(CATEGORIES),
        )

    @router.get("/connectors/health", response_model=ConnectorHealthResponse)
    def health(
        _current_user: UserRead = Depends(get_current_user),
    ) -> ConnectorHealthResponse:
        """The catalogue's own state.

        With two hundred connectors, "which ones do we have" stops being a list
        somebody reads and becomes a question needing shape: how many work
        here, how many are only declared, and which single package would unlock
        the most. Needs no database, because it describes what this deployment
        *could* reach rather than what it has.
        """
        return ConnectorHealthResponse(**overview().to_dict())

    @router.get("/projects/{project_id}/connectors/usage", response_model=ConnectorUsageResponse)
    def project_usage(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> ConnectorUsageResponse:
        """Which connectors this project actually uses, and how they are faring."""
        ensure_owned_project(db, project_id, current_user.id)
        return ConnectorUsageResponse(
            items=[entry.to_dict() for entry in usage(db, project_id)]
        )

    @router.get(
        "/projects/{project_id}/connectors/watch", response_model=WatchStatusResponse
    )
    def watch_status(
        project_id: uuid.UUID,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> WatchStatusResponse:
        """What the schema watch is remembering, and what it could remember.

        `describable` is the second half on purpose: at two hundred connectors
        "nothing has drifted" is ambiguous between "everything is fine" and
        "nothing is being watched", and those deserve different reactions.
        """
        from service_connectors.sweep import watched_streams
        from service_connectors.watch import describable

        ensure_owned_project(db, project_id, current_user.id)
        return WatchStatusResponse(
            items=[WatchedStreamRead(**row) for row in watched_streams(db, project_id=project_id)],
            describable=describable(),
        )

    @router.post(
        "/projects/{project_id}/connectors/watch", response_model=SweepResponse
    )
    def run_watch(
        project_id: uuid.UUID,
        payload: SweepRequest,
        db: Session = Depends(get_db),
        current_user: UserRead = Depends(get_current_user),
    ) -> SweepResponse:
        """Re-read every watchable stream now.

        The same call the nightly schedule makes. `apply: false` compares and
        records nothing, because the first sweep of a busy project can open a
        lot of incidents and somebody should be able to look first.
        """
        from service_connectors.sweep import sweep_project

        ensure_owned_project(db, project_id, current_user.id)
        report = sweep_project(
            db,
            project_id=project_id,
            connection_id=payload.connection_id,
            open_incidents=payload.apply,
        )
        if payload.apply:
            db.commit()
        else:
            db.rollback()
        return SweepResponse(**report.to_dict())

    @router.get("/connectors/formats", response_model=FormatCatalogResponse)
    def formats(
        _current_user: UserRead = Depends(get_current_user),
    ) -> FormatCatalogResponse:
        return FormatCatalogResponse(
            items=[FormatRead(**spec.to_dict()) for spec in FORMATS],
            compressions=list(COMPRESSIONS),
        )

    @router.get("/connectors/{connector_type}", response_model=ConnectorSpecRead)
    def one(
        connector_type: str,
        _current_user: UserRead = Depends(get_current_user),
    ) -> ConnectorSpecRead:
        return ConnectorSpecRead(**get(connector_type).spec.to_dict())

    @router.get("/connectors/{connector_type}/conformance", response_model=ConformanceResponse)
    def conformance(
        connector_type: str,
        _current_user: UserRead = Depends(get_current_user),
    ) -> ConformanceResponse:
        """What this connector promises, and whether it keeps its promises.

        Exposed rather than kept in the test suite so a deployment can check its
        own connectors, including any added locally.
        """
        return ConformanceResponse(**check_spec(get(connector_type)).to_dict())

    @router.post("/connectors/test", response_model=ConnectorTestResponse)
    def test_connection(
        payload: ConnectorTestRequest,
        _current_user: UserRead = Depends(get_current_user),
    ) -> ConnectorTestResponse:
        connector = get(payload.connector_type)
        config = validate_config(payload.connector_type, payload.config)
        if not connector.spec.supports("test"):
            raise BadRequestError(f"{connector.spec.label} cannot be tested.")
        return ConnectorTestResponse(**connector.test(config).to_dict())

    @router.post("/connectors/{connector_type}/streams", response_model=StreamListResponse)
    def discover(
        connector_type: str,
        payload: ConnectorTestRequest,
        _current_user: UserRead = Depends(get_current_user),
    ) -> StreamListResponse:
        """What is available to read, asked of the source itself."""
        connector = get(connector_type)
        if not connector.spec.supports("discover"):
            raise BadRequestError(
                f"{connector.spec.label} cannot list what it holds; name the stream directly."
            )
        config = validate_config(connector_type, payload.config)
        return StreamListResponse(
            connector_type=connector_type,
            items=[
                StreamRead(**stream.to_dict())
                for stream in connector.discover(config)  # type: ignore[attr-defined]
            ],
        )

    return router
