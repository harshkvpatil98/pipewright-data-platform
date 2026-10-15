"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

import type {
  AuthUser,
  ContractCheck,
  ContractConsumer,
  ContractHistoryResponse,
  ContractProblem,
  ContractSaveResponse,
  ContractVersion,
  DataContract,
  DataContractWrite,
  DatasetContractResponse,
} from "@platform/shared-types";
import { Badge, Button, EmptyState, SectionPanel, Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf, formatDateTime } from "@/lib/format";

import {
  columnPromise,
  consumerHref,
  consumerKind,
  datasetPromises,
  problemHeadline,
  statusWords,
} from "../contract-words";
import { ContractEditor } from "./contract-editor";

type DatasetContractPageProps = {
  currentUser: AuthUser;
  projectId: string;
  dataset: { id: string; name: string; columns: string[]; ready: boolean };
  initial: DatasetContractResponse;
  initialHistory: ContractVersion[];
};

const RANK: Record<string, number> = { viewer: 0, operator: 1, editor: 2, admin: 3 };
const atLeast = (role: string | null, needed: string) => role !== null && (RANK[role] ?? -1) >= RANK[needed];

/**
 * A dataset's contract (Phase 19, C1): what it promises, whether new data is
 * keeping it, what relies on it, and its history; written from the current
 * data in one click by someone who may edit.
 */
