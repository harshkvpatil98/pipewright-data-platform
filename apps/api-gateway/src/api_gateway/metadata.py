from shared_python.db import Base

# Import models here so Alembic sees a single metadata graph while service code stays modular.
from service_auth.models import User  # noqa: F401
from service_comparisons.models import SavedStatisticalTest, SavedStatisticalTestRun  # noqa: F401
from service_datasets.models import Dataset  # noqa: F401
from service_destinations.models import DestinationConfig  # noqa: F401
from service_pipeline_runs.models import PipelineRun  # noqa: F401
from service_projects.models import Project  # noqa: F401
from service_sources.models import Source  # noqa: F401
from service_schedules.models import ScheduledOperation  # noqa: F401
from service_transformations.models import TransformationPipeline  # noqa: F401
from service_notifications.models import ExternalNotificationTarget, UserNotification  # noqa: F401

__all__ = ["Base"]
