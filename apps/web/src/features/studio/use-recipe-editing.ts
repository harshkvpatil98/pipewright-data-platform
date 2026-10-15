"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { apiFetch } from "@/lib/api/client";
import { ApiError } from "@/lib/api/errors";

import {
  Clock,
  type Doc,
  type Op,
  type Stamp,
  type Unstamped,
  applyOps,
  diff,
  inverse,
  materialise,
  maxCounter,
  seed,
  stableJson,
  undoable,
} from "./coedit";
import type { TimelineStep } from "./steps-timeline";

/** How often a Studio asks for others' changes, and sends its own. */
export const POLL_MS = 2000;
const SEND_MS = 300;
/** Typing into one setting folds into one undo step until a pause this long. */
const FOLD_MS = 1000;
const UNDO_LIMIT = 100;

type UndoEntry = { entries: { op: Unstamped; after: Stamp }[]; group: string | null; at: number };

export type SavedRecipe = {
  revision: number;
  name: string;
  steps: TimelineStep[];
  revisedBy: string | null;
  revisedAt: string | null;
};

type Batch = { seq: number; client_id: string; actor: string | null; ops: Op[] };

type SharedCopy = {
  epoch: number;
  seq: number;
  doc: Doc | null;
  batches: Batch[];
  saved: {
    revision: number;
    name: string;
    steps_json: { step_type: string; config: Record<string, unknown> }[];
    step_ids: string[];
    revised_by: string | null;
    revised_at: string | null;
  } | null;
  revision: number;
  reset_reason: string | null;
  your_role: "viewer" | "operator" | "editor" | "admin" | null;
  needs_approval: boolean;
  open_suggestions: number;
};

export type SharedState = {
  yourRole: SharedCopy["your_role"];
  needsApproval: boolean;
  openSuggestions: number;
};

/** A stable id for a new step, unique across everyone's browsers. */
export function newStepId(): string {
  return crypto.randomUUID().replace(/-/g, "");
}

const signature = (name: string, steps: TimelineStep[]) =>
  stableJson([name.trim(), steps.map((step) => [step.uid, step.step_type, step.config])]);

const registerKey = (op: Unstamped) =>
  op.k === "name" ? "name" : op.k === "set" ? `${op.id}:cfg:${op.key}` : op.k === "del" ? `${op.id}:del` : `${op.id}:pos`;

/** Fold a newer undo entry into an older one: the older "before" wins, the newer stamp is what to look for. */
function fold(older: UndoEntry, newer: UndoEntry): UndoEntry {
  const merged = new Map(older.entries.map((entry) => [registerKey(entry.op), entry]));
  for (const entry of newer.entries) {
    const key = registerKey(entry.op);
    const existing = merged.get(key);
    merged.set(key, existing ? { op: existing.op, after: entry.after } : entry);
  }
  return { entries: [...merged.values()], group: newer.group, at: newer.at };
}

export type RemoteNote = { who: string | null; at: number };

/**
 * The recipe being edited in the Studio (C2).
 *
 * `live` (a saved recipe, and someone who may edit it): the working copy is
 * the one shared on the server; changes go out as they happen and others'
 * come in every two seconds. Otherwise the copy is this browser's alone (a
 * new recipe, or someone suggesting a change), with the same undo.
 */
