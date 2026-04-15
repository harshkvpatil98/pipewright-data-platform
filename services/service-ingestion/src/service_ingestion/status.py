from shared_python.status import ServiceStatus


def get_service_status(_db) -> ServiceStatus:
    return ServiceStatus(
        name="service-ingestion",
        status="healthy",
        details={"supported_extensions": ["csv", "xlsx", "json"]},
    )
