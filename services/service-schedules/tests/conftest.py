"""Register ORM modules for SQLAlchemy mapper configuration in tests."""

from __future__ import annotations


def pytest_configure() -> None:
    import service_destinations.models  # noqa: F401
    import service_datasets.models  # noqa: F401
    import service_pipeline_runs.models  # noqa: F401
    import service_schedules.models  # noqa: F401
    import service_transformations.models  # noqa: F401
