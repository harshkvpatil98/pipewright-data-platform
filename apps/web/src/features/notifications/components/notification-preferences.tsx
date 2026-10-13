"use client";

import { useEffect, useState } from "react";

import type { NotificationPreference, NotificationPreferencesResponse } from "@platform/shared-types";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

const MODE_LABELS: Record<NotificationPreference["mode"], string> = {
  each: "Each one",
  digest: "Daily summary",
  off: "Off",
};

/**
 * One row per kind of notification, with three choices. Saved the moment it
 * changes: a settings page with a separate Save button for each switch is a
 * page people leave without saving.
 */
export function NotificationPreferences() {
  const [items, setItems] = useState<NotificationPreference[] | null>(null);
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    apiFetch<NotificationPreferencesResponse>("/notifications/preferences")
      .then((response) => setItems(response.items))
      .catch((caught) => setError(extractErrorMessage(caught)));
  }, []);

  const choose = async (category: string, mode: NotificationPreference["mode"]) => {
    setSaving(category);
    setError(null);
    try {
      const response = await apiFetch<NotificationPreferencesResponse>("/notifications/preferences", {
        method: "PUT",
        body: JSON.stringify({ category, mode }),
      });
      setItems(response.items);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setSaving(null);
    }
  };

  if (error && !items) {
    return <p className="px-4 py-3 text-[13px] text-danger">{error}</p>;
  }
  if (!items) {
    return <p className="px-4 py-3 text-[13px] text-muted">Loading…</p>;
  }

  return (
    <>
      {error ? <p className="px-4 py-3 text-[13px] text-danger">{error}</p> : null}
      {items.map((item) => (
        <div key={item.category} className="flex flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="min-w-0">
            <div className="text-[14px] text-ink">{item.label}</div>
            <div className="text-[12.5px] text-muted">{item.description}</div>
          </div>
          <div
            role="radiogroup"
            aria-label={item.label}
            className={cx("flex rounded-lg border border-line p-0.5", saving === item.category && "opacity-60")}
          >
            {(Object.keys(MODE_LABELS) as NotificationPreference["mode"][]).map((mode) => (
              <button
                key={mode}
                type="button"
                role="radio"
                aria-checked={item.mode === mode}
                disabled={saving !== null}
                onClick={() => void choose(item.category, mode)}
                className={cx(
                  "rounded-md px-2.5 py-1.5 text-[13px] transition",
                  item.mode === mode
                    ? "bg-[color:var(--accent)] text-accent-ink"
                    : "text-ink-3 hover:text-ink",
                )}
              >
                {MODE_LABELS[mode]}
              </button>
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
