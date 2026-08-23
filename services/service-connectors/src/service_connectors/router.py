from __future__ import annotations

from collections.abc import Callable

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from service_auth.schemas import UserRead

from service_connectors import adapters  # noqa: F401  - registers the catalogue
from service_connectors.conformance import check_spec
from service_connectors.formats import COMPRESSIONS, FORMATS
from service_connectors.protocol import CATEGORIES
from service_connectors.registry import get, specs, validate_config
from service_connectors.schemas import (
    ConformanceResponse,
    ConnectorCatalogResponse,
    ConnectorSpecRead,
    ConnectorTestRequest,
    ConnectorTestResponse,
    FormatCatalogResponse,
    FormatRead,
    StreamListResponse,
    StreamRead,
)
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
