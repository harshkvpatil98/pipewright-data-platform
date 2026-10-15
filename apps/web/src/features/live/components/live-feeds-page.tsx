"use client";

import Link from "next/link";
import { useState } from "react";

import type { AuthUser, ExtractionConnection, LiveKind, StreamSource } from "@platform/shared-types";
import {
  Badge,
  Button,
  EmptyState,
  SectionPanel,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { countOf, formatDateTime, formatNumber } from "@/lib/format";

import { behindWords, feedState, guaranteeTone } from "../live-words";
import { AddLiveFeed } from "./add-live-feed";
import { LiveRunnerBanner } from "./live-runner-banner";

type LiveFeedsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  feeds: StreamSource[];
  kinds: LiveKind[];
  connections: ExtractionConnection[];
};

/**
 * Every live feed in the project (D1, roadmap Phase 20): what each reads,
 * whether it is keeping up, and how sure it is that each event is saved once.
 */
export function LiveFeedsPageView({ currentUser, projectId, feeds, kinds, connections }: LiveFeedsPageProps) {
  const [adding, setAdding] = useState(false);
  const failing = feeds.filter((feed) => feed.status === "failing").length;
  const add = <Button onClick={() => setAdding(true)}>Add a live feed</Button>;

  return (
    <AppShell
      currentUser={currentUser}
      title="Live feeds"
      subtitle="Data that arrives by itself: database changes, queue messages and posted events."
      actions={feeds.length ? add : undefined}
      meta={
        feeds.length ? (
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-ink-2">
            {countOf(feeds.length, "live feed")}
            {failing ? ` · ${failing} failing` : ""}
          </span>
        ) : null
      }
    >
      <LiveRunnerBanner />
      {feeds.length === 0 ? (
        <EmptyState
          title="No live feeds yet"
          description="Follow a database's changes, read a queue such as Kafka, or give a partner an address to post to."
          action={add}
        />
      ) : (
        <SectionPanel
          title="Live feeds in this project"
          description="Each is read every few seconds and saved to its datasets as it says."
          contentClassName="px-0 py-0"
        >
          <Table edge="panel">
            <TableHead>
              <TableRow>
                <TableHeaderCell>Feed</TableHeaderCell>
                <TableHeaderCell>Reads</TableHeaderCell>
                <TableHeaderCell>State</TableHeaderCell>
                <TableHeaderCell numeric>Events</TableHeaderCell>
                <TableHeaderCell>Last event</TableHeaderCell>
                <TableHeaderCell>Saved once?</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {feeds.map((feed) => {
                const state = feedState(feed);
                const behind = behindWords(feed.behind);
                return (
                  <TableRow key={feed.id}>
                    <TableCell className="text-ink">
                      <Link
                        href={`/projects/${projectId}/live/${feed.id}`}
                        className="font-medium text-[color:var(--accent-muted)] hover:underline"
                      >
                        {feed.name}
                      </Link>
                      {feed.live_tables.length ? (
                        <div className="text-[13px] text-ink-3">
                          {feed.live_tables.map((table) => table.table_name).join(", ")}
                        </div>
                      ) : null}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-2">{feed.kind_label}</TableCell>
                    <TableCell className="whitespace-nowrap">
                      <Badge tone={state.tone} title={feed.last_error ?? undefined}>
                        {state.word}
                      </Badge>
                      {behind ? <div className="mt-1 text-[13px] text-warning">{behind}</div> : null}
                    </TableCell>
                    <TableCell numeric className="text-ink-2">
                      {formatNumber(feed.events_count)}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-3">
                      {feed.last_event_at ? formatDateTime(feed.last_event_at) : "None yet"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <Badge tone={guaranteeTone(feed.guarantee)} title={feed.guarantee_detail}>
                        {feed.guarantee === "at_least_once" ? "At least once" : "Once"}
                      </Badge>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </SectionPanel>
      )}
      <AddLiveFeed
        projectId={projectId}
        kinds={kinds}
        connections={connections}
        open={adding}
        onClose={() => setAdding(false)}
      />
    </AppShell>
  );
}
