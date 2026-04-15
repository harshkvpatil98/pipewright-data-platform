"""Register related ORM modules so SQLAlchemy can configure mappers when tests build SavedStatisticalTest rows."""

from __future__ import annotations


def pytest_configure() -> None:
    import service_pipeline_runs.models  # noqa: F401
    import service_transformations.models  # noqa: F401