export function DatasetContractPageView({
  currentUser,
  projectId,
  dataset,
  initial,
  initialHistory,
}: DatasetContractPageProps) {
  const router = useRouter();
  const [state, setState] = useState(initial);
  const [history, setHistory] = useState(initialHistory);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [checked, setChecked] = useState<ContractCheck | null>(null);
  const base = `/projects/${projectId}/datasets/${dataset.id}/contract`;
  const contract = state.contract;
  const canEdit = atLeast(state.your_role, "editor");
  const canCheck = atLeast(state.your_role, "operator");

  const refreshHistory = async () => {
    try {
      setHistory((await apiFetch<ContractHistoryResponse>(`${base}/history`)).items);
    } catch {
      /* the history is a convenience; the contract itself is already shown */
    }
  };

  const save = async (body: DataContractWrite) => {
    setBusy("save");
    setError(null);
    try {
      const saved = await apiFetch<ContractSaveResponse>(base, { method: "PUT", body: JSON.stringify(body) });
      setState(saved);
      setChecked(saved.current);
      setEditing(false);
      await refreshHistory();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const act = async (name: string, run: () => Promise<void>) => {
    setBusy(name);
    setError(null);
    try {
      await run();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const follow = () =>
    act("follow", async () => {
      const updated = await apiFetch<DataContract>(`${base}/follow`, { method: contract?.following ? "DELETE" : "POST" });
      setState((current) => (current.contract ? { ...current, contract: { ...current.contract, ...updated } } : current));
    });

  const checkNow = () =>
    act("check", async () => {
      setChecked(await apiFetch<ContractCheck>(`${base}/check`, { method: "POST" }));
      setState(await apiFetch<DatasetContractResponse>(base));
    });

  const ownerDefault =
    contract?.owner_user_id ??
    (state.people.some((person) => person.id === currentUser.id) ? currentUser.id : null);

  const startingPoint: DataContractWrite = contract
    ? {
        owner_user_id: contract.owner_user_id,
        description: contract.description,
        enforcement: contract.enforcement,
        terms: contract.terms,
      }
    : { owner_user_id: ownerDefault, description: null, enforcement: "stop", terms: state.draft };

  const status = contract ? statusWords(contract.status) : null;
  const open = contract?.problems.filter((problem) => problem.resolved_at === null) ?? [];
  const earlier = contract?.problems.filter((problem) => problem.resolved_at !== null) ?? [];

  return (
    <AppShell
      currentUser={currentUser}
      title={`Contract · ${dataset.name}`}
      subtitle="What this dataset promises the people who use it."
      actions={
        contract && !editing ? (
          <div className="flex flex-wrap items-center gap-2">
            {canEdit ? (
              <Button size="sm" onClick={() => setEditing(true)}>
                Change
              </Button>
            ) : null}
            {canCheck && dataset.ready ? (
              <Button size="sm" variant="secondary" onClick={() => void checkNow()} disabled={busy !== null}>
                {busy === "check" ? "Checking…" : "Check now"}
              </Button>
            ) : null}
            <Button size="sm" variant="secondary" onClick={() => void follow()} disabled={busy !== null}>
              {contract.following ? "Stop following" : "Follow"}
            </Button>
            {canEdit ? (
              <DeleteRowButton
                path={base}
                name={`the contract on ${dataset.name}`}
                kind="contract"
                consequences={[
                  "New data is no longer checked against its promises.",
                  "Its history and problems go with it. The dataset and its freshness promise stay.",
                ]}
                onDeleted={() => router.push(`/projects/${projectId}/contracts`)}
              />
            ) : null}
          </div>
        ) : undefined
      }
      meta={
        contract && status ? (
          <>
            <Badge tone={status.tone}>{status.word}</Badge>
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-ink-2">
              Version {contract.version} ·{" "}
              {contract.enforcement === "stop" ? "stops data that breaks it" : "warns about data that breaks it"}
            </span>
            <span className="rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-ink-2">
              {countOf(contract.followers, "follower")}
            </span>
          </>
        ) : null
      }
    >
      {error && !editing ? (
        <p role="alert" className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
          {error}
        </p>
      ) : null}
      {checked ? <CheckNotice check={checked} /> : null}

      {editing ? (
        <ContractEditor
          projectId={projectId}
          datasetId={dataset.id}
          columns={dataset.columns}
          people={state.people}
          initial={startingPoint}
          saved={contract?.terms ?? null}
          busy={busy === "save"}
          error={error}
          onSave={(body) => void save(body)}
          onCancel={() => {
            setEditing(false);
            setError(null);
          }}
        />
      ) : !contract ? (
        <EmptyState
          title="No contract yet"
          description={
            canEdit
              ? "Write down what this dataset promises: its columns, its rows and how often it gets new data. It starts from today's data."
              : "Nobody has written down what this dataset promises yet. Someone with the editor role can."
          }
          action={
            canEdit ? (
              <Button onClick={() => setEditing(true)} disabled={!dataset.ready}>
                Write the contract
              </Button>
            ) : undefined
          }
        />
      ) : (
        <>
          {open.length ? (
            <SectionPanel
              title={open.length === 1 ? "A problem now" : `${countOf(open.length, "problem")} now`}
              description="Resolved on its own when new data from the same place keeps the contract."
            >
              <ul className="space-y-3">
                {open.map((problem) => (
                  <ProblemItem key={problem.id} problem={problem} projectId={projectId} />
                ))}
              </ul>
            </SectionPanel>
          ) : null}

          <SectionPanel
            title="What it promises"
            description={contract.description ?? "No description yet."}
            actions={
              <span className="text-[13px] text-ink-3">
                Owner: <span className="text-ink-2">{contract.owner_username ?? "nobody"}</span>
              </span>
            }
            contentClassName="px-0 py-0"
          >
            {contract.terms.columns.length ? (
              <Table edge="panel">
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Column</TableHeaderCell>
                    <TableHeaderCell>Promise</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {contract.terms.columns.map((column) => (
                    <TableRow key={column.name}>
                      <TableCell className="font-medium text-ink">{column.name}</TableCell>
                      <TableCell className="text-ink-2">
                        {columnPromise(column)}
                        {column.allowed_values?.length ? (
                          <span className="block text-[13px] text-ink-3">{column.allowed_values.join(", ")}</span>
                        ) : null}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <p className="px-5 py-4 text-sm text-ink-3 lg:px-6">No columns are promised.</p>
            )}
            <ul className="space-y-1 border-t border-line px-5 py-4 text-sm text-ink-2 lg:px-6">
              {datasetPromises(contract.terms).map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
          </SectionPanel>

          <ReliesOn projectId={projectId} consumers={contract.consumers} />

          {earlier.length ? (
            <SectionPanel title="Earlier problems" description="Problems that new data has since resolved.">
              <ul className="space-y-3">
                {earlier.map((problem) => (
                  <ProblemItem key={problem.id} problem={problem} projectId={projectId} />
                ))}
              </ul>
            </SectionPanel>
          ) : null}

          <SectionPanel title="History" description="Every change to the contract, newest first.">
            <ol className="space-y-3">
              {history.map((version) => (
                <li key={version.version} className="rounded-2xl border border-line bg-surface px-4 py-3">
                  <div className="text-[13px] text-ink-3">
                    Version {version.version} · {version.created_by_username ?? "Someone"} ·{" "}
                    {formatDateTime(version.created_at)}
                  </div>
                  <ul className="mt-1 list-disc pl-5 text-sm text-ink-2">
                    {version.changes.map((line) => (
                      <li key={line}>{line}</li>
                    ))}
                  </ul>
                </li>
              ))}
            </ol>
          </SectionPanel>
        </>
      )}
    </AppShell>
  );
}

function CheckNotice({ check }: { check: ContractCheck }) {
  if (check.kept) {
    return (
      <p className="rounded-2xl border border-success-line bg-success-soft px-4 py-3 text-sm text-success">
        The current data keeps the contract ({countOf(check.rows_checked, "row")} checked).
      </p>
    );
  }
  return (
    <div role="status" className="rounded-2xl border border-warning-line bg-warning-soft px-4 py-3 text-sm text-ink-2">
      <p className="font-medium text-warning">The current data already breaks the contract.</p>
      <ul className="mt-1 list-disc pl-5">
        {check.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      <p className="mt-1 text-ink-3">Fix the data or the promise; until then it shows as broken.</p>
    </div>
  );
}

function ProblemItem({ problem, projectId }: { problem: ContractProblem; projectId: string }) {
  const resolved = problem.resolved_at !== null;
  return (
    <li
      className={
        resolved
          ? "rounded-2xl border border-line bg-surface px-4 py-3"
          : "rounded-2xl border border-danger-line bg-danger-soft px-4 py-3"
      }
    >
      <p className={resolved ? "text-sm font-medium text-ink-2" : "text-sm font-medium text-danger"}>
        {problemHeadline(problem)}
      </p>
      <ul className="mt-1 list-disc pl-5 text-sm text-ink-2">
        {problem.reasons.map((reason) => (
          <li key={reason}>{reason}</li>
        ))}
      </ul>
      <p className="mt-2 text-[13px] text-ink-3">
        {problem.times_seen > 1 ? `Seen ${problem.times_seen} times, last ` : "Seen "}
        {formatDateTime(problem.last_seen_at)}
        {problem.resolved_at ? ` · resolved ${formatDateTime(problem.resolved_at)}` : ""}
        {problem.pipeline_run_id ? (
          <>
            {" · "}
            <Link href={`/projects/${projectId}/runs/${problem.pipeline_run_id}/audit`} className="underline">
              See the run
            </Link>
          </>
        ) : null}
      </p>
    </li>
  );
}

function ReliesOn({ projectId, consumers }: { projectId: string; consumers: ContractConsumer[] }) {
  const kinds = [...new Set(consumers.map((consumer) => consumer.kind))];
  return (
    <SectionPanel title="What relies on it" description="Worked out from the project as it is now.">
      {consumers.length === 0 ? (
        <p className="text-sm text-ink-3">Nothing in this project reads this dataset yet.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-2">
          {kinds.map((kind) => {
            const items = consumers.filter((consumer) => consumer.kind === kind);
            return (
              <div key={kind}>
                <h3 className="text-[13px] font-medium text-ink-3">{consumerKind(kind, items.length)}</h3>
                <ul className="mt-1 space-y-1 text-sm">
                  {items.map((consumer) => {
                    const href = consumerHref(projectId, consumer);
                    return (
                      <li key={consumer.id}>
                        {href ? (
                          <Link href={href} className="text-[color:var(--accent-muted)] hover:underline">
                            {consumer.name}
                          </Link>
                        ) : (
                          consumer.name
                        )}
                      </li>
                    );
                  })}
                </ul>
              </div>
            );
          })}
        </div>
      )}
    </SectionPanel>
  );
}
