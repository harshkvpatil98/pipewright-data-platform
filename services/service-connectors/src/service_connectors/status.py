from sqlalchemy.orm import Session

from shared_python.status import ServiceStatus

from service_connectors import adapters  # noqa: F401
from service_connectors.registry import specs


def get_service_status(_db: Session) -> ServiceStatus:
    """The catalogue holds no state; its health is what it can reach."""
    catalogue = specs()
    available = [spec for spec in catalogue if spec.available]
    missing = sorted({spec.driver_package for spec in catalogue if not spec.available and spec.driver_package})

    return ServiceStatus(
        name="service-connectors",
        status="healthy",
        details={
            "connectors": len(catalogue),
            "available": len(available),
            "writable": len([spec for spec in available if spec.supports("write")]),
            "drivers_not_installed": missing,
        },
    )
