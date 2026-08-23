/**
 * Sidebar navigation.
 *
 * `badge` states honestly what each destination is. The working product
 * surfaces (extraction, pipelines, data quality, schema drift, destinations,
 * schedules) are project-scoped and reached from a project workspace, so the
 * top-level entries below that are still placeholders say so.
 */
export const navigationItems = [
  { label: "Overview", href: "/", badge: "Live" },
  { label: "Projects", href: "/projects", badge: "Live" },
  { label: "System status", href: "/system-status", badge: "Ops" },
  { label: "Demo", href: "/demo", badge: "Guide" },
  { label: "Case study", href: "/case-study", badge: "Brief" },
  { label: "Datasets", href: "/datasets", badge: "Planned" },
  { label: "Pipeline Builder", href: "/pipelines", badge: "Planned" },
  { label: "Audit Center", href: "/audits", badge: "Planned" },
  { label: "Testing Lab", href: "/testing", badge: "Planned" },
  { label: "Integration Hub", href: "/integrations", badge: "Planned" },
  { label: "Settings", href: "/settings", badge: "Planned" },
] as const;
