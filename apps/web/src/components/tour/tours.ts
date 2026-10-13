import type { TourStep } from "@/components/tour/tour-provider";

/**
 * Tour definitions.
 *
 * Each `target` matches a `data-tour` attribute in the shell or a page. Steps
 * are written to teach the workflow, not to label the furniture -- a step earns
 * its place only if it tells a first-time user something they could not guess.
 */

// v2: the navigation was rebuilt around six areas (adoption-readiness A1), so
// everyone sees the tour once more rather than keeping a picture of a layout
// that no longer exists.
export const WELCOME_TOUR_ID = "welcome-v2";

export const welcomeTour: TourStep[] = [
  {
    target: "",
    placement: "center",
    title: "Welcome to Pipewright",
    body: "Bring data in, clean it, check it and share it. This takes about half a minute.",
  },
  {
    target: "project-switcher",
    placement: "bottom",
    title: "Everything lives in a project",
    body: "A project keeps one team's or one subject's data together. Switch projects or start a new one here.",
  },
  {
    target: "nav-rail",
    placement: "right",
    title: "Six areas, in the order data moves",
    body: "Data brings it in. Build cleans it. Automate keeps it running. Trust checks it. Share shows it to everyone else.",
  },
  {
    target: "area-tabs",
    placement: "bottom",
    title: "Each area has tabs",
    body: "Related pages sit side by side here, so nothing is more than two clicks away.",
  },
  {
    target: "command-trigger",
    placement: "bottom",
    title: "Search for anything",
    body: "Press ⌘K (Ctrl+K on Windows) to jump to any page, dataset or dashboard by name.",
  },
  {
    target: "help-trigger",
    placement: "left",
    title: "Help is always here",
    body: "Replay this tour, see keyboard shortcuts or check that everything is running. A good first step: add some data from the Overview.",
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
    body: "Every tool here adds one step to your recipe. Your original dataset is never changed.",
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
    body: "This is the real result of your steps on your actual data. Save it as a recipe when it looks right.",
  },
];

export const DATA_QUALITY_TOUR_ID = "data-quality-v1";

export const dataQualityTour: TourStep[] = [
  {
    target: "",
    placement: "center",
    title: "Check your data is right",
    body: "A check says what must always be true: a column is never empty, a value stays in range, every row is unique. It catches a bad load before it reaches a dashboard.",
  },
  {
    target: "dq-define",
    placement: "right",
    title: "Add a check",
    body: "Pick a kind of check and the form asks only for what it needs: a column, an allowed range, a pattern. Severity decides whether a failure stops the run or just warns.",
  },
  {
    target: "dq-evaluate",
    placement: "top",
    title: "Run it against a dataset",
    body: "Every check on the dataset runs at once. Turn on quarantine and failing rows are set aside in their own dataset, while the good rows carry on.",
  },
];

export const SCHEDULES_TOUR_ID = "schedules-v1";

export const schedulesTour: TourStep[] = [
  {
    target: "",
    placement: "center",
    title: "Put it on a schedule",
    body: "A schedule runs a recipe or a delivery at the times you set, so the work happens without anyone clicking Run.",
  },
  {
    target: "schedules-create",
    placement: "bottom",
    title: "Create a schedule",
    body: "Choose how often it runs (every day, every hour, or your own pattern) and what it runs. It starts by itself when the time comes.",
  },
  {
    target: "schedules-list",
    placement: "top",
    title: "Watch and override",
    body: "Each schedule shows when it runs next and how the last run went. Run now tries it straight away without changing its timetable.",
  },
];
