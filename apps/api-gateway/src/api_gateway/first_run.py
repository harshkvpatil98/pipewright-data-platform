"""The first administrator, on a new installation (adoption-readiness A9).

`AUTH_BOOTSTRAP_USERNAME` and `AUTH_BOOTSTRAP_PASSWORD` were in every example
settings file and in the Helm chart's Secret, and nothing read them: a new
installation by the deployment guide had nobody who could sign in. The
gateway now makes that administrator as it starts, once, while the
installation has no accounts at all; with any account it does nothing, so
the settings can stay without reopening a way in. Two gateways starting
together cannot both make it: the second meets the first's username.
"""

from __future__ import annotations

import os

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from service_auth.models import User
from service_auth.schemas import BootstrapUserRequest
from service_auth.service import create_user
from shared_python.errors import ConflictError
from shared_python.logging import get_logger

logger = get_logger(__name__)


def ensure_first_administrator(db: Session, *, username: str | None, password: str | None) -> str | None:
    """Make the first administrator if there is no account yet. Returns the
    username made, or None when there was nothing to do or it could not."""
    if not (username or "").strip() or not password:
        return None
    if db.scalar(select(func.count()).select_from(User)):
        return None
    try:
        user = create_user(db, BootstrapUserRequest(username=username.strip(), password=password, role="admin"))
    except ValidationError:
        logger.warning(
            "first_administrator_not_made reason=%s",
            "AUTH_BOOTSTRAP_USERNAME needs 3 to 80 characters and AUTH_BOOTSTRAP_PASSWORD 8 to 128",
        )
        return None
    except (ConflictError, IntegrityError):
        db.rollback()
        return None
    logger.info("first_administrator_made username=%s", user.username)
    return user.username


def make_first_administrator(session_factory) -> None:
    """At start-up: best effort, since a database that is not up yet is the
    readiness check's to report, not a reason to stop the gateway."""
    db = session_factory()
    try:
        ensure_first_administrator(
            db,
            username=os.getenv("AUTH_BOOTSTRAP_USERNAME"),
            password=os.getenv("AUTH_BOOTSTRAP_PASSWORD"),
        )
    except Exception:  # noqa: BLE001 - see docstring
        logger.exception("first_administrator_check_failed")
    finally:
        db.close()
