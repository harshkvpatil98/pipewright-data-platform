import type { TourStep } from "@/components/tour/tour-provider";

/**
 * Tour definitions.
 *
 * Each `target` matches a `data-tour` attribute in the shell or a page. Steps
 * are written to teach the workflow, not to label the furniture -- a step earns
 * its place only if it tells a first-time user something they could not guess.
 */

export const WELCOME_TOUR_ID = "welcome-v1";

export const welcomeTour: TourStep[] = [
  {
    target: "",
    placement: "center",
    title: "Welcome to Pipewright",
    body: "A quick tour of how data moves through the platform: connect a source, shape it, prove it is correct, then publish. Takes about 40 seconds.",
  },
  {
    target: "nav-rail",
    placement: "right",
    title: "Your workspace",
    body: "Everything lives here. Each icon is a stage of the pipeline — sources on top, delivery at the bottom, in the order data flows.",
  },
  {
    target: "ribbon",
    placement: "bottom",
    title: "The ribbon changes with context",
    body: "Actions for whatever you are looking at appear here, grouped by task. Open a dataset and you get transform tools; open a connection and you get extraction tools.",
  },
  {
    target: "command-trigger",
    placement: "bottom",
    title: "Jump anywhere instantly",
    body: "Press ⌘K (Ctrl+K on Windows) to search every page and action. It is the fastest way to move around once you know your way.",
  },
  {
    target: "inspector-toggle",
    placement: "left",
    title: "Details on the right",
    body: "The inspector shows properties, schema, and run history for the current selection. Collapse it any time you want more canvas.",
  },
  {
    target: "status-bar",
    placement: "top",
    title: "Live system state",
    body: "Connection health, row counts, and the last run outcome stay visible while you work, so you notice a broken pipeline before someone else does.",
  },
  {
    target: "help-trigger",
    placement: "left",
    title: "That is the tour",
    body: "Replay it any time from this help menu. Start by opening a project and connecting a data source.",
  },
];

export const STUDIO_TOUR_ID = "studio-v1";

export const studioTour: TourStep[] = [
  {
    target: "studio-source",
    placement: "right",
    title: "Pick your input",
    body: "Choose the dataset you want to shape. Its rows load into the grid immediately so you can see what you are working with.",
  },
  {
    target: "ribbon",
    placement: "bottom",
    title: "Apply a transformation",
    body: "Every tool here adds one step to your pipeline. Nothing is destructive — the source dataset is never modified.",
  },
  {
    target: "applied-steps",
    placement: "left",
    title: "Steps stack in order",
    body: "Each step runs on the output of the one before it. Remove or reorder any step and the preview recalculates instantly.",
  },
  {
    target: "studio-preview",
    placement: "top",
    title: "Live preview",
    body: "This is the real result of your steps, computed on the server against actual data — not a mock-up. Save it as a pipeline when it looks right.",
  },
];

export const DATA_QUALITY_TOUR_ID = "data-quality-v1";

export const dataQualityTour: TourStep[] = [
  {
    target: "",
    placement: "center",
    title: "Prove your data is correct",
    body: "Data quality rules assert what must always be true — a column is never empty, a value stays in range, every row is unique. This is how you catch a bad load before it reaches a dashboard.",
  },
  {
    target: "dq-define",
    placement: "right",
    title: "Define a rule",
    body: "Pick a rule type and the form shows only the fields that type needs — a column to check, an allowed range, a pattern. Severity decides whether a failure blocks the pipeline or just warns.",
  },
  {
    target: "dq-evaluate",
    placement: "top",
    title: "Run it against a dataset",
    body: "Every enabled rule that applies to the dataset runs at once. Turn on quarantine and failing rows are split into their own dataset instead of flowing downstream — the good rows still move.",
  },
];

export const SCHEDULES_TOUR_ID = "schedules-v1";

export const schedulesTour: TourStep[] = [
  {
    target: "",
    placement: "center",
    title: "Put it on a schedule",
    body: "A schedule runs a pipeline or a publish on a recurrence you set, so the work happens without anyone clicking Run. This is the last step from a one-off transform to a living pipeline.",
  },
  {
    target: "schedules-create",
    placement: "bottom",
    title: "Create a schedule",
    body: "Give it a standard five-field cron expression and point it at a pipeline run or a PostgreSQL publish. The executor runs it automatically once its next run time is due.",
  },
  {
    target: "schedules-list",
    placement: "top",
    title: "Watch and override",
    body: "Saved schedules show their next run and last outcome here. Trigger now forces an immediate run for testing without advancing the cron slot, so the regular cadence is undisturbed.",
  },
];
