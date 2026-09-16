from shared_python.db import Base

# Import models here so Alembic sees a single metadata graph while service code stays modular.
from service_access.models import ProjectMembership  # noqa: F401
from service_auth.models import User, UserPreference  # noqa: F401
from service_enterprise.models import (  # noqa: F401
    ErasureRequest,
    Organisation,
    RetentionPolicy,
    SecurityPolicy,
    UsageRecord,
)
from service_comparisons.models import SavedStatisticalTest, SavedStatisticalTestRun  # noqa: F401
from service_datasets.models import Dataset  # noqa: F401
from service_destinations.models import DestinationConfig  # noqa: F401
from service_extraction.models import ExtractionConnection, ExtractionJob  # noqa: F401
from service_writeback.models import ChangeSet, ChangeSetEdit  # noqa: F401
from service_governance.models import (  # noqa: F401
    AuditEntry,
    ChangeRequest,
    Comment,
    ResourceVersion,
)
from service_pipeline_runs.models import PipelineRun  # noqa: F401
from service_projects.models import Project  # noqa: F401
from service_quality.models import (  # noqa: F401
    DataQualityRule,
    DataQualityRunResult,
    SchemaDriftEvent,
)
from service_observability.models import (  # noqa: F401
    DatasetMetric,
    FreshnessPolicy,
    Incident,
    IncidentEvent,
)
from service_reporting.models import (  # noqa: F401
    CatalogAnnotation,
    Dashboard,
    DashboardTile,
    GlossaryTerm,
    ReportDelivery,
    SavedChart,
    ScheduledReport,
)
from service_sources.models import Source  # noqa: F401
from service_schedules.models import ScheduledOperation  # noqa: F401
from service_transformations.models import TransformationPipeline  # noqa: F401
from service_workflows.models import (  # noqa: F401
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
)
from service_notifications.models import ExternalNotificationTarget, UserNotification  # noqa: F401
from service_workbench.models import (  # noqa: F401
    Notebook,
    NotebookCell,
    QueryRun,
    SavedQuery,
)
from service_connectors.models import ConnectorSchemaSnapshot  # noqa: F401
from service_ingestion.models import IngestSpecRecord  # noqa: F401

# Imported for the side effect: this teaches governance how to snapshot and
# restore a workflow, which is what makes version history restorable.
import service_workflows.versioning  # noqa: F401,E402

__all__ = ["Base"]
