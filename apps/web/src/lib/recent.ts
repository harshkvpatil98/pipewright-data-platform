/**
 * Things the user opened recently, for the command palette.
 *
 * Kept per browser in localStorage: it is a convenience, not a record, and a
 * private window or cleared storage simply starts empty.
 */

const STORAGE_KEY = "pipewright.recent";
const LIMIT = 8;

export type RecentItem = {
  href: string;
  label: string;
  /** Where it lives, e.g. "Datasets", shown as the palette row's caption. */
  where: string;
};

export function readRecent(): RecentItem[] {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : [];
    return Array.isArray(parsed)
      ? parsed.filter(
          (item): item is RecentItem =>
            typeof item?.href === "string" && typeof item?.label === "string",
        )
      : [];
  } catch {
    return [];
  }
}

/** Newest first, one entry per address. */
export function withRecent(items: RecentItem[], item: RecentItem): RecentItem[] {
  return [item, ...items.filter((existing) => existing.href !== item.href)].slice(0, LIMIT);
}

export function recordRecent(item: RecentItem): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(withRecent(readRecent(), item)));
  } catch {
    /* storage unavailable: nothing to remember */
  }
}
