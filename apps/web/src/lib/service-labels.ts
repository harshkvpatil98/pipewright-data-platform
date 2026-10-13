/**
 * What each platform module is called on screen.
 *
 * The status endpoint reports modules by their package names
 * ("service-observability"), which mean something to the people who run the
 * platform and nothing to anyone else. This is the one place they become
 * words; an unknown name still shows, prettified, rather than vanishing.
 */

const SERVICE_LABELS: Record<string, string> = {
  postgres: "Database",
  "service-auth": "Sign-in",
  "service-projects": "Projects",
  "service-access": "Permissions",
  "service-enterprise": "Security",
  "service-governance": "Approvals and audit",
  "service-sources": "Source registry",
  "service-connectors": "Connectors",
  "service-datasets": "Datasets",
  "service-destinations": "Destinations",
  "service-ingestion": "File uploads",
  "service-extraction": "Database imports",
  "service-quality": "Checks",
  "service-pipeline-runs": "Runs",
  "service-transformations": "Recipes",
  "service-workflows": "Workflows",
  "service-writeback": "Table editor",
  "service-workbench": "SQL and notebooks",
  "service-lineage": "Lineage",
  "service-intelligence": "Data suggestions",
  "service-observability": "Monitoring",
  "service-reporting": "Dashboards and reports",
  "service-comparisons": "Comparisons",
  "service-schedules": "Schedules",
  "service-notifications": "Notifications",
};

export function serviceLabel(name: string): string {
  const known = SERVICE_LABELS[name];
  if (known) return known;
  const spaced = name.replace(/^service-/, "").replace(/[-_]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
