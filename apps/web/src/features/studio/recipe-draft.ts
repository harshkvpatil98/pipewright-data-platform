/**
 * Unsaved Studio work, kept in this browser until it is saved or discarded.
 *
 * A session that ends, a tab closed by mistake or a crash would otherwise take
 * every unsaved step with it. The draft is per viewer and per browser by
 * design: it is a safety net, not a way to share work (saving is).
 */

export type RecipeDraft = {
  name: string;
  steps: { step_type: string; config: Record<string, unknown> }[];
  at: number;
};

const PREFIX = "pipewright.studio.draft";
const KEEP_FOR_MS = 7 * 24 * 60 * 60 * 1000;

export function draftKey(projectId: string, recipeId: string | null, datasetId: string): string {
  return `${PREFIX}:${projectId}:${recipeId ?? `new:${datasetId}`}`;
}

export function readDraft(key: string, now = Date.now()): RecipeDraft | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const draft = JSON.parse(raw) as RecipeDraft;
    if (!Array.isArray(draft.steps) || typeof draft.at !== "number" || now - draft.at > KEEP_FOR_MS) {
      window.localStorage.removeItem(key);
      return null;
    }
    return draft;
  } catch {
    return null;
  }
}

export function writeDraft(key: string, draft: RecipeDraft): void {
  try {
    window.localStorage.setItem(key, JSON.stringify(draft));
  } catch {
    /* storage full or unavailable: the draft is a convenience */
  }
}

export function clearDraft(key: string): void {
  try {
    window.localStorage.removeItem(key);
  } catch {
    /* nothing to clear */
  }
}
