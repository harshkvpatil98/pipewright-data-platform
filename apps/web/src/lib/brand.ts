/**
 * Single source of truth for product naming. Everything user-facing reads from
 * here so the product can be renamed in one place.
 */
export const brand = {
  name: "Pipewright",
  /** Kept short so it sits on one line beside the mark in the sidebar. */
  tagline: "Data Pipelines",
  /** Used for page titles and meta description. */
  description:
    "Pipewright is a production data pipeline platform: database and file extraction, incremental loading, joins and aggregations, data quality rules, schema drift detection, scheduling, and BI publishing.",
  shortDescription: "Extract, transform, validate, and publish data with full run lineage.",
} as const;

export const appName = process.env.NEXT_PUBLIC_APP_NAME ?? brand.name;
