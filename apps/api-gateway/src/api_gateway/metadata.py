from shared_python.db import Base
from shared_python.rate_limit import RateLimitWindow  # noqa: F401

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
    Presence,
    ResourceVersion,
)
from service_pipeline_runs.models import PipelineRun  # noqa: F401
from service_projects.models import Project  # noqa: F401
from service_quality.models import (  # noqa: F401
    DataContract,
    DataContractEvent,
    DataContractFollower,
    DataContractProblem,
    DataContractVersion,
    DataQualityRule,
    DataQualityRunResult,
    SchemaDriftEvent,
)
from service_observability.models import (  # noqa: F401
    DatasetMetric,
    FreshnessPolicy,
    Incident,
    IncidentEvent,
    MetricAlert,
    MetricAlertEvent,
)
from service_reporting.models import (  # noqa: F401
    CatalogAnnotation,
    Dashboard,
    DashboardEmbed,
    DashboardTile,
    GlossaryTerm,
    ReportDelivery,
    SavedChart,
    ScheduledReport,
)
from service_sources.models import Source  # noqa: F401
from service_schedules.models import ScheduledOperation  # noqa: F401
from service_transformations.models import (  # noqa: F401
    RecipeEditBatch,
    RecipeSharedCopy,
    TransformationPipeline,
)
from service_workflows.models import (  # noqa: F401
    Workflow,
    WorkflowEdge,
    WorkflowNode,
    WorkflowNodeRun,
    WorkflowRun,
)
from service_notifications.models import ExternalNotificationTarget, UserNotification, WebhookDelivery  # noqa: F401
from service_workbench.models import (  # noqa: F401
    Notebook,
    NotebookCell,
    QueryRun,
    SavedQuery,
)
from service_connectors.models import ConnectorSchemaSnapshot  # noqa: F401
from service_ingestion.models import IngestSpecRecord  # noqa: F401

# Imported for the side effect: these teach governance how to snapshot and
# restore a workflow and a recipe, which is what makes version history
# restorable and a suggested recipe change appliable (C2).
import service_transformations.versioning  # noqa: F401,E402
import service_workflows.versioning  # noqa: F401,E402

__all__ = ["Base"]
