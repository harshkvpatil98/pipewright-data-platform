"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { DatasetActivityItem, DatasetActivityResponse } from "@platform/shared-types";
import { Button, SectionPanel } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDateTime } from "@/lib/format";
import { cx } from "@/lib/utils";

const LEVEL_DOT: Record<DatasetActivityItem["level"], string> = {
  info: "bg-ink-3",
  success: "bg-success",
  warning: "bg-warning",
  error: "bg-danger",
};

/**
 * What happened to one dataset, newest first (C2): each new version and
 * what made it, runs that failed to make one, checks, schema changes,
 * contract problems, alerts, incidents, comments and changes to it.
 */
export function DatasetFeedPanel({ projectId, datasetId }: { projectId: string; datasetId: string }) {
  const [items, setItems] = useState<DatasetActivityItem[] | null>(null);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (offset: number) => {
      setBusy(true);
      setError(null);
      try {
        const page = await apiFetch<DatasetActivityResponse>(
          `/projects/${projectId}/datasets/${datasetId}/activity?offset=${offset}`,
        );
        setItems((current) => {
          if (offset === 0 || current === null) return page.items;
          const seen = new Set(current.map((item) => item.id));
          return [...current, ...page.items.filter((item) => !seen.has(item.id))];
        });
        setNextOffset(page.next_offset);
      } catch (caught) {
        setError(extractErrorMessage(caught));
      } finally {
        setBusy(false);
      }
    },
    [projectId, datasetId],
  );

  useEffect(() => {
    void load(0);
  }, [load]);

  return (
    <SectionPanel
      title="What happened to it"
      description="Newest first: each version and what made it, checks, contracts, alerts and comments."
    >
      {error ? <p className="text-sm text-danger">{error}</p> : null}
      {items === null ? (
        <p className="text-[13px] text-ink-3">Loading…</p>
      ) : items.length === 0 ? (
        <p className="text-[13px] text-ink-3">Nothing has happened to this dataset yet.</p>
      ) : (
        <ol className="divide-y divide-line">
          {items.map((item) => (
            <li key={item.id} className="flex items-start gap-3 py-2.5">
              <span className={cx("mt-1.5 h-2 w-2 shrink-0 rounded-full", LEVEL_DOT[item.level])} aria-hidden />
              <div className="min-w-0 flex-1">
                <div className="text-[13.5px] text-ink">
                  {item.href ? (
                    <Link href={item.href} className="hover:underline">
                      {item.sentence}
                    </Link>
                  ) : (
                    item.sentence
                  )}
                </div>
                {item.detail ? <div className="mt-0.5 break-words text-[12.5px] text-ink-3">{item.detail}</div> : null}
              </div>
              <span className="shrink-0 text-right text-[12px] text-ink-3">
                {item.who ? <span className="block">{item.who}</span> : null}
                <time dateTime={item.at}>{formatDateTime(item.at)}</time>
              </span>
            </li>
          ))}
        </ol>
      )}
      {nextOffset !== null ? (
        <div className="mt-3 flex justify-center">
          <Button variant="secondary" size="sm" disabled={busy} onClick={() => void load(nextOffset)}>
            {busy ? "Loading…" : "Show older"}
          </Button>
        </div>
      ) : null}
    </SectionPanel>
  );
}
