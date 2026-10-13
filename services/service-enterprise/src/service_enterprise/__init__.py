"""Tenancy, fine-grained security, retention, cost, and telemetry.

Importing this registers the tenancy boundary with `service_access`, which is
what makes every existing access check organisation-aware. That side effect is
deliberate: a tenancy rule applied at the edges is a tenancy rule with a hole
in it.
"""

from service_enterprise import tenancy
from service_enterprise.router import build_metrics_router, build_router
from service_enterprise.security import Policy, apply_policies
from service_enterprise.status import get_service_status
from service_enterprise.telemetry import collect, render
from service_enterprise.usage import record as record_usage

tenancy.register()


def _register_network_gate() -> None:
    """Organisations' network lists refuse requests from elsewhere (A6, W5)."""
    from service_auth.network_gate import register_network_gate
    from service_enterprise.service import network_gate

    register_network_gate(network_gate)


_register_network_gate()

__all__ = [
    "Policy",
    "apply_policies",
    "build_metrics_router",
    "build_router",
    "collect",
    "get_service_status",
    "record_usage",
    "render",
]
