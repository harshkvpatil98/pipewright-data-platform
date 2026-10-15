"""Every Pipewright API operation as a method. Generated; do not edit.

Made by `scripts/generate-client.py` from the gateway's OpenAPI document.
Each method calls `self._call`, which `pipewright.Client` provides.
"""

# ruff: noqa: E501

from __future__ import annotations

from typing import Any


class Operations:
    def _call(self, method: str, path: str, **kwargs: Any) -> Any:  # pragma: no cover - Client overrides
        raise NotImplementedError

    def read_roles(self) -> Any:
        """Read Roles

        GET /api/v1/access/roles
        """
        return self._call("GET", "/api/v1/access/roles")

    def audits(self, *, outcome: str | None = None, actor: str | None = None, method: str | None = None, q: str | None = None, project_id: str | None = None, since_days: int | None = None, limit: int | None = None) -> Any:
        """Audits

        GET /api/v1/audits
        """
        return self._call("GET", "/api/v1/audits", query={"outcome": outcome, "actor": actor, "method": method, "q": q, "project_id": project_id, "since_days": since_days, "limit": limit})

    def audits_export(self, *, format: str | None = None, outcome: str | None = None, actor: str | None = None, method: str | None = None, q: str | None = None, project_id: str | None = None, since_days: int | None = None) -> Any:
        """Audits Export

        GET /api/v1/audits/export
        """
        return self._call("GET", "/api/v1/audits/export", query={"format": format, "outcome": outcome, "actor": actor, "method": method, "q": q, "project_id": project_id, "since_days": since_days})

    def invite(self, *, body: Any) -> Any:
        """Create an inactive account and a one-time activation code.

        POST /api/v1/auth/invite
        """
        return self._call("POST", "/api/v1/auth/invite", body=body)

    def login(self, *, body: Any) -> Any:
        """Login

        POST /api/v1/auth/login
        """
        return self._call("POST", "/api/v1/auth/login", body=body)

    def login_mfa(self, *, body: Any) -> Any:
        """Second step: exchange the ticket plus a TOTP or recovery code for a session. The ticket proves the password already passed.

        POST /api/v1/auth/login/mfa
        """
        return self._call("POST", "/api/v1/auth/login/mfa", body=body)

    def me(self) -> Any:
        """Me

        GET /api/v1/auth/me
        """
        return self._call("GET", "/api/v1/auth/me")

    def edit_profile(self, *, body: Any) -> Any:
        """Edit Profile

        PATCH /api/v1/auth/me
        """
        return self._call("PATCH", "/api/v1/auth/me", body=body)

    def mfa_status(self) -> Any:
        """Mfa Status

        GET /api/v1/auth/me/mfa
        """
        return self._call("GET", "/api/v1/auth/me/mfa")

    def mfa_activate(self, *, body: Any) -> Any:
        """Mfa Activate

        POST /api/v1/auth/me/mfa/activate
        """
        return self._call("POST", "/api/v1/auth/me/mfa/activate", body=body)

    def mfa_disable(self, *, body: Any) -> Any:
        """Mfa Disable

        POST /api/v1/auth/me/mfa/disable
        """
        return self._call("POST", "/api/v1/auth/me/mfa/disable", body=body)

    def mfa_enroll(self) -> Any:
        """Mfa Enroll

        POST /api/v1/auth/me/mfa/enroll
        """
        return self._call("POST", "/api/v1/auth/me/mfa/enroll")

    def mfa_regenerate_recovery(self, *, body: Any) -> Any:
        """Mfa Regenerate Recovery

        POST /api/v1/auth/me/mfa/recovery-codes
        """
        return self._call("POST", "/api/v1/auth/me/mfa/recovery-codes", body=body)

    def change_own_password(self, *, body: Any) -> Any:
        """Change Own Password

        PATCH /api/v1/auth/me/password
        """
        return self._call("PATCH", "/api/v1/auth/me/password", body=body)

    def read_preferences(self) -> Any:
        """Read Preferences

        GET /api/v1/auth/me/preferences
        """
        return self._call("GET", "/api/v1/auth/me/preferences")

    def update_preferences(self, *, body: Any) -> Any:
        """Update Preferences

        PATCH /api/v1/auth/me/preferences
        """
        return self._call("PATCH", "/api/v1/auth/me/preferences", body=body)

    def sign_out_all(self) -> Any:
        """Sign Out All

        POST /api/v1/auth/me/sign-out-everywhere
        """
        return self._call("POST", "/api/v1/auth/me/sign-out-everywhere")

    def protected_example(self) -> Any:
        """Protected Example

        GET /api/v1/auth/protected
        """
        return self._call("GET", "/api/v1/auth/protected")

    def redeem_code_route(self, *, body: Any) -> Any:
        """Set a password from a one-time activation or reset code, then sign in.

        POST /api/v1/auth/redeem-code
        """
        return self._call("POST", "/api/v1/auth/redeem-code", body=body)

    def session_policy(self) -> Any:
        """How long a session lasts here, and the address this request came from (A6, W5).

        GET /api/v1/auth/session-policy
        """
        return self._call("GET", "/api/v1/auth/session-policy")

    def renew_session(self) -> Any:
        """A fresh sign-in token for a session that is still valid and in use.

        POST /api/v1/auth/session/renew
        """
        return self._call("POST", "/api/v1/auth/session/renew")

    def sso_callback(self, *, code: str | None = None, state: str | None = None, error: str | None = None) -> Any:
        """Sso Callback

        GET /api/v1/auth/sso/callback
        """
        return self._call("GET", "/api/v1/auth/sso/callback", query={"code": code, "state": state, "error": error})

    def sso_start(self, *, next: str | None = None) -> Any:
        """Sso Start

        GET /api/v1/auth/sso/start
        """
        return self._call("GET", "/api/v1/auth/sso/start", query={"next": next})

    def sso_status(self) -> Any:
        """Whether SSO is available, and the plain truth about SAML.

        GET /api/v1/auth/sso/status
        """
        return self._call("GET", "/api/v1/auth/sso/status")

    def list_tokens(self) -> Any:
        """List Tokens

        GET /api/v1/auth/tokens
        """
        return self._call("GET", "/api/v1/auth/tokens")

    def create_token(self, *, body: Any) -> Any:
        """Create Token

        POST /api/v1/auth/tokens
        """
        return self._call("POST", "/api/v1/auth/tokens", body=body)

    def revoke_token(self, token_id: str) -> Any:
        """Revoke Token

        DELETE /api/v1/auth/tokens/{token_id}
        """
        return self._call("DELETE", f"/api/v1/auth/tokens/{token_id}")

    def read_users(self) -> Any:
        """Everyone with an account. Readable by any signed-in user, because inviting a colleague to a project means typing their username.

        GET /api/v1/auth/users
        """
        return self._call("GET", "/api/v1/auth/users")

    def add_user(self, *, body: Any) -> Any:
        """Add User

        POST /api/v1/auth/users
        """
        return self._call("POST", "/api/v1/auth/users", body=body)

    def change_user(self, user_id: str, *, body: Any) -> Any:
        """Change User

        PATCH /api/v1/auth/users/{user_id}
        """
        return self._call("PATCH", f"/api/v1/auth/users/{user_id}", body=body)

    def remove_user(self, user_id: str) -> Any:
        """Remove User

        DELETE /api/v1/auth/users/{user_id}
        """
        return self._call("DELETE", f"/api/v1/auth/users/{user_id}")

    def reset_user_mfa(self, user_id: str) -> Any:
        """Clear a locked-out person's second factor so they can sign in with their password and re-enrol. An admin action, distinct from self-disable so the audit trail records who did it.

        POST /api/v1/auth/users/{user_id}/mfa/reset
        """
        return self._call("POST", f"/api/v1/auth/users/{user_id}/mfa/reset")

    def issue_reset_code(self, user_id: str) -> Any:
        """Give an admin a one-time code to hand a locked-out colleague.

        POST /api/v1/auth/users/{user_id}/reset-code
        """
        return self._call("POST", f"/api/v1/auth/users/{user_id}/reset-code")

    def types(self) -> Any:
        """Types

        GET /api/v1/charts/types
        """
        return self._call("GET", "/api/v1/charts/types")

    def catalogue(self) -> Any:
        """Every connector, with the settings each one needs.

        GET /api/v1/connectors
        """
        return self._call("GET", "/api/v1/connectors")

    def formats(self) -> Any:
        """Formats

        GET /api/v1/connectors/formats
        """
        return self._call("GET", "/api/v1/connectors/formats")

    def health(self) -> Any:
        """The catalogue's own state.

        GET /api/v1/connectors/health
        """
        return self._call("GET", "/api/v1/connectors/health")

    def test_connection(self, *, body: Any) -> Any:
        """Test Connection

        POST /api/v1/connectors/test
        """
        return self._call("POST", "/api/v1/connectors/test", body=body)

    def one(self, connector_type: str) -> Any:
        """One

        GET /api/v1/connectors/{connector_type}
        """
        return self._call("GET", f"/api/v1/connectors/{connector_type}")

    def conformance(self, connector_type: str) -> Any:
        """What this connector promises, and whether it keeps its promises.

        GET /api/v1/connectors/{connector_type}/conformance
        """
        return self._call("GET", f"/api/v1/connectors/{connector_type}/conformance")

    def discover(self, connector_type: str, *, body: Any) -> Any:
        """What is available to read, asked of the source itself.

        POST /api/v1/connectors/{connector_type}/streams
        """
        return self._call("POST", f"/api/v1/connectors/{connector_type}/streams", body=body)

    def get_rule_catalog(self) -> Any:
        """Describe every supported rule type and its configuration keys.

        GET /api/v1/data-quality/rule-types
        """
        return self._call("GET", "/api/v1/data-quality/rule-types")

    def dataset_search(self, *, q: str | None = None, limit: int | None = None) -> Any:
        """Dataset Search

        GET /api/v1/datasets
        """
        return self._call("GET", "/api/v1/datasets", query={"q": q, "limit": limit})

    def live(self) -> Any:
        """Live

        GET /api/v1/health/live
        """
        return self._call("GET", "/api/v1/health/live")

    def ready(self) -> Any:
        """Ready

        GET /api/v1/health/ready
        """
        return self._call("GET", "/api/v1/health/ready")

    def receive(self, token: str) -> Any:
        """Receive

        POST /api/v1/hooks/{token}
        """
        return self._call("POST", f"/api/v1/hooks/{token}")

    def get_my_notifications(self, *, limit: int | None = None) -> Any:
        """Get My Notifications

        GET /api/v1/notifications
        """
        return self._call("GET", "/api/v1/notifications", query={"limit": limit})

    def get_notification_preferences(self) -> Any:
        """Get Notification Preferences

        GET /api/v1/notifications/preferences
        """
        return self._call("GET", "/api/v1/notifications/preferences")

    def put_notification_preference(self, *, body: Any) -> Any:
        """Change how one kind of notification arrives, for the signed-in person only.

        PUT /api/v1/notifications/preferences
        """
        return self._call("PUT", "/api/v1/notifications/preferences", body=body)

    def patch_notifications_read_all(self) -> Any:
        """Patch Notifications Read All

        PATCH /api/v1/notifications/read-all
        """
        return self._call("PATCH", "/api/v1/notifications/read-all")

    def patch_notification_read(self, notification_id: str) -> Any:
        """Patch Notification Read

        PATCH /api/v1/notifications/{notification_id}/read
        """
        return self._call("PATCH", f"/api/v1/notifications/{notification_id}/read")

    def read_organisations(self) -> Any:
        """Read Organisations

        GET /api/v1/organisations
        """
        return self._call("GET", "/api/v1/organisations")

    def add_organisation(self, *, body: Any) -> Any:
        """Add Organisation

        POST /api/v1/organisations
        """
        return self._call("POST", "/api/v1/organisations", body=body)

    def read_limits(self) -> Any:
        """Read Limits

        GET /api/v1/organisations/limits
        """
        return self._call("GET", "/api/v1/organisations/limits")

    def edit_organisation(self, organisation_id: str, *, body: Any) -> Any:
        """Edit Organisation

        PATCH /api/v1/organisations/{organisation_id}
        """
        return self._call("PATCH", f"/api/v1/organisations/{organisation_id}", body=body)

    def remove_organisation(self, organisation_id: str) -> Any:
        """Remove Organisation

        DELETE /api/v1/organisations/{organisation_id}
        """
        return self._call("DELETE", f"/api/v1/organisations/{organisation_id}")

    def add_project(self, organisation_id: str, project_id: str) -> Any:
        """Add Project

        POST /api/v1/organisations/{organisation_id}/projects/{project_id}
        """
        return self._call("POST", f"/api/v1/organisations/{organisation_id}/projects/{project_id}")

    def remove_project(self, organisation_id: str, project_id: str) -> Any:
        """Remove Project

        DELETE /api/v1/organisations/{organisation_id}/projects/{project_id}
        """
        return self._call("DELETE", f"/api/v1/organisations/{organisation_id}/projects/{project_id}")

    def add_member(self, organisation_id: str, user_id: str) -> Any:
        """Add Member

        POST /api/v1/organisations/{organisation_id}/users/{user_id}
        """
        return self._call("POST", f"/api/v1/organisations/{organisation_id}/users/{user_id}")

    def remove_member(self, organisation_id: str, user_id: str) -> Any:
        """Revoke somebody's membership of a tenant.

        DELETE /api/v1/organisations/{organisation_id}/users/{user_id}
        """
        return self._call("DELETE", f"/api/v1/organisations/{organisation_id}/users/{user_id}")

    def get_projects(self) -> Any:
        """Get Projects

        GET /api/v1/projects
        """
        return self._call("GET", "/api/v1/projects")

    def post_project(self, *, body: Any) -> Any:
        """Post Project

        POST /api/v1/projects
        """
        return self._call("POST", "/api/v1/projects", body=body)

    def create_demo(self) -> Any:
        """Create Demo

        POST /api/v1/projects/demo
        """
        return self._call("POST", "/api/v1/projects/demo")

    def get_project(self, project_id: str) -> Any:
        """Get Project

        GET /api/v1/projects/{project_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}")

    def patch_project(self, project_id: str, *, body: Any) -> Any:
        """Patch Project

        PATCH /api/v1/projects/{project_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}", body=body)

    def delete_project(self, project_id: str) -> Any:
        """Delete Project

        DELETE /api/v1/projects/{project_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}")

    def read_project_activity(self, project_id: str, *, kind: list[Any] | None = None, offset: int | None = None, limit: int | None = None) -> Any:
        """What happened in the project, newest first: changes, runs, incidents, comments and alerts, with who and when. Repeat `kind` to choose several.

        GET /api/v1/projects/{project_id}/activity
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/activity", query={"kind": kind, "offset": offset, "limit": limit})

    def read_audit(self, project_id: str, *, outcome: str | None = None, limit: int | None = None) -> Any:
        """Read Audit

        GET /api/v1/projects/{project_id}/audit-log
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/audit-log", query={"outcome": outcome, "limit": limit})

    def get_project_bi_connections(self, project_id: str) -> Any:
        """Get Project Bi Connections

        GET /api/v1/projects/{project_id}/bi-connections
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/bi-connections")

    def post_project_bi_connection(self, project_id: str, *, body: Any) -> Any:
        """Post Project Bi Connection

        POST /api/v1/projects/{project_id}/bi-connections
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/bi-connections", body=body)

    def get_project_bi_connection(self, project_id: str, connection_id: str) -> Any:
        """Get Project Bi Connection

        GET /api/v1/projects/{project_id}/bi-connections/{connection_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/bi-connections/{connection_id}")

    def patch_project_bi_connection(self, project_id: str, connection_id: str, *, body: Any) -> Any:
        """Patch Project Bi Connection

        PATCH /api/v1/projects/{project_id}/bi-connections/{connection_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/bi-connections/{connection_id}", body=body)

    def remove_project_bi_connection(self, project_id: str, connection_id: str) -> Any:
        """Remove Project Bi Connection

        DELETE /api/v1/projects/{project_id}/bi-connections/{connection_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/bi-connections/{connection_id}")

    def get_project_bi_connection_metadata(self, project_id: str, connection_id: str) -> Any:
        """Get Project Bi Connection Metadata

        GET /api/v1/projects/{project_id}/bi-connections/{connection_id}/metadata
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/bi-connections/{connection_id}/metadata")

    def post_project_bi_connection_test(self, project_id: str, connection_id: str) -> Any:
        """Post Project Bi Connection Test

        POST /api/v1/projects/{project_id}/bi-connections/{connection_id}/test
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/bi-connections/{connection_id}/test")

    def get_bundle(self, project_id: str) -> Any:
        """The project's recipes, checks, metrics, charts, dashboards, workflows and schedules as one file. Never its data or credentials.

        GET /api/v1/projects/{project_id}/bundle
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/bundle")

    def post_bundle_import(self, project_id: str, *, body: Any) -> Any:
        """Make what the preview showed.

        POST /api/v1/projects/{project_id}/bundle/import
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/bundle/import", body=body)

    def post_bundle_preview(self, project_id: str, *, body: Any) -> Any:
        """What importing the bundle would make, match and skip. Changes nothing.

        POST /api/v1/projects/{project_id}/bundle/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/bundle/preview", body=body)

    def catalog(self, project_id: str, *, q: str | None = None, certified_only: bool | None = None, tag: str | None = None, limit: int | None = None) -> Any:
        """Catalog

        GET /api/v1/projects/{project_id}/catalog
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/catalog", query={"q": q, "certified_only": certified_only, "tag": tag, "limit": limit})

    def read_annotation(self, project_id: str, dataset_id: str) -> Any:
        """Read Annotation

        GET /api/v1/projects/{project_id}/catalog/{dataset_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/catalog/{dataset_id}")

    def edit_annotation(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Edit Annotation

        PATCH /api/v1/projects/{project_id}/catalog/{dataset_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/catalog/{dataset_id}", body=body)

    def read_changes(self, project_id: str, *, status: str | None = None) -> Any:
        """Read Changes

        GET /api/v1/projects/{project_id}/changes
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/changes", query={"status": status})

    def create_change(self, project_id: str, *, body: Any) -> Any:
        """Create Change

        POST /api/v1/projects/{project_id}/changes
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/changes", body=body)

    def read_change(self, project_id: str, change_id: str) -> Any:
        """Read Change

        GET /api/v1/projects/{project_id}/changes/{change_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/changes/{change_id}")

    def approve(self, project_id: str, change_id: str, *, body: Any) -> Any:
        """Approve

        POST /api/v1/projects/{project_id}/changes/{change_id}/approve
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/changes/{change_id}/approve", body=body)

    def reject(self, project_id: str, change_id: str, *, body: Any) -> Any:
        """Reject

        POST /api/v1/projects/{project_id}/changes/{change_id}/reject
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/changes/{change_id}/reject", body=body)

    def withdraw(self, project_id: str, change_id: str) -> Any:
        """Withdraw

        POST /api/v1/projects/{project_id}/changes/{change_id}/withdraw
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/changes/{change_id}/withdraw")

    def read_charts(self, project_id: str) -> Any:
        """Read Charts

        GET /api/v1/projects/{project_id}/charts
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/charts")

    def add_chart(self, project_id: str, *, body: Any) -> Any:
        """Add Chart

        POST /api/v1/projects/{project_id}/charts
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/charts", body=body)

    def preview(self, project_id: str, *, body: Any) -> Any:
        """Preview

        POST /api/v1/projects/{project_id}/charts/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/charts/preview", body=body)

    def read_chart(self, project_id: str, chart_id: str) -> Any:
        """Read Chart

        GET /api/v1/projects/{project_id}/charts/{chart_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/charts/{chart_id}")

    def edit_chart(self, project_id: str, chart_id: str, *, body: Any) -> Any:
        """Edit Chart

        PATCH /api/v1/projects/{project_id}/charts/{chart_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/charts/{chart_id}", body=body)

    def remove_chart(self, project_id: str, chart_id: str) -> Any:
        """Remove Chart

        DELETE /api/v1/projects/{project_id}/charts/{chart_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/charts/{chart_id}")

    def project_usage(self, project_id: str) -> Any:
        """Which connectors this project actually uses, and how they are faring.

        GET /api/v1/projects/{project_id}/connectors/usage
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/connectors/usage")

    def watch_status(self, project_id: str) -> Any:
        """What the schema watch is remembering, and what it could remember.

        GET /api/v1/projects/{project_id}/connectors/watch
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/connectors/watch")

    def run_watch(self, project_id: str, *, body: Any) -> Any:
        """Re-read every watchable stream now.

        POST /api/v1/projects/{project_id}/connectors/watch
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/connectors/watch", body=body)

    def list_project_contracts(self, project_id: str) -> Any:
        """Every contract in the project, with whether each is kept.

        GET /api/v1/projects/{project_id}/contracts
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/contracts")

    def read_dashboards(self, project_id: str) -> Any:
        """Read Dashboards

        GET /api/v1/projects/{project_id}/dashboards
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/dashboards")

    def add_dashboard(self, project_id: str, *, body: Any) -> Any:
        """Add Dashboard

        POST /api/v1/projects/{project_id}/dashboards
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/dashboards", body=body)

    def read_dashboard(self, project_id: str, dashboard_id: str) -> Any:
        """Read Dashboard

        GET /api/v1/projects/{project_id}/dashboards/{dashboard_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}")

    def edit_dashboard(self, project_id: str, dashboard_id: str, *, body: Any) -> Any:
        """Edit Dashboard

        PATCH /api/v1/projects/{project_id}/dashboards/{dashboard_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}", body=body)

    def remove_dashboard(self, project_id: str, dashboard_id: str) -> Any:
        """Remove Dashboard

        DELETE /api/v1/projects/{project_id}/dashboards/{dashboard_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}")

    def read_dashboard_data(self, project_id: str, dashboard_id: str, *, body: Any = None) -> Any:
        """Every tile computed, with the dashboard's global filters (or an ad-hoc set) applied. A read that POSTs because the filters are the body; it stores nothing.

        POST /api/v1/projects/{project_id}/dashboards/{dashboard_id}/data
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}/data", body=body)

    def list_dashboard_embeds(self, project_id: str, dashboard_id: str) -> Any:
        """Where this dashboard is shown on other sites, each with its own link.

        GET /api/v1/projects/{project_id}/dashboards/{dashboard_id}/embeds
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}/embeds")

    def create_dashboard_embed(self, project_id: str, dashboard_id: str, *, body: Any) -> Any:
        """A signed link that runs out after `days`. The answer carries the embed's signing secret, once, for a server that signs links of its own.

        POST /api/v1/projects/{project_id}/dashboards/{dashboard_id}/embeds
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}/embeds", body=body)

    def revoke_dashboard_embed(self, project_id: str, dashboard_id: str, embed_id: str) -> Any:
        """Turn it off: every link signed with its secret stops at once.

        DELETE /api/v1/projects/{project_id}/dashboards/{dashboard_id}/embeds/{embed_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}/embeds/{embed_id}")

    def share(self, project_id: str, dashboard_id: str) -> Any:
        """Share

        POST /api/v1/projects/{project_id}/dashboards/{dashboard_id}/share
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}/share")

    def unshare(self, project_id: str, dashboard_id: str) -> Any:
        """Unshare

        DELETE /api/v1/projects/{project_id}/dashboards/{dashboard_id}/share
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/dashboards/{dashboard_id}/share")

    def get_results(self, project_id: str, *, dataset_id: str | None = None, limit: int | None = None) -> Any:
        """Get Results

        GET /api/v1/projects/{project_id}/data-quality/results
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/data-quality/results", query={"dataset_id": dataset_id, "limit": limit})

    def get_rules(self, project_id: str, *, dataset_id: str | None = None) -> Any:
        """Get Rules

        GET /api/v1/projects/{project_id}/data-quality/rules
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/data-quality/rules", query={"dataset_id": dataset_id})

    def post_rule(self, project_id: str, *, body: Any) -> Any:
        """Post Rule

        POST /api/v1/projects/{project_id}/data-quality/rules
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/data-quality/rules", body=body)

    def patch_rule(self, project_id: str, rule_id: str, *, body: Any) -> Any:
        """Patch Rule

        PATCH /api/v1/projects/{project_id}/data-quality/rules/{rule_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/data-quality/rules/{rule_id}", body=body)

    def remove_rule(self, project_id: str, rule_id: str) -> Any:
        """Remove Rule

        DELETE /api/v1/projects/{project_id}/data-quality/rules/{rule_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/data-quality/rules/{rule_id}")

    def post_database_copy(self, project_id: str, *, body: Any) -> Any:
        """Queue a copy for the background worker; its run shows the progress and the report.

        POST /api/v1/projects/{project_id}/database-copies
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/database-copies", body=body)

    def post_database_copy_plan(self, project_id: str, *, body: Any) -> Any:
        """Post Database Copy Plan

        POST /api/v1/projects/{project_id}/database-copies/plan
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/database-copies/plan", body=body)

    def get_project_datasets(self, project_id: str) -> Any:
        """Get Project Datasets

        GET /api/v1/projects/{project_id}/datasets
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets")

    def post_project_dataset(self, project_id: str, *, body: Any) -> Any:
        """Post Project Dataset

        POST /api/v1/projects/{project_id}/datasets
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets", body=body)

    def analyze_dataset(self, project_id: str, *, spec_id: str | None = None, total_bytes: int | None = None, files: dict[str, Any], data: dict[str, Any] | None = None) -> Any:
        """Work out how to read a file, and store nothing.

        POST /api/v1/projects/{project_id}/datasets/analyze
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/analyze", query={"spec_id": spec_id, "total_bytes": total_bytes}, files=files, data=data)

    def upload_dataset(self, project_id: str, *, dataset_name: str | None = None, spec_id: str | None = None, files: dict[str, Any], data: dict[str, Any] | None = None) -> Any:
        """Upload Dataset

        POST /api/v1/projects/{project_id}/datasets/upload
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/upload", query={"dataset_name": dataset_name, "spec_id": spec_id}, files=files, data=data)

    def start_upload(self, project_id: str, *, body: Any) -> Any:
        """Begin a chunked upload, for a file too large to send in one request.

        POST /api/v1/projects/{project_id}/datasets/uploads
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/uploads", body=body)

    def upload_status(self, project_id: str, upload_id: str) -> Any:
        """Which chunks arrived. A client resumes by sending the ones that did not.

        GET /api/v1/projects/{project_id}/datasets/uploads/{upload_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/uploads/{upload_id}")

    def abandon_upload(self, project_id: str, upload_id: str) -> Any:
        """Abandon Upload

        DELETE /api/v1/projects/{project_id}/datasets/uploads/{upload_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/datasets/uploads/{upload_id}")

    def put_chunk(self, project_id: str, upload_id: str, index: str, *, files: dict[str, Any], data: dict[str, Any] | None = None) -> Any:
        """Send one chunk. Sending the same index again replaces it.

        PUT /api/v1/projects/{project_id}/datasets/uploads/{upload_id}/chunks/{index}
        """
        return self._call("PUT", f"/api/v1/projects/{project_id}/datasets/uploads/{upload_id}/chunks/{index}", files=files, data=data)

    def complete_upload(self, project_id: str, upload_id: str, *, body: Any = None) -> Any:
        """Assemble the chunks, verify them, and ingest the result.

        POST /api/v1/projects/{project_id}/datasets/uploads/{upload_id}/complete
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/uploads/{upload_id}/complete", body=body)

    def get_project_dataset(self, project_id: str, dataset_id: str) -> Any:
        """Get Project Dataset

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}")

    def patch_project_dataset(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Patch Project Dataset

        PATCH /api/v1/projects/{project_id}/datasets/{dataset_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/datasets/{dataset_id}", body=body)

    def remove_project_dataset(self, project_id: str, dataset_id: str) -> Any:
        """Remove Project Dataset

        DELETE /api/v1/projects/{project_id}/datasets/{dataset_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/datasets/{dataset_id}")

    def read_dataset_activity(self, project_id: str, dataset_id: str, *, offset: int | None = None, limit: int | None = None) -> Any:
        """What happened to one dataset, newest first: its versions and what made them, failed runs, checks, schema changes, contracts, alerts, incidents, comments and changes to it.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/activity
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/activity", query={"offset": offset, "limit": limit})

    def read_anomalies(self, project_id: str, dataset_id: str, *, sensitivity: str | None = None, raise_incidents: bool | None = None) -> Any:
        """Read Anomalies

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/anomalies
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/anomalies", query={"sensitivity": sensitivity, "raise_incidents": raise_incidents})

    def get_project_dataset_audit(self, project_id: str, dataset_id: str) -> Any:
        """Get Project Dataset Audit

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/audit
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/audit")

    def export_project_dataset_audit(self, project_id: str, dataset_id: str, *, format: str | None = None) -> Any:
        """Export Project Dataset Audit

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/audit/export
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/audit/export", query={"format": format})

    def read_dataset_contract(self, project_id: str, dataset_id: str) -> Any:
        """A dataset's contract (or none), and promises drafted from its current data.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/contract
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract")

    def save_dataset_contract(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Write or change a dataset's contract; says whether the current data keeps it.

        PUT /api/v1/projects/{project_id}/datasets/{dataset_id}/contract
        """
        return self._call("PUT", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract", body=body)

    def remove_dataset_contract(self, project_id: str, dataset_id: str) -> Any:
        """Remove a dataset's contract.

        DELETE /api/v1/projects/{project_id}/datasets/{dataset_id}/contract
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract")

    def preview_dataset_contract_check(self, project_id: str, dataset_id: str, *, version: int | None = None) -> Any:
        """Whether the current data, or one version, keeps the contract. Records nothing.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/contract/check
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract/check", query={"version": version})

    def check_dataset_contract(self, project_id: str, dataset_id: str) -> Any:
        """Check the current data against the contract now, and record the outcome.

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/contract/check
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract/check")

    def follow_dataset_contract(self, project_id: str, dataset_id: str) -> Any:
        """Be told when the contract breaks, is kept again or changes.

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/contract/follow
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract/follow")

    def unfollow_dataset_contract(self, project_id: str, dataset_id: str) -> Any:
        """Stop being told about the contract.

        DELETE /api/v1/projects/{project_id}/datasets/{dataset_id}/contract/follow
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract/follow")

    def read_contract_history(self, project_id: str, dataset_id: str) -> Any:
        """Every version of the contract, newest first, with what changed.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/contract/history
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/contract/history")

    def post_ad_hoc_check(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Ad Hoc Check

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/data-quality/check
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/data-quality/check", body=body)

    def post_evaluate(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Evaluate

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/data-quality/evaluate
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/data-quality/evaluate", body=body)

    def post_dataset_delivery(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Small datasets are written now; a large one is queued for the worker (status "queued").

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/deliver
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/deliver", body=body)

    def post_dataset_delivery_preview(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Dataset Delivery Preview

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/deliver/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/deliver/preview", body=body)

    def documentation(self, project_id: str, dataset_id: str) -> Any:
        """A draft description, assembled from facts already recorded.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/documentation
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/documentation")

    def get_project_dataset_download(self, project_id: str, dataset_id: str, *, format: str | None = None, version: int | None = None) -> Any:
        """Get Project Dataset Download

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/download
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/download", query={"format": format, "version": version})

    def duplicates(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Values that look like the same thing written differently.

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/duplicates
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/duplicates", body=body)

    def explain(self, project_id: str, dataset_id: str, *, metric: str | None = None, window_days: int | None = None) -> Any:
        """What else changed when this metric moved.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/explain
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/explain", query={"metric": metric, "window_days": window_days})

    def dataset_terms(self, project_id: str, dataset_id: str) -> Any:
        """Dataset Terms

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/glossary-terms
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/glossary-terms")

    def link_dataset_term(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Link Dataset Term

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/glossary-terms
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/glossary-terms", body=body)

    def unlink_dataset_term(self, project_id: str, dataset_id: str, term_id: str, *, column: str) -> Any:
        """Unlink Dataset Term

        DELETE /api/v1/projects/{project_id}/datasets/{dataset_id}/glossary-terms/{term_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/glossary-terms/{term_id}", query={"column": column})

    def impact(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Impact

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/impact
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/impact", body=body)

    def join_keys(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """How these two datasets join, judged by real value overlap.

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/join-keys
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/join-keys", body=body)

    def read_lineage(self, project_id: str, dataset_id: str, *, depth: int | None = None) -> Any:
        """Read Lineage

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/lineage
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/lineage", query={"depth": depth})

    def read_columns(self, project_id: str, dataset_id: str) -> Any:
        """Read Columns

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/lineage/columns
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/lineage/columns")

    def trace_column(self, project_id: str, dataset_id: str, column_name: str) -> Any:
        """Trace Column

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/lineage/columns/{column_name}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/lineage/columns/{column_name}")

    def list_metric_alerts(self, project_id: str, dataset_id: str) -> Any:
        """The dataset's alerts, and the newest times they crossed their line or came back.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts")

    def create_metric_alert(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Alert when a measure is above or below a value, or changes by more than a percentage. Checked against the newest measures at once, then each time they are recorded.

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts", body=body)

    def update_metric_alert(self, project_id: str, dataset_id: str, alert_id: str, *, body: Any) -> Any:
        """Update Metric Alert

        PATCH /api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts/{alert_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts/{alert_id}", body=body)

    def delete_metric_alert(self, project_id: str, dataset_id: str, alert_id: str) -> Any:
        """Delete Metric Alert

        DELETE /api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts/{alert_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/metric-alerts/{alert_id}")

    def read_metrics(self, project_id: str, dataset_id: str, *, metric: str | None = None, column: str | None = None, limit: int | None = None) -> Any:
        """Read Metrics

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/metrics
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/metrics", query={"metric": metric, "column": column, "limit": limit})

    def capture_metrics(self, project_id: str, dataset_id: str) -> Any:
        """Capture Metrics

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/metrics/capture
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/metrics/capture")

    def pii_scan(self, project_id: str, dataset_id: str) -> Any:
        """Columns that look like personal data, with how sure this is.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/pii
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/pii")

    def masking(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Masking

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/pii/mask
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/pii/mask", body=body)

    def get_dataset_pipelines(self, project_id: str, dataset_id: str) -> Any:
        """Get Dataset Pipelines

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines")

    def post_dataset_pipeline(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Dataset Pipeline

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines", body=body)

    def post_dataset_pipeline_preview(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Dataset Pipeline Preview

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/pipelines/preview", body=body)

    def get_project_dataset_preview(self, project_id: str, dataset_id: str) -> Any:
        """Get Project Dataset Preview

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/preview
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/preview")

    def get_project_dataset_profile(self, project_id: str, dataset_id: str) -> Any:
        """Get Project Dataset Profile

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/profile
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/profile")

    def post_publish_dataset_to_postgres(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Publish Dataset To Postgres

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/publish/postgres
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/publish/postgres", body=body)

    def post_publish_dataset_to_power_bi(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Publish Dataset To Power Bi

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/publish/power-bi
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/publish/power-bi", body=body)

    def post_publish_dataset_to_tableau(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Publish Dataset To Tableau

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/publish/tableau
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/publish/tableau", body=body)

    def rule_suggestions(self, project_id: str, dataset_id: str) -> Any:
        """Quality rules the profile already justifies.

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/rule-suggestions
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/rule-suggestions")

    def get_schema_drift(self, project_id: str, dataset_id: str, *, baseline_dataset_id: str, record: bool | None = None) -> Any:
        """Get Schema Drift

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/schema-drift
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/schema-drift", query={"baseline_dataset_id": baseline_dataset_id, "record": record})

    def preview_security_policies(self, project_id: str, dataset_id: str, *, role: str | None = None, user_id: str | None = None) -> Any:
        """What somebody would actually see -- as a bare role, or, when user_id is given, as that specific person (their project role resolved for them).

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/security-preview
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/security-preview", query={"role": role, "user_id": user_id})

    def get_dataset_transformation_suggestions(self, project_id: str, dataset_id: str) -> Any:
        """Get Dataset Transformation Suggestions

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/suggestions
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/suggestions")

    def get_project_dataset_versions(self, project_id: str, dataset_id: str) -> Any:
        """Get Project Dataset Versions

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/versions
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions")

    def post_project_dataset_versions_diff(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """Post Project Dataset Versions Diff

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/versions/diff
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/diff", body=body)

    def query_dataset_version(self, project_id: str, dataset_id: str, *, body: Any) -> Any:
        """SQL over a dataset as of a version or an instant. A read (viewer): `query` is a read-only segment in the central matrix.

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/versions/query
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/query", body=body)

    def get_project_dataset_version(self, project_id: str, dataset_id: str, version_number: str) -> Any:
        """Get Project Dataset Version

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{version_number}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{version_number}")

    def get_project_dataset_version_preview(self, project_id: str, dataset_id: str, version_number: str) -> Any:
        """Get Project Dataset Version Preview

        GET /api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{version_number}/preview
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{version_number}/preview")

    def post_project_dataset_version_rollback(self, project_id: str, dataset_id: str, version_number: str) -> Any:
        """Post Project Dataset Version Rollback

        POST /api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{version_number}/rollback
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{dataset_id}/versions/{version_number}/rollback")

    def get_dataset_vs_dataset_comparison(self, project_id: str, left_dataset_id: str, right_dataset_id: str) -> Any:
        """Get Dataset Vs Dataset Comparison

        GET /api/v1/projects/{project_id}/datasets/{left_dataset_id}/compare/{right_dataset_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/datasets/{left_dataset_id}/compare/{right_dataset_id}")

    def post_dataset_statistical_test(self, project_id: str, left_dataset_id: str, right_dataset_id: str, *, body: Any) -> Any:
        """Post Dataset Statistical Test

        POST /api/v1/projects/{project_id}/datasets/{left_dataset_id}/tests/{right_dataset_id}
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/datasets/{left_dataset_id}/tests/{right_dataset_id}", body=body)

    def describe(self, project_id: str, *, body: Any) -> Any:
        """Turn a typed request into pipeline steps.

        POST /api/v1/projects/{project_id}/describe
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/describe", body=body)

    def get_project_destinations(self, project_id: str) -> Any:
        """Get Project Destinations

        GET /api/v1/projects/{project_id}/destinations
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/destinations")

    def post_project_destination(self, project_id: str, *, body: Any) -> Any:
        """Post Project Destination

        POST /api/v1/projects/{project_id}/destinations
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/destinations", body=body)

    def get_project_destination(self, project_id: str, destination_id: str) -> Any:
        """Get Project Destination

        GET /api/v1/projects/{project_id}/destinations/{destination_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/destinations/{destination_id}")

    def patch_project_destination(self, project_id: str, destination_id: str, *, body: Any) -> Any:
        """Patch Project Destination

        PATCH /api/v1/projects/{project_id}/destinations/{destination_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/destinations/{destination_id}", body=body)

    def remove_project_destination(self, project_id: str, destination_id: str) -> Any:
        """Remove Project Destination

        DELETE /api/v1/projects/{project_id}/destinations/{destination_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/destinations/{destination_id}")

    def post_project_destination_test(self, project_id: str, destination_id: str) -> Any:
        """Post Project Destination Test

        POST /api/v1/projects/{project_id}/destinations/{destination_id}/test
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/destinations/{destination_id}/test")

    def read_comments(self, project_id: str, *, target_id: str, target_type: str) -> Any:
        """Read Comments

        GET /api/v1/projects/{project_id}/discussion
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/discussion", query={"target_id": target_id, "target_type": target_type})

    def write_comment(self, project_id: str, *, body: Any) -> Any:
        """Write Comment

        POST /api/v1/projects/{project_id}/discussion
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/discussion", body=body)

    def reopen_comment_thread(self, project_id: str, comment_id: str) -> Any:
        """Open a resolved thread again.

        POST /api/v1/projects/{project_id}/discussion/{comment_id}/reopen
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/discussion/{comment_id}/reopen")

    def close_comment(self, project_id: str, comment_id: str) -> Any:
        """Close Comment

        POST /api/v1/projects/{project_id}/discussion/{comment_id}/resolve
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/discussion/{comment_id}/resolve")

    def read_erasures(self, project_id: str) -> Any:
        """Read Erasures

        GET /api/v1/projects/{project_id}/erasures
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/erasures")

    def erase(self, project_id: str, *, body: Any) -> Any:
        """Find a person across every dataset, and redact them if asked.

        POST /api/v1/projects/{project_id}/erasures
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/erasures", body=body)

    def get_connections(self, project_id: str) -> Any:
        """Get Connections

        GET /api/v1/projects/{project_id}/extraction/connections
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/extraction/connections")

    def post_connection(self, project_id: str, *, body: Any) -> Any:
        """Post Connection

        POST /api/v1/projects/{project_id}/extraction/connections
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/extraction/connections", body=body)

    def patch_connection(self, project_id: str, connection_id: str, *, body: Any) -> Any:
        """Patch Connection

        PATCH /api/v1/projects/{project_id}/extraction/connections/{connection_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}", body=body)

    def remove_connection(self, project_id: str, connection_id: str) -> Any:
        """Remove Connection

        DELETE /api/v1/projects/{project_id}/extraction/connections/{connection_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}")

    def get_columns(self, project_id: str, connection_id: str, *, table: str, schema_name: str | None = None) -> Any:
        """Get Columns

        GET /api/v1/projects/{project_id}/extraction/connections/{connection_id}/columns
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}/columns", query={"table": table, "schema_name": schema_name})

    def post_preview(self, project_id: str, connection_id: str, *, body: Any) -> Any:
        """Post Preview

        POST /api/v1/projects/{project_id}/extraction/connections/{connection_id}/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}/preview", body=body)

    def get_table_statistics(self, project_id: str, connection_id: str, *, table: str, schema_name: str | None = None) -> Any:
        """What is known about a table: rows, and per column its spread and commonest values.

        GET /api/v1/projects/{project_id}/extraction/connections/{connection_id}/statistics
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}/statistics", query={"table": table, "schema_name": schema_name})

    def refresh_table_statistics(self, project_id: str, connection_id: str, *, body: Any) -> Any:
        """Collect a table's statistics again now, rather than waiting for the daily pass.

        POST /api/v1/projects/{project_id}/extraction/connections/{connection_id}/statistics/refresh
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}/statistics/refresh", body=body)

    def get_tables(self, project_id: str, connection_id: str) -> Any:
        """Get Tables

        GET /api/v1/projects/{project_id}/extraction/connections/{connection_id}/tables
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}/tables")

    def post_connection_test(self, project_id: str, connection_id: str) -> Any:
        """Post Connection Test

        POST /api/v1/projects/{project_id}/extraction/connections/{connection_id}/test
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/extraction/connections/{connection_id}/test")

    def get_jobs(self, project_id: str) -> Any:
        """Get Jobs

        GET /api/v1/projects/{project_id}/extraction/jobs
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/extraction/jobs")

    def post_job(self, project_id: str, *, body: Any) -> Any:
        """Post Job

        POST /api/v1/projects/{project_id}/extraction/jobs
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/extraction/jobs", body=body)

    def patch_job(self, project_id: str, job_id: str, *, body: Any) -> Any:
        """Patch Job

        PATCH /api/v1/projects/{project_id}/extraction/jobs/{job_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/extraction/jobs/{job_id}", body=body)

    def remove_job(self, project_id: str, job_id: str) -> Any:
        """Remove Job

        DELETE /api/v1/projects/{project_id}/extraction/jobs/{job_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/extraction/jobs/{job_id}")

    def post_job_reset_watermark(self, project_id: str, job_id: str) -> Any:
        """Post Job Reset Watermark

        POST /api/v1/projects/{project_id}/extraction/jobs/{job_id}/reset-watermark
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/extraction/jobs/{job_id}/reset-watermark")

    def post_job_run(self, project_id: str, job_id: str) -> Any:
        """Post Job Run

        POST /api/v1/projects/{project_id}/extraction/jobs/{job_id}/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/extraction/jobs/{job_id}/run")

    def read_policies(self, project_id: str) -> Any:
        """Read Policies

        GET /api/v1/projects/{project_id}/freshness-policies
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/freshness-policies")

    def create_policy(self, project_id: str, *, body: Any) -> Any:
        """Create Policy

        POST /api/v1/projects/{project_id}/freshness-policies
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/freshness-policies", body=body)

    def patch_policy(self, project_id: str, policy_id: str, *, body: Any) -> Any:
        """Patch Policy

        PATCH /api/v1/projects/{project_id}/freshness-policies/{policy_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/freshness-policies/{policy_id}", body=body)

    def remove_policy(self, project_id: str, policy_id: str) -> Any:
        """Remove Policy

        DELETE /api/v1/projects/{project_id}/freshness-policies/{policy_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/freshness-policies/{policy_id}")

    def run_freshness_check(self, project_id: str) -> Any:
        """Run Freshness Check

        POST /api/v1/projects/{project_id}/freshness/check
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/freshness/check")

    def read_terms(self, project_id: str) -> Any:
        """Read Terms

        GET /api/v1/projects/{project_id}/glossary
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/glossary")

    def add_term(self, project_id: str, *, body: Any) -> Any:
        """Add Term

        POST /api/v1/projects/{project_id}/glossary
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/glossary", body=body)

    def edit_term(self, project_id: str, term_id: str, *, body: Any) -> Any:
        """Edit Term

        PATCH /api/v1/projects/{project_id}/glossary/{term_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/glossary/{term_id}", body=body)

    def remove_term(self, project_id: str, term_id: str) -> Any:
        """Remove Term

        DELETE /api/v1/projects/{project_id}/glossary/{term_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/glossary/{term_id}")

    def read_versions(self, project_id: str, resource_id: str, resource_type: str) -> Any:
        """Read Versions

        GET /api/v1/projects/{project_id}/history/{resource_type}/{resource_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/history/{resource_type}/{resource_id}")

    def compare_versions(self, project_id: str, resource_type: str, resource_id: str, *, left: int, right: int) -> Any:
        """Compare Versions

        GET /api/v1/projects/{project_id}/history/{resource_type}/{resource_id}/diff
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/history/{resource_type}/{resource_id}/diff", query={"left": left, "right": right})

    def restore(self, project_id: str, resource_type: str, resource_id: str, *, body: Any) -> Any:
        """Restore

        POST /api/v1/projects/{project_id}/history/{resource_type}/{resource_id}/restore
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/history/{resource_type}/{resource_id}/restore", body=body)

    def read_version(self, project_id: str, resource_type: str, resource_id: str, version: str) -> Any:
        """Read Version

        GET /api/v1/projects/{project_id}/history/{resource_type}/{resource_id}/versions/{version}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/history/{resource_type}/{resource_id}/versions/{version}")

    def read_incidents(self, project_id: str, *, status: str | None = None, severity: str | None = None, limit: int | None = None) -> Any:
        """Read Incidents

        GET /api/v1/projects/{project_id}/incidents
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/incidents", query={"status": status, "severity": severity, "limit": limit})

    def read_incident(self, project_id: str, incident_id: str) -> Any:
        """Read Incident

        GET /api/v1/projects/{project_id}/incidents/{incident_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/incidents/{incident_id}")

    def ack(self, project_id: str, incident_id: str) -> Any:
        """Ack

        POST /api/v1/projects/{project_id}/incidents/{incident_id}/acknowledge
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/incidents/{incident_id}/acknowledge")

    def set_assignee(self, project_id: str, incident_id: str, *, body: Any) -> Any:
        """Set Assignee

        POST /api/v1/projects/{project_id}/incidents/{incident_id}/assign
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/incidents/{incident_id}/assign", body=body)

    def add_comment(self, project_id: str, incident_id: str, *, body: Any) -> Any:
        """Add Comment

        POST /api/v1/projects/{project_id}/incidents/{incident_id}/comments
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/incidents/{incident_id}/comments", body=body)

    def open_again(self, project_id: str, incident_id: str, *, body: Any) -> Any:
        """Open Again

        POST /api/v1/projects/{project_id}/incidents/{incident_id}/reopen
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/incidents/{incident_id}/reopen", body=body)

    def close(self, project_id: str, incident_id: str, *, body: Any) -> Any:
        """Close

        POST /api/v1/projects/{project_id}/incidents/{incident_id}/resolve
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/incidents/{incident_id}/resolve", body=body)

    def list_specs(self, project_id: str) -> Any:
        """List Specs

        GET /api/v1/projects/{project_id}/ingest-specs
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/ingest-specs")

    def remember_spec(self, project_id: str, *, body: Any) -> Any:
        """Save a confirmed spec so the next file of this kind reuses it.

        POST /api/v1/projects/{project_id}/ingest-specs
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/ingest-specs", body=body)

    def delete_spec(self, project_id: str, spec_id: str) -> Any:
        """Delete Spec

        DELETE /api/v1/projects/{project_id}/ingest-specs/{spec_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/ingest-specs/{spec_id}")

    def read_live_kinds(self, project_id: str) -> Any:
        """Every kind of live source, its settings, guarantee and tier.

        GET /api/v1/projects/{project_id}/live/kinds
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/live/kinds")

    def read_members(self, project_id: str) -> Any:
        """Read Members

        GET /api/v1/projects/{project_id}/members
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/members")

    def add_project_member(self, project_id: str, *, body: Any) -> Any:
        """Add Project Member

        POST /api/v1/projects/{project_id}/members
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/members", body=body)

    def change_role(self, project_id: str, membership_id: str, *, body: Any) -> Any:
        """Change Role

        PATCH /api/v1/projects/{project_id}/members/{membership_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/members/{membership_id}", body=body)

    def revoke(self, project_id: str, membership_id: str) -> Any:
        """Revoke

        DELETE /api/v1/projects/{project_id}/members/{membership_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/members/{membership_id}")

    def list_project_metrics(self, project_id: str) -> Any:
        """List Project Metrics

        GET /api/v1/projects/{project_id}/metrics
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/metrics")

    def add_metric(self, project_id: str, *, body: Any) -> Any:
        """Add Metric

        POST /api/v1/projects/{project_id}/metrics
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/metrics", body=body)

    def read_metric(self, project_id: str, metric_id: str) -> Any:
        """Read Metric

        GET /api/v1/projects/{project_id}/metrics/{metric_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/metrics/{metric_id}")

    def edit_metric(self, project_id: str, metric_id: str, *, body: Any) -> Any:
        """Edit Metric

        PATCH /api/v1/projects/{project_id}/metrics/{metric_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/metrics/{metric_id}", body=body)

    def remove_metric(self, project_id: str, metric_id: str) -> Any:
        """Remove Metric

        DELETE /api/v1/projects/{project_id}/metrics/{metric_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/metrics/{metric_id}")

    def preview_metric_route(self, project_id: str, metric_id: str, *, body: Any = None) -> Any:
        """Compute the metric now, cut by dimensions. A read (viewer).

        POST /api/v1/projects/{project_id}/metrics/{metric_id}/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/metrics/{metric_id}/preview", body=body)

    def read_metric_sql(self, project_id: str, metric_id: str, *, dialect: str | None = None, dimensions: str | None = None) -> Any:
        """The definition rendered as SQL in a dialect, for the workbench.

        GET /api/v1/projects/{project_id}/metrics/{metric_id}/sql
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/metrics/{metric_id}/sql", query={"dialect": dialect, "dimensions": dimensions})

    def read_metric_usage(self, project_id: str, metric_id: str) -> Any:
        """What resolves through this metric -- what moves if it changes.

        GET /api/v1/projects/{project_id}/metrics/{metric_id}/usage
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/metrics/{metric_id}/usage")

    def get_notification_targets(self, project_id: str) -> Any:
        """Get Notification Targets

        GET /api/v1/projects/{project_id}/notification-targets
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/notification-targets")

    def post_notification_target(self, project_id: str, *, body: Any) -> Any:
        """Post Notification Target

        POST /api/v1/projects/{project_id}/notification-targets
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/notification-targets", body=body)

    def get_notification_target(self, project_id: str, target_id: str) -> Any:
        """Get Notification Target

        GET /api/v1/projects/{project_id}/notification-targets/{target_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/notification-targets/{target_id}")

    def patch_notification_target(self, project_id: str, target_id: str, *, body: Any) -> Any:
        """Patch Notification Target

        PATCH /api/v1/projects/{project_id}/notification-targets/{target_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/notification-targets/{target_id}", body=body)

    def remove_notification_target(self, project_id: str, target_id: str) -> Any:
        """Remove Notification Target

        DELETE /api/v1/projects/{project_id}/notification-targets/{target_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/notification-targets/{target_id}")

    def get_webhook_deliveries(self, project_id: str, target_id: str, *, limit: int | None = None) -> Any:
        """The latest events sent to a webhook and how each went.

        GET /api/v1/projects/{project_id}/notification-targets/{target_id}/deliveries
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/notification-targets/{target_id}/deliveries", query={"limit": limit})

    def post_rotate_webhook_secret(self, project_id: str, target_id: str) -> Any:
        """A webhook's new signing secret, shown in this answer only.

        POST /api/v1/projects/{project_id}/notification-targets/{target_id}/rotate-secret
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/notification-targets/{target_id}/rotate-secret")

    def post_notification_target_test(self, project_id: str, target_id: str) -> Any:
        """Post Notification Target Test

        POST /api/v1/projects/{project_id}/notification-targets/{target_id}/test
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/notification-targets/{target_id}/test")

    def get_project_notifications(self, project_id: str, *, limit: int | None = None) -> Any:
        """Get Project Notifications

        GET /api/v1/projects/{project_id}/notifications
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/notifications", query={"limit": limit})

    def get_project_pipelines(self, project_id: str) -> Any:
        """Get Project Pipelines

        GET /api/v1/projects/{project_id}/pipelines
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/pipelines")

    def get_project_pipeline(self, project_id: str, pipeline_id: str) -> Any:
        """Get Project Pipeline

        GET /api/v1/projects/{project_id}/pipelines/{pipeline_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}")

    def patch_project_pipeline(self, project_id: str, pipeline_id: str, *, body: Any) -> Any:
        """Patch Project Pipeline

        PATCH /api/v1/projects/{project_id}/pipelines/{pipeline_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}", body=body)

    def post_run_transformation_pipeline(self, project_id: str, pipeline_id: str) -> Any:
        """Post Run Transformation Pipeline

        POST /api/v1/projects/{project_id}/pipelines/{pipeline_id}/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}/run")

    def read_recipe_shared_copy(self, project_id: str, pipeline_id: str, *, epoch: int | None = None, after: int | None = None, revision: int | None = None) -> Any:
        """The recipe's shared working copy, or what changed in it since `after`.

        GET /api/v1/projects/{project_id}/pipelines/{pipeline_id}/shared
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}/shared", query={"epoch": epoch, "after": after, "revision": revision})

    def push_recipe_changes(self, project_id: str, pipeline_id: str, *, body: Any) -> Any:
        """Merge changes into the recipe's shared working copy.

        POST /api/v1/projects/{project_id}/pipelines/{pipeline_id}/shared
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}/shared", body=body)

    def discard_recipe_changes(self, project_id: str, pipeline_id: str) -> Any:
        """Throw away the shared copy's unsaved changes, for everyone editing it.

        POST /api/v1/projects/{project_id}/pipelines/{pipeline_id}/shared/discard
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}/shared/discard")

    def suggest_recipe_change(self, project_id: str, pipeline_id: str, *, body: Any) -> Any:
        """Suggest a change to a recipe for someone who may edit it to accept or decline.

        POST /api/v1/projects/{project_id}/pipelines/{pipeline_id}/suggest
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/pipelines/{pipeline_id}/suggest", body=body)

    def pivot_table(self, project_id: str, *, body: Any) -> Any:
        """Pivot Table

        POST /api/v1/projects/{project_id}/pivot
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/pivot", body=body)

    def read_who_is_here(self, project_id: str, *, target_id: str, target_type: str | None = None) -> Any:
        """Who has something open now.

        GET /api/v1/projects/{project_id}/presence
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/presence", query={"target_id": target_id, "target_type": target_type})

    def say_here(self, project_id: str, *, body: Any) -> Any:
        """Say you have something open, and hear who else has.

        POST /api/v1/projects/{project_id}/presence
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/presence", body=body)

    def say_gone(self, project_id: str, client_id: str, *, target_id: str, target_type: str | None = None) -> Any:
        """This page has closed.

        DELETE /api/v1/projects/{project_id}/presence/{client_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/presence/{client_id}", query={"target_id": target_id, "target_type": target_type})

    def promote_resource_to(self, project_id: str, *, body: Any) -> Any:
        """Promote Resource To

        POST /api/v1/projects/{project_id}/promote
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/promote", body=body)

    def read_reports(self, project_id: str) -> Any:
        """Read Reports

        GET /api/v1/projects/{project_id}/reports
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/reports")

    def add_report(self, project_id: str, *, body: Any) -> Any:
        """Add Report

        POST /api/v1/projects/{project_id}/reports
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/reports", body=body)

    def edit_report(self, project_id: str, report_id: str, *, body: Any) -> Any:
        """Edit Report

        PATCH /api/v1/projects/{project_id}/reports/{report_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/reports/{report_id}", body=body)

    def remove_report(self, project_id: str, report_id: str) -> Any:
        """Remove Report

        DELETE /api/v1/projects/{project_id}/reports/{report_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/reports/{report_id}")

    def deliveries(self, project_id: str, report_id: str) -> Any:
        """Deliveries

        GET /api/v1/projects/{project_id}/reports/{report_id}/deliveries
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/reports/{report_id}/deliveries")

    def generate(self, project_id: str, report_id: str) -> Any:
        """Generate the file now and hand it straight back.

        POST /api/v1/projects/{project_id}/reports/{report_id}/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/reports/{report_id}/run")

    def read_retention(self, project_id: str) -> Any:
        """Read Retention

        GET /api/v1/projects/{project_id}/retention
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/retention")

    def add_retention(self, project_id: str, *, body: Any) -> Any:
        """Add Retention

        POST /api/v1/projects/{project_id}/retention
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/retention", body=body)

    def sweep(self, project_id: str) -> Any:
        """Sweep

        POST /api/v1/projects/{project_id}/retention/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/retention/run")

    def get_project_runs(self, project_id: str) -> Any:
        """Get Project Runs

        GET /api/v1/projects/{project_id}/runs
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/runs")

    def post_sample_run(self, project_id: str) -> Any:
        """Post Sample Run

        POST /api/v1/projects/{project_id}/runs/sample
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/runs/sample")

    def get_project_run(self, project_id: str, run_id: str) -> Any:
        """Get Project Run

        GET /api/v1/projects/{project_id}/runs/{run_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/runs/{run_id}")

    def get_project_run_audit(self, project_id: str, run_id: str) -> Any:
        """Get Project Run Audit

        GET /api/v1/projects/{project_id}/runs/{run_id}/audit
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/runs/{run_id}/audit")

    def export_project_run_audit(self, project_id: str, run_id: str, *, format: str | None = None) -> Any:
        """Export Project Run Audit

        GET /api/v1/projects/{project_id}/runs/{run_id}/audit/export
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/runs/{run_id}/audit/export", query={"format": format})

    def get_run_comparison(self, project_id: str, run_id: str) -> Any:
        """Get Run Comparison

        GET /api/v1/projects/{project_id}/runs/{run_id}/comparison
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/runs/{run_id}/comparison")

    def post_replay_pipeline_run(self, project_id: str, run_id: str) -> Any:
        """Re-execute a recorded run against its pinned inputs at its recorded instant, and compare with what it published. Editor role: it publishes a new dataset (central matrix, `replay` ∈ EDITOR_SEGMENTS).

        POST /api/v1/projects/{project_id}/runs/{run_id}/replay
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/runs/{run_id}/replay")

    def add_sample(self, project_id: str, sample_id: str) -> Any:
        """Add Sample

        POST /api/v1/projects/{project_id}/samples/{sample_id}
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/samples/{sample_id}")

    def get_schedules(self, project_id: str) -> Any:
        """Get Schedules

        GET /api/v1/projects/{project_id}/schedules
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/schedules")

    def post_schedule(self, project_id: str, *, body: Any) -> Any:
        """Post Schedule

        POST /api/v1/projects/{project_id}/schedules
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/schedules", body=body)

    def get_one_schedule(self, project_id: str, schedule_id: str) -> Any:
        """Get One Schedule

        GET /api/v1/projects/{project_id}/schedules/{schedule_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/schedules/{schedule_id}")

    def patch_schedule(self, project_id: str, schedule_id: str, *, body: Any) -> Any:
        """Patch Schedule

        PATCH /api/v1/projects/{project_id}/schedules/{schedule_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/schedules/{schedule_id}", body=body)

    def remove_schedule(self, project_id: str, schedule_id: str) -> Any:
        """Remove Schedule

        DELETE /api/v1/projects/{project_id}/schedules/{schedule_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/schedules/{schedule_id}")

    def post_toggle(self, project_id: str, schedule_id: str, *, body: Any) -> Any:
        """Post Toggle

        POST /api/v1/projects/{project_id}/schedules/{schedule_id}/toggle
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/schedules/{schedule_id}/toggle", body=body)

    def post_trigger_now(self, project_id: str, schedule_id: str) -> Any:
        """Post Trigger Now

        POST /api/v1/projects/{project_id}/schedules/{schedule_id}/trigger-now
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/schedules/{schedule_id}/trigger-now")

    def get_drift_events(self, project_id: str, *, dataset_id: str | None = None, unacknowledged_only: bool | None = None, limit: int | None = None) -> Any:
        """Get Drift Events

        GET /api/v1/projects/{project_id}/schema-drift/events
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/schema-drift/events", query={"dataset_id": dataset_id, "unacknowledged_only": unacknowledged_only, "limit": limit})

    def post_acknowledge_drift(self, project_id: str, event_id: str) -> Any:
        """Post Acknowledge Drift

        POST /api/v1/projects/{project_id}/schema-drift/events/{event_id}/acknowledge
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/schema-drift/events/{event_id}/acknowledge")

    def list_security_policies(self, project_id: str, *, dataset_id: str | None = None) -> Any:
        """List Security Policies

        GET /api/v1/projects/{project_id}/security-policies
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/security-policies", query={"dataset_id": dataset_id})

    def add_policy(self, project_id: str, *, body: Any) -> Any:
        """Add Policy

        POST /api/v1/projects/{project_id}/security-policies
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/security-policies", body=body)

    def edit_policy(self, project_id: str, policy_id: str, *, body: Any) -> Any:
        """Edit Policy

        PATCH /api/v1/projects/{project_id}/security-policies/{policy_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/security-policies/{policy_id}", body=body)

    def remove_security_policy(self, project_id: str, policy_id: str) -> Any:
        """Remove Security Policy

        DELETE /api/v1/projects/{project_id}/security-policies/{policy_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/security-policies/{policy_id}")

    def get_project_sources(self, project_id: str) -> Any:
        """Get Project Sources

        GET /api/v1/projects/{project_id}/sources
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/sources")

    def post_project_source(self, project_id: str, *, body: Any) -> Any:
        """Post Project Source

        POST /api/v1/projects/{project_id}/sources
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/sources", body=body)

    def read_streams(self, project_id: str) -> Any:
        """Read Streams

        GET /api/v1/projects/{project_id}/streams
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/streams")

    def add_stream(self, project_id: str, *, body: Any) -> Any:
        """A webhook's token comes back in this response and never again.

        POST /api/v1/projects/{project_id}/streams
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams", body=body)

    def test_stream_settings(self, project_id: str, *, body: Any) -> Any:
        """Whether settings would work, before they are saved.

        POST /api/v1/projects/{project_id}/streams/try
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams/try", body=body)

    def read_stream(self, project_id: str, source_id: str) -> Any:
        """Read Stream

        GET /api/v1/projects/{project_id}/streams/{source_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/streams/{source_id}")

    def edit_stream(self, project_id: str, source_id: str, *, body: Any) -> Any:
        """Rename, pause or resume, change settings, tables or how often it is read and saved.

        PATCH /api/v1/projects/{project_id}/streams/{source_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/streams/{source_id}", body=body)

    def remove_stream(self, project_id: str, source_id: str) -> Any:
        """Remove Stream

        DELETE /api/v1/projects/{project_id}/streams/{source_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/streams/{source_id}")

    def read_stream_events(self, project_id: str, source_id: str, *, limit: int | None = None) -> Any:
        """Read Stream Events

        GET /api/v1/projects/{project_id}/streams/{source_id}/events
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/streams/{source_id}/events", query={"limit": limit})

    def materialise_stream(self, project_id: str, source_id: str) -> Any:
        """Save now: the log, every table kept current and every live recipe's output.

        POST /api/v1/projects/{project_id}/streams/{source_id}/materialise
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams/{source_id}/materialise")

    def poll_stream(self, project_id: str, source_id: str) -> Any:
        """Read now, outside the runner's schedule.

        POST /api/v1/projects/{project_id}/streams/{source_id}/poll
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams/{source_id}/poll")

    def read_live_recipes(self, project_id: str, source_id: str) -> Any:
        """Read Live Recipes

        GET /api/v1/projects/{project_id}/streams/{source_id}/recipes
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/streams/{source_id}/recipes")

    def add_live_recipe(self, project_id: str, source_id: str, *, body: Any) -> Any:
        """Add Live Recipe

        POST /api/v1/projects/{project_id}/streams/{source_id}/recipes
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams/{source_id}/recipes", body=body)

    def edit_live_recipe(self, project_id: str, source_id: str, recipe_id: str, *, body: Any) -> Any:
        """Edit Live Recipe

        PATCH /api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}", body=body)

    def remove_live_recipe(self, project_id: str, source_id: str, recipe_id: str) -> Any:
        """Remove Live Recipe

        DELETE /api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}")

    def read_live_recipe_results(self, project_id: str, source_id: str, recipe_id: str, *, limit: int | None = None) -> Any:
        """Read Live Recipe Results

        GET /api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}/results
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}/results", query={"limit": limit})

    def restart_live_recipe(self, project_id: str, source_id: str, recipe_id: str) -> Any:
        """Restart Live Recipe

        POST /api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}/start-again
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams/{source_id}/recipes/{recipe_id}/start-again")

    def restart_stream(self, project_id: str, source_id: str) -> Any:
        """Forget the saved position; change capture takes its snapshots again.

        POST /api/v1/projects/{project_id}/streams/{source_id}/start-again
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams/{source_id}/start-again")

    def test_stream(self, project_id: str, source_id: str) -> Any:
        """Test Stream

        POST /api/v1/projects/{project_id}/streams/{source_id}/test
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/streams/{source_id}/test")

    def read_stream_throughput(self, project_id: str, source_id: str) -> Any:
        """Read Stream Throughput

        GET /api/v1/projects/{project_id}/streams/{source_id}/throughput
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/streams/{source_id}/throughput")

    def get_saved_statistical_tests(self, project_id: str, *, left_dataset_id: str | None = None, right_dataset_id: str | None = None) -> Any:
        """Get Saved Statistical Tests

        GET /api/v1/projects/{project_id}/tests/saved
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/tests/saved", query={"left_dataset_id": left_dataset_id, "right_dataset_id": right_dataset_id})

    def post_saved_statistical_test(self, project_id: str, *, body: Any) -> Any:
        """Post Saved Statistical Test

        POST /api/v1/projects/{project_id}/tests/saved
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/tests/saved", body=body)

    def get_saved_statistical_test(self, project_id: str, saved_test_id: str) -> Any:
        """Get Saved Statistical Test

        GET /api/v1/projects/{project_id}/tests/saved/{saved_test_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/tests/saved/{saved_test_id}")

    def patch_saved_statistical_test(self, project_id: str, saved_test_id: str, *, body: Any) -> Any:
        """Patch Saved Statistical Test

        PATCH /api/v1/projects/{project_id}/tests/saved/{saved_test_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/tests/saved/{saved_test_id}", body=body)

    def remove_saved_test(self, project_id: str, saved_test_id: str) -> Any:
        """Remove Saved Test

        DELETE /api/v1/projects/{project_id}/tests/saved/{saved_test_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/tests/saved/{saved_test_id}")

    def post_run_saved_statistical_test(self, project_id: str, saved_test_id: str) -> Any:
        """Post Run Saved Statistical Test

        POST /api/v1/projects/{project_id}/tests/saved/{saved_test_id}/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/tests/saved/{saved_test_id}/run")

    def get_saved_statistical_test_runs(self, project_id: str, saved_test_id: str) -> Any:
        """Get Saved Statistical Test Runs

        GET /api/v1/projects/{project_id}/tests/saved/{saved_test_id}/runs
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/tests/saved/{saved_test_id}/runs")

    def read_usage(self, project_id: str, *, period_days: int | None = None) -> Any:
        """Read Usage

        GET /api/v1/projects/{project_id}/usage
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/usage", query={"period_days": period_days})

    def post_completions(self, project_id: str, connection_id: str, *, body: Any) -> Any:
        """Suggestions for a cursor position. A POST because the script is the input.

        POST /api/v1/projects/{project_id}/workbench/completions/{connection_id}
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workbench/completions/{connection_id}", body=body)

    def post_explain(self, project_id: str, *, body: Any) -> Any:
        """Post Explain

        POST /api/v1/projects/{project_id}/workbench/explain
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workbench/explain", body=body)

    def get_history(self, project_id: str, *, limit: int | None = None, mine_only: bool | None = None) -> Any:
        """What was run, and how it went. Never what it returned.

        GET /api/v1/projects/{project_id}/workbench/history
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workbench/history", query={"limit": limit, "mine_only": mine_only})

    def get_notebooks(self, project_id: str) -> Any:
        """Get Notebooks

        GET /api/v1/projects/{project_id}/workbench/notebooks
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workbench/notebooks")

    def post_notebook(self, project_id: str, *, body: Any) -> Any:
        """Post Notebook

        POST /api/v1/projects/{project_id}/workbench/notebooks
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workbench/notebooks", body=body)

    def get_one_notebook(self, project_id: str, notebook_id: str) -> Any:
        """Get One Notebook

        GET /api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}")

    def patch_notebook(self, project_id: str, notebook_id: str, *, body: Any) -> Any:
        """Patch Notebook

        PATCH /api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}", body=body)

    def delete_one_notebook(self, project_id: str, notebook_id: str) -> Any:
        """Delete One Notebook

        DELETE /api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}")

    def post_notebook_run(self, project_id: str, notebook_id: str, *, body: Any) -> Any:
        """Post Notebook Run

        POST /api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workbench/notebooks/{notebook_id}/run", body=body)

    def post_workbench_preview(self, project_id: str, *, body: Any) -> Any:
        """Split a script and say what would be allowed. Nothing runs.

        POST /api/v1/projects/{project_id}/workbench/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workbench/preview", body=body)

    def get_queries(self, project_id: str) -> Any:
        """Get Queries

        GET /api/v1/projects/{project_id}/workbench/queries
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workbench/queries")

    def post_query(self, project_id: str, *, body: Any) -> Any:
        """Post Query

        POST /api/v1/projects/{project_id}/workbench/queries
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workbench/queries", body=body)

    def patch_query(self, project_id: str, saved_id: str, *, body: Any) -> Any:
        """Patch Query

        PATCH /api/v1/projects/{project_id}/workbench/queries/{saved_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/workbench/queries/{saved_id}", body=body)

    def delete_query(self, project_id: str, saved_id: str) -> Any:
        """Delete Query

        DELETE /api/v1/projects/{project_id}/workbench/queries/{saved_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/workbench/queries/{saved_id}")

    def post_run(self, project_id: str, *, body: Any) -> Any:
        """Post Run

        POST /api/v1/projects/{project_id}/workbench/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workbench/run", body=body)

    def get_schema(self, project_id: str, connection_id: str, *, table: str | None = None, refresh: bool | None = None) -> Any:
        """The live schema. `table` loads that one's columns.

        GET /api/v1/projects/{project_id}/workbench/schema/{connection_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workbench/schema/{connection_id}", query={"table": table, "refresh": refresh})

    def get_runs(self, project_id: str, *, workflow_id: str | None = None, limit: int | None = None) -> Any:
        """Get Runs

        GET /api/v1/projects/{project_id}/workflow-runs
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workflow-runs", query={"workflow_id": workflow_id, "limit": limit})

    def compare_runs(self, project_id: str, left_run_id: str, right_run_id: str) -> Any:
        """Compare Runs

        GET /api/v1/projects/{project_id}/workflow-runs/{left_run_id}/diff/{right_run_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workflow-runs/{left_run_id}/diff/{right_run_id}")

    def get_run(self, project_id: str, run_id: str) -> Any:
        """Get Run

        GET /api/v1/projects/{project_id}/workflow-runs/{run_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workflow-runs/{run_id}")

    def post_cancel(self, project_id: str, run_id: str) -> Any:
        """Post Cancel

        POST /api/v1/projects/{project_id}/workflow-runs/{run_id}/cancel
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workflow-runs/{run_id}/cancel")

    def post_resume(self, project_id: str, run_id: str) -> Any:
        """Run a failed run again from where it failed, reusing what succeeded.

        POST /api/v1/projects/{project_id}/workflow-runs/{run_id}/resume
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workflow-runs/{run_id}/resume")

    def get_workflows(self, project_id: str) -> Any:
        """Get Workflows

        GET /api/v1/projects/{project_id}/workflows
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workflows")

    def post_workflow(self, project_id: str, *, body: Any) -> Any:
        """Post Workflow

        POST /api/v1/projects/{project_id}/workflows
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workflows", body=body)

    def get_workflow(self, project_id: str, workflow_id: str) -> Any:
        """Get Workflow

        GET /api/v1/projects/{project_id}/workflows/{workflow_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workflows/{workflow_id}")

    def patch_workflow(self, project_id: str, workflow_id: str, *, body: Any) -> Any:
        """Patch Workflow

        PATCH /api/v1/projects/{project_id}/workflows/{workflow_id}
        """
        return self._call("PATCH", f"/api/v1/projects/{project_id}/workflows/{workflow_id}", body=body)

    def remove_workflow(self, project_id: str, workflow_id: str) -> Any:
        """Remove Workflow

        DELETE /api/v1/projects/{project_id}/workflows/{workflow_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/workflows/{workflow_id}")

    def post_backfill(self, project_id: str, workflow_id: str, *, body: Any) -> Any:
        """Post Backfill

        POST /api/v1/projects/{project_id}/workflows/{workflow_id}/backfill
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workflows/{workflow_id}/backfill", body=body)

    def post_backfill_preview(self, project_id: str, workflow_id: str, *, body: Any) -> Any:
        """Show how many runs a backfill would queue, without queuing them.

        POST /api/v1/projects/{project_id}/workflows/{workflow_id}/backfill/preview
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workflows/{workflow_id}/backfill/preview", body=body)

    def post_workflow_run(self, project_id: str, workflow_id: str, *, body: Any = None) -> Any:
        """Queue a run and return immediately; a worker executes it.

        POST /api/v1/projects/{project_id}/workflows/{workflow_id}/run
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/workflows/{workflow_id}/run", body=body)

    def get_validation(self, project_id: str, workflow_id: str) -> Any:
        """Get Validation

        GET /api/v1/projects/{project_id}/workflows/{workflow_id}/validate
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/workflows/{workflow_id}/validate")

    def list_change_sets(self, project_id: str, *, limit: int | None = None) -> Any:
        """List Change Sets

        GET /api/v1/projects/{project_id}/writeback/change-sets
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/writeback/change-sets", query={"limit": limit})

    def post_change_set(self, project_id: str, *, body: Any) -> Any:
        """Post Change Set

        POST /api/v1/projects/{project_id}/writeback/change-sets
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/writeback/change-sets", body=body)

    def get_one(self, project_id: str, change_set_id: str) -> Any:
        """Get One

        GET /api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}")

    def post_commit(self, project_id: str, change_set_id: str, *, body: Any) -> Any:
        """Post Commit

        POST /api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/commit
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/commit", body=body)

    def post_discard(self, project_id: str, change_set_id: str) -> Any:
        """Post Discard

        POST /api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/discard
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/discard")

    def post_edits(self, project_id: str, change_set_id: str, *, body: Any) -> Any:
        """Post Edits

        POST /api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/edits
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/edits", body=body)

    def delete_edit(self, project_id: str, change_set_id: str, edit_id: str) -> Any:
        """Delete Edit

        DELETE /api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/edits/{edit_id}
        """
        return self._call("DELETE", f"/api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/edits/{edit_id}")

    def get_migration(self, project_id: str, change_set_id: str) -> Any:
        """The same SQL, as a file to review and run through change control.

        GET /api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/migration
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/migration")

    def post_plan(self, project_id: str, change_set_id: str) -> Any:
        """Rehearse inside a transaction that is always rolled back.

        POST /api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/plan
        """
        return self._call("POST", f"/api/v1/projects/{project_id}/writeback/change-sets/{change_set_id}/plan")

    def get_rows(self, project_id: str, connection_id: str, *, table: str, table_schema: str | None = None, key: list[Any] | None = None, limit: int | None = None, offset: int | None = None, order_by: str | None = None, descending: bool | None = None) -> Any:
        """Live rows in a stable order, so the same cell stays the same cell.

        GET /api/v1/projects/{project_id}/writeback/rows/{connection_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/writeback/rows/{connection_id}", query={"table": table, "table_schema": table_schema, "key": key, "limit": limit, "offset": offset, "order_by": order_by, "descending": descending})

    def get_table_shape(self, project_id: str, connection_id: str, *, table: str, table_schema: str | None = None, key: list[Any] | None = None) -> Any:
        """Can this table be edited, and by what key? Answered before any editing.

        GET /api/v1/projects/{project_id}/writeback/tables/{connection_id}
        """
        return self._call("GET", f"/api/v1/projects/{project_id}/writeback/tables/{connection_id}", query={"table": table, "table_schema": table_schema, "key": key})

    def shared_dashboard(self, token: str) -> Any:
        """Shared Dashboard

        GET /api/v1/public/dashboards/{token}
        """
        return self._call("GET", f"/api/v1/public/dashboards/{token}")

    def embedded_dashboard_view(self, token: str) -> Any:
        """A dashboard by its embed link (A8, Y4): 404 when the link is not valid or the embed was turned off, 410 when it has run out.

        GET /api/v1/public/embeds/{token}
        """
        return self._call("GET", f"/api/v1/public/embeds/{token}")

    def recent_runs(self, *, status: str | None = None, limit: int | None = None) -> Any:
        """Recent Runs

        GET /api/v1/runs
        """
        return self._call("GET", "/api/v1/runs", query={"status": status, "limit": limit})

    def list_samples(self) -> Any:
        """List Samples

        GET /api/v1/samples
        """
        return self._call("GET", "/api/v1/samples")

    def sso(self) -> Any:
        """What single sign-on is available, and what is not.

        GET /api/v1/sso/status
        """
        return self._call("GET", "/api/v1/sso/status")

    def get_platform_status(self) -> Any:
        """Get Platform Status

        GET /api/v1/status
        """
        return self._call("GET", "/api/v1/status")

    def get_service_statuses(self) -> Any:
        """Get Service Statuses

        GET /api/v1/status/services
        """
        return self._call("GET", "/api/v1/status/services")

    def get_support_contact(self) -> Any:
        """Where to get help, and which version is running. Readable without signing in.

        GET /api/v1/status/support
        """
        return self._call("GET", "/api/v1/status/support")

    def get_recipe_templates(self) -> Any:
        """Get Recipe Templates

        GET /api/v1/transformations/templates
        """
        return self._call("GET", "/api/v1/transformations/templates")

    def post_match_recipe_templates(self, *, body: Any) -> Any:
        """Each template, with the columns it would use here and what it lacks.

        POST /api/v1/transformations/templates/match
        """
        return self._call("POST", "/api/v1/transformations/templates/match", body=body)

    def post_recipe_template_steps(self, template_id: str, *, body: Any) -> Any:
        """Post Recipe Template Steps

        POST /api/v1/transformations/templates/{template_id}/steps
        """
        return self._call("POST", f"/api/v1/transformations/templates/{template_id}/steps", body=body)

    def get_tools(self, *, query: str | None = None, category: str | None = None, column_type: str | None = None, limit: int | None = None) -> Any:
        """Get Tools

        GET /api/v1/transformations/tools
        """
        return self._call("GET", "/api/v1/transformations/tools", query={"query": query, "category": category, "column_type": column_type, "limit": limit})

    def post_tool_preview(self, *, body: Any) -> Any:
        """Run one tool over supplied rows, so the UI can show its effect.

        POST /api/v1/transformations/tools/preview
        """
        return self._call("POST", "/api/v1/transformations/tools/preview", body=body)

    def post_recipe_parse(self, *, body: Any) -> Any:
        """Post Recipe Parse

        POST /api/v1/workbench/recipe/parse
        """
        return self._call("POST", "/api/v1/workbench/recipe/parse", body=body)

    def post_recipe_yaml(self, *, body: Any) -> Any:
        """Post Recipe Yaml

        POST /api/v1/workbench/recipe/yaml
        """
        return self._call("POST", "/api/v1/workbench/recipe/yaml", body=body)

    def get_sandbox(self) -> Any:
        """What this deployment can enforce, and what it therefore refuses.

        GET /api/v1/workbench/sandbox
        """
        return self._call("GET", "/api/v1/workbench/sandbox")

    def get_macros(self) -> Any:
        """Macros available inside node configuration.

        GET /api/v1/workflows/macros
        """
        return self._call("GET", "/api/v1/workflows/macros")
