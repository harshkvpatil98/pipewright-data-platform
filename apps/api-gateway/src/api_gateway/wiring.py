"""Cross-service wiring that would otherwise be a circular import.

Services register capabilities with each other through resolver hooks rather
than importing each other. The gateway is the one place that knows about all of
them, so the hooks are installed here.
"""

from __future__ import annotations

import uuid

from sqlalchemy import Engine
from sqlalchemy.orm import Session

from shared_python.errors import BadRequestError, NotFoundError
from shared_python.logging import get_logger
from shared_python.security.config_crypto import decrypt_sensitive_fields

logger = get_logger(__name__)


def _writeback_engine(db: Session, project_id: uuid.UUID, connection_id: uuid.UUID) -> Engine:
    """Turn a saved extraction connection into a live engine.

    Scoped to the project on purpose: a change set carries a connection id, and
    without this check one project could name another project's connection.
    """
    from service_extraction.connectors.sql_database import get_engine
    from service_extraction.models import ExtractionConnection
    from service_extraction.connectors.base import SENSITIVE_CONFIG_FIELDS

    connection = db.get(ExtractionConnection, connection_id)
    if connection is None or connection.project_id != project_id:
        raise NotFoundError("That database connection does not exist in this project.")
    if connection.status != "active":
        raise BadRequestError(
            f"Connection {connection.name!r} is {connection.status}, so it cannot be written to."
        )
    config = decrypt_sensitive_fields(dict(connection.config_json or {}), SENSITIVE_CONFIG_FIELDS)
    return get_engine(connection.connector_type, config)


def install_secret_providers() -> list[str]:
    """Wire up the managed secret stores whose SDKs are installed.

    A connector config field can hold a value or a reference --
    `vault://database/prod#password`. The `env` and `file` providers need
    nothing and are always there; the managed ones register only when their SDK
    is present, so a reference to one that is missing fails loudly rather than
    falling back to something else. See `shared_python.security.vault`.
    """
    from shared_python.security.vault import install_managed_providers

    installed = install_managed_providers()
    if installed:
        logger.info("secret_providers_installed", extra={"providers": installed})
    return installed


def install_resolvers() -> None:
    """Idempotent: safe to call once per application, and in tests."""
    from service_workbench import register_engine_resolver as register_workbench_engine
    from service_writeback import register_engine_resolver as register_writeback_engine

    # Both want the same thing -- a live engine for a saved connection, scoped
    # to the project -- so they share one resolver rather than two that drift.
    register_writeback_engine(_writeback_engine)
    register_workbench_engine(_writeback_engine)
    install_secret_providers()
