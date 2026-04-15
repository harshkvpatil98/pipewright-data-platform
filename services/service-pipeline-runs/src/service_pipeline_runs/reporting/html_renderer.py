from __future__ import annotations

from service_pipeline_runs.schemas import RunAuditSummary
from shared_python.reporting.audit_report_html import (
    render_run_audit_report_html,
    sanitize_audit_filename_component,
)


def render_run_audit_html(summary: RunAuditSummary) -> str:
    """HTML document from the typed run audit summary (no duplicate assembly logic)."""
    return render_run_audit_report_html(summary.model_dump(mode="json"))


def build_run_audit_export_filename(summary: RunAuditSummary) -> str:
    base = sanitize_audit_filename_component(str(summary.id), fallback="run")
    return f"run-audit-{base}.html"
