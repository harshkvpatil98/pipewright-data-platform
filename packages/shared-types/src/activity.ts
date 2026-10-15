/** What happened in a project, in one stream (A8, Y6). */

export const ACTIVITY_KINDS = ["changes", "runs", "incidents", "comments", "alerts", "contracts"] as const;
export type ActivityKind = (typeof ACTIVITY_KINDS)[number];

export type ActivityItem = {
  id: string;
  kind: ActivityKind;
  at: string;
  who: string | null;
  /** "Ann deleted a dashboard", "Recipe run failed". */
  sentence: string;
  /** What it was about: a name, a quoted comment, an alert's message. */
  detail: string | null;
  level: "info" | "success" | "warning" | "error";
  /** The page it is about, from the site's root. */
  href: string | null;
};

export type ActivityResponse = {
  items: ActivityItem[];
  /** Pass as `offset` for the next, older page; null when there is no more. */
  next_offset: number | null;
};
