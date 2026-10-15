"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";

import type { AuthUser, DataContract } from "@platform/shared-types";
import {
  Badge,
  Button,
  EmptyState,
  FormField,
  Modal,
  SectionPanel,
  Select,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { compareText, countOf, formatDateTime } from "@/lib/format";

import { statusWords } from "../contract-words";

type ContractsPageProps = {
  currentUser: AuthUser;
  projectId: string;
  contracts: DataContract[];
  datasets: { id: string; name: string }[];
};

/**
 * Every contract in the project (Phase 19, C1): which are kept, which are
 * broken and by how much, and a way to write one for a dataset that has none.
 */
export function ContractsPageView({ currentUser, projectId, contracts, datasets }: ContractsPageProps) {
  const router = useRouter();
  const [choosing, setChoosing] = useState(false);
  const covered = useMemo(() => new Set(contracts.map((contract) => contract.dataset_id)), [contracts]);
  const open = useMemo(
    () => datasets.filter((dataset) => !covered.has(dataset.id)).sort((a, b) => compareText(a.name, b.name)),
    [datasets, covered],
  );
  const [chosen, setChosen] = useState("");
  const broken = contracts.filter((contract) => contract.status === "broken").length;

  const start = () => {
    const target = chosen || open[0]?.id;
    if (target) router.push(`/projects/${projectId}/datasets/${target}/contract`);
  };

  const add = (
    <Button onClick={() => setChoosing(true)} disabled={open.length === 0}>
      Add a contract
    </Button>
  );

  return (
    <AppShell
      currentUser={currentUser}
      title="Contracts"
      subtitle="Promises about a dataset that new data must keep."
      actions={contracts.length ? add : undefined}
      meta={
        contracts.length ? (
          <span className="rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-ink-2">
            {countOf(contracts.length, "contract")}
            {broken ? ` · ${broken} broken` : " · all kept"}
          </span>
        ) : null
      }
    >
      {contracts.length === 0 ? (
        <EmptyState
          title="No contracts yet"
          description="A contract promises the people using a dataset what it holds. New data that breaks it is stopped before it replaces what they use."
          action={add}
        />
      ) : (
        <SectionPanel
          title="Contracts in this project"
          description="Each is checked whenever a recipe, an import or a stream makes new data for its dataset."
          contentClassName="px-0 py-0"
        >
          <Table edge="panel">
            <TableHead>
              <TableRow>
                <TableHeaderCell>Dataset</TableHeaderCell>
                <TableHeaderCell>State</TableHeaderCell>
                <TableHeaderCell>When broken</TableHeaderCell>
                <TableHeaderCell>Owner</TableHeaderCell>
                <TableHeaderCell numeric>Followers</TableHeaderCell>
                <TableHeaderCell>Last checked</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {contracts.map((contract) => {
                const state = statusWords(contract.status);
                return (
                  <TableRow key={contract.id}>
                    <TableCell className="text-ink">
                      <Link
                        href={`/projects/${projectId}/datasets/${contract.dataset_id}/contract`}
                        className="font-medium text-[color:var(--accent-muted)] hover:underline"
                      >
                        {contract.dataset_name}
                      </Link>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <Badge tone={state.tone}>
                        {contract.status === "broken" ? countOf(contract.open_problems, "problem") : state.word}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-ink-2">
                      {contract.enforcement === "stop" ? "Stops the data" : "Lets it through, with a warning"}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-2">{contract.owner_username ?? "Nobody"}</TableCell>
                    <TableCell numeric className="text-ink-2">
                      {contract.followers}
                    </TableCell>
                    <TableCell className="whitespace-nowrap text-ink-3">
                      {contract.last_checked_at ? formatDateTime(contract.last_checked_at) : "Not yet"}
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        </SectionPanel>
      )}

      <Modal
        open={choosing}
        onClose={() => setChoosing(false)}
        title="Add a contract"
        description="Choose the dataset. Its promises are written from its current data, for you to change before saving."
        footer={
          <div className="flex items-center justify-end gap-2">
            <Button variant="ghost" size="sm" onClick={() => setChoosing(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={start} disabled={open.length === 0}>
              Continue
            </Button>
          </div>
        }
      >
        {open.length === 0 ? (
          <p className="text-sm text-ink-3">Every dataset in this project already has a contract.</p>
        ) : (
          <FormField label="Dataset" htmlFor="contract-dataset">
            <Select id="contract-dataset" value={chosen || open[0].id} onChange={(event) => setChosen(event.target.value)}>
              {open.map((dataset) => (
                <option key={dataset.id} value={dataset.id}>
                  {dataset.name}
                </option>
              ))}
            </Select>
          </FormField>
        )}
      </Modal>
    </AppShell>
  );
}