export function useRecipeEditing(options: {
  projectId: string;
  recipeId: string | null;
  initialName: string;
  initialSteps: TimelineStep[];
  live: boolean;
  /** The saved recipe's revision when the page opened, if it is saved. */
  initialRevision: number | null;
  /** The shared copy as the page opened with it, so nothing flashes. */
  initialDoc?: Doc | null;
}) {
  const { projectId, recipeId, live } = options;
  const clientId = useRef<string>("");
  if (!clientId.current) clientId.current = newStepId();
  const clock = useRef<Clock>(new Clock(clientId.current));
  const docRef = useRef<Doc>(options.initialDoc ?? seed(options.initialName, options.initialSteps));
  if (options.initialDoc && clock.current) clock.current.observe(maxCounter(options.initialDoc));
  const [doc, setDoc] = useState<Doc>(docRef.current);
  const undoStack = useRef<UndoEntry[]>([]);
  const redoStack = useRef<UndoEntry[]>([]);
  const [undoDepth, setUndoDepth] = useState({ undo: 0, redo: 0 });
  const pending = useRef<Op[]>([]);
  const epoch = useRef<number | null>(null);
  const seq = useRef<number | null>(null);
  const [saved, setSaved] = useState<SavedRecipe | null>(
    options.initialRevision !== null
      ? {
          revision: options.initialRevision,
          name: options.initialName,
          steps: options.initialSteps,
          revisedBy: null,
          revisedAt: null,
        }
      : null,
  );
  const [shared, setShared] = useState<SharedState | null>(null);
  const [connected, setConnected] = useState(!live);
  const [resetReason, setResetReason] = useState<string | null>(null);
  const [remote, setRemote] = useState<RemoteNote | null>(null);
  const [savedBySomeoneElse, setSavedBySomeoneElse] = useState<SavedRecipe | null>(null);
  /** What this Studio showed when the copy started again without it. */
  const [setAside, setSetAside] = useState<{ name: string; steps: TimelineStep[] } | null>(null);

  const publish = useCallback((next: Doc) => {
    docRef.current = next;
    setDoc(next);
  }, []);

  const syncDepth = () => setUndoDepth({ undo: undoStack.current.length, redo: redoStack.current.length });

  const commit = useCallback(
    (ops: Op[], record: { group: string | null } | "undo" | "redo") => {
      if (ops.length === 0) return;
      const before = docRef.current;
      const after = applyOps(before, ops);
      const entry: UndoEntry = {
        entries: inverse(before, ops),
        group: record === "undo" || record === "redo" ? null : record.group,
        at: Date.now(),
      };
      if (record === "undo") {
        redoStack.current = [...redoStack.current, entry].slice(-UNDO_LIMIT);
      } else if (record === "redo") {
        undoStack.current = [...undoStack.current, entry].slice(-UNDO_LIMIT);
      } else {
        const last = undoStack.current[undoStack.current.length - 1];
        if (last && entry.group !== null && last.group === entry.group && entry.at - last.at < FOLD_MS) {
          undoStack.current = [...undoStack.current.slice(0, -1), fold(last, entry)];
        } else {
          undoStack.current = [...undoStack.current, entry].slice(-UNDO_LIMIT);
        }
        redoStack.current = [];
      }
      syncDepth();
      if (live) pending.current = [...pending.current, ...ops];
      publish(after);
    },
    [live, publish],
  );

  // The same list until the copy changes: the Studio previews whenever its
  // steps change, and a new list each render previewed without end.
  const shown = useMemo(() => materialise(doc), [doc]);
  const steps = shown.steps;
  const name = shown.name ?? options.initialName;

  /** Change the steps: `next` gets the steps as they are now. */
  const change = useCallback(
    (next: (current: TimelineStep[]) => TimelineStep[], group?: string) => {
      const current = materialise(docRef.current);
      const target = next(current.steps);
      if (target === current.steps) return;
      commit(diff(docRef.current, { name: null, steps: target }, clock.current), { group: group ?? null });
    },
    [commit],
  );

  const rename = useCallback(
    (value: string) => {
      const current = materialise(docRef.current);
      commit(diff(docRef.current, { name: value, steps: current.steps }, clock.current), { group: "name" });
    },
    [commit],
  );

  const undo = useCallback(() => {
    const entry = undoStack.current[undoStack.current.length - 1];
    if (!entry) return;
    undoStack.current = undoStack.current.slice(0, -1);
    commit(undoable(docRef.current, entry.entries, clock.current), "undo");
    syncDepth();
  }, [commit]);

  const redo = useCallback(() => {
    const entry = redoStack.current[redoStack.current.length - 1];
    if (!entry) return;
    redoStack.current = redoStack.current.slice(0, -1);
    commit(undoable(docRef.current, entry.entries, clock.current), "redo");
    syncDepth();
  }, [commit]);

  // ------------------------------------------------------------ the shared copy
  const adoptSaved = useCallback((copy: SharedCopy) => {
    if (!copy.saved) return null;
    const next: SavedRecipe = {
      revision: copy.saved.revision,
      name: copy.saved.name,
      steps: copy.saved.steps_json.map((step, index) => ({
        uid: copy.saved?.step_ids[index] ?? newStepId(),
        step_type: step.step_type,
        config: step.config ?? {},
      })),
      revisedBy: copy.saved.revised_by,
      revisedAt: copy.saved.revised_at,
    };
    setSaved(next);
    return next;
  }, []);

  const adopt = useCallback(
    (copy: SharedCopy, mine: boolean) => {
      setShared({ yourRole: copy.your_role, needsApproval: copy.needs_approval, openSuggestions: copy.open_suggestions });
      const before = docRef.current;
      if (copy.doc) {
        const fresh = copy.doc as Doc;
        clock.current.observe(maxCounter(fresh));
        if (epoch.current !== null && epoch.current !== copy.epoch) {
          // Changed outside the Studio: the copy started again. What this
          // Studio showed is kept, so it can be offered back as a draft.
          setResetReason(copy.reset_reason ?? "This recipe was changed outside the Studio.");
          const was = materialise(before);
          const now = materialise(fresh);
          if (signature(was.name ?? "", was.steps) !== signature(now.name ?? "", now.steps)) {
            setSetAside({ name: was.name ?? "", steps: was.steps });
          }
          undoStack.current = [];
          redoStack.current = [];
          syncDepth();
        }
        pending.current = [];
        publish(fresh);
      } else if (copy.batches.length) {
        let next = docRef.current;
        let lastOther: Batch | null = null;
        for (const batch of copy.batches) {
          for (const op of batch.ops) clock.current.observe(op.s[0]);
          next = applyOps(next, batch.ops);
          if (batch.client_id !== clientId.current) lastOther = batch;
        }
        // Our own unsent changes stay on top; merging is order-free.
        publish(applyOps(next, pending.current));
        if (lastOther) setRemote({ who: lastOther.actor, at: Date.now() });
      }
      epoch.current = copy.epoch;
      seq.current = copy.seq;
      const fresh = adoptSaved(copy);
      if (fresh && !mine && fresh.revisedBy) setSavedBySomeoneElse(fresh);
    },
    [adoptSaved, publish],
  );

  const revisionRef = useRef<number | null>(options.initialRevision);
  useEffect(() => {
    revisionRef.current = saved?.revision ?? null;
  }, [saved]);

  const poll = useCallback(
    async (full = false) => {
      if (!live || !recipeId) return;
      const query = new URLSearchParams();
      if (!full && epoch.current !== null && seq.current !== null) {
        query.set("epoch", String(epoch.current));
        query.set("after", String(seq.current));
      }
      if (!full && revisionRef.current !== null) query.set("revision", String(revisionRef.current));
      const copy = await apiFetch<SharedCopy>(`/projects/${projectId}/pipelines/${recipeId}/shared?${query}`);
      adopt(copy, false);
      setConnected(true);
    },
    [live, recipeId, projectId, adopt],
  );

  const sending = useRef(false);
  const flush = useCallback(async () => {
    if (!live || !recipeId || sending.current || pending.current.length === 0 || epoch.current === null) return;
    sending.current = true;
    const ops = pending.current;
    pending.current = [];
    try {
      await apiFetch(`/projects/${projectId}/pipelines/${recipeId}/shared`, {
        method: "POST",
        body: JSON.stringify({ epoch: epoch.current, client_id: clientId.current, ops }),
      });
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 409) {
        await poll(true).catch(() => undefined);
      } else {
        // Not delivered: they go again with the next changes.
        pending.current = [...ops, ...pending.current];
      }
    } finally {
      sending.current = false;
    }
  }, [live, recipeId, projectId, poll]);

  useEffect(() => {
    if (!live || !recipeId) return;
    let stopped = false;
    void poll(true).catch(() => setConnected(false));
    const asking = setInterval(() => {
      if (!stopped && document.visibilityState !== "hidden") void poll().catch(() => setConnected(false));
    }, POLL_MS);
    const sendingTimer = setInterval(() => void flush(), SEND_MS);
    return () => {
      stopped = true;
      clearInterval(asking);
      clearInterval(sendingTimer);
      void flush();
    };
  }, [live, recipeId, poll, flush]);

  /** What a save sends: the copy as it is, with its step ids and epoch. */
  const forSaving = useCallback(() => {
    const current = materialise(docRef.current);
    return {
      name: current.name ?? options.initialName,
      steps: current.steps,
      epoch: epoch.current,
      revision: revisionRef.current,
    };
  }, [options.initialName]);

  /** After a save: the saved recipe is now the copy as it was sent. */
  const markSaved = useCallback(
    async (revision: number, savedName: string, savedSteps: TimelineStep[]) => {
      setSaved({ revision, name: savedName, steps: savedSteps, revisedBy: null, revisedAt: new Date().toISOString() });
      revisionRef.current = revision;
      await flush();
    },
    [flush],
  );

  /** Start again from the saved recipe (a draft offered back, a discard). */
  const replaceWith = useCallback(
    (nextName: string, nextSteps: TimelineStep[]) => {
      commit(diff(docRef.current, { name: nextName, steps: nextSteps }, clock.current), { group: null });
    },
    [commit],
  );

  const dirty = useMemo(
    () => (saved === null ? steps.length > 0 : signature(name, steps) !== signature(saved.name, saved.steps)),
    [saved, name, steps],
  );

  return {
    clientId: clientId.current,
    name,
    steps,
    change,
    rename,
    undo,
    redo,
    canUndo: undoDepth.undo > 0,
    canRedo: undoDepth.redo > 0,
    saved,
    dirty,
    shared,
    connected,
    resetReason,
    clearResetReason: () => setResetReason(null),
    setAside,
    clearSetAside: () => setSetAside(null),
    remote,
    savedBySomeoneElse,
    clearSavedBySomeoneElse: () => setSavedBySomeoneElse(null),
    forSaving,
    markSaved,
    replaceWith,
    refresh: () => poll(true),
  };
}
