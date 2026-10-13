"""The hook that lets an organisation's network list refuse a request (A6, W5).

Authentication lives below organisations, so it cannot ask them directly:
the enterprise service registers a gate at import, the same way tenancy
registers its project resolver. With no gate registered (a single-tenant
install), every address is allowed.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

Gate = Callable[[Session, Any, str], None]

_gate: Gate | None = None


def register_network_gate(gate: Gate | None) -> None:
    """Install the function that raises ForbiddenError for a refused address."""
    global _gate
    _gate = gate


def check_network(db: Session, user: Any, address: str) -> None:
    """Refuse the request when the user's organisation does not allow this address."""
    if _gate is not None:
        _gate(db, user, address)
