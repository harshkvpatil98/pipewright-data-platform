from __future__ import annotations

from service_datasets.schemas import DatasetAuditSummary
from shared_python.reporting.audit_report_html import (
    render_dataset_audit_report_html,
    sanitize_audit_filename_component,
)


def render_dataset_audit_html(summary: DatasetAuditSummary) -> str:
    """HTML document from the typed dataset audit summary (no duplicate assembly logic)."""
    return render_dataset_audit_report_html(summary.model_dump(mode="json"))


def build_dataset_audit_export_filename(summary: DatasetAuditSummary) -> str:
    base = sanitize_audit_filename_component(summary.name, fallback=str(summary.id))
    return f"dataset-audit-{base}.html"
