"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type {
  AuthUser,
  DestinationCreatePayload,
  DestinationRecord,
  DestinationTestResult,
  DestinationUpdatePayload,
} from "@platform/shared-types";
import {
  Button,
  EmptyState,
  FormField,
  Icon,
  Input,
  Modal,
  SectionPanel,
  Select,
} from "@platform/shared-ui";

import { AppShell } from "@/components/layout/app-shell";
import { CopyDatabaseDialog } from "@/features/destinations/components/copy-database-dialog";
import { DeleteRowButton } from "@/components/ui/delete-row-button";
import {
  configFrom,
  DESTINATION_KINDS,
  emptyValues,
  KIND_BY_TYPE,
  missingField,
  valuesFrom,
  type DestinationKind,
} from "@/features/destinations/destination-kinds";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { formatDate } from "@/lib/format";
import { cx } from "@/lib/utils";

type DestinationsPageViewProps = {
  currentUser: AuthUser;
  projectId: string;
  initialItems: DestinationRecord[];
};

type Draft = {
  kind: DestinationKind;
  name: string;
  values: Record<string, string>;
  /** Set when editing a saved destination. */
  editing: DestinationRecord | null;
};

export function DestinationsPageView({ currentUser, projectId, initialItems }: DestinationsPageViewProps) {
  const router = useRouter();
  const [items, setItems] = useState(initialItems);
  const [picking, setPicking] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const [tests, setTests] = useState<Record<string, DestinationTestResult>>({});
  const [copying, setCopying] = useState(false);

  useEffect(() => {
    setItems(initialItems);
  }, [initialItems]);

  const refresh = async () => {
    const data = await apiFetch<{ items: DestinationRecord[] }>(`/projects/${projectId}/destinations`);
    setItems(data.items);
    router.refresh();
  };

  const runTest = async (id: string) => {
    setTesting(id);
    try {
      const result = await apiFetch<DestinationTestResult>(`/projects/${projectId}/destinations/${id}/test`, {
        method: "POST",
      });
      setTests((current) => ({ ...current, [id]: result }));
    } catch (caught) {
      setTests((current) => ({
        ...current,
        [id]: { success: false, message: extractErrorMessage(caught), checked_at: new Date().toISOString(), latency_ms: null, warnings: [] },
      }));
    } finally {
      setTesting(null);
    }
  };

  const save = async () => {
    if (!draft) return;
    setFormError(null);
    if (!draft.name.trim()) {
      setFormError("Give the destination a name you will recognise.");
      return;
    }
    const missing = missingField(draft.kind, draft.values, draft.editing !== null);
    if (missing) {
      setFormError(`Fill in ${missing.toLowerCase()}.`);
      return;
    }
    setBusy(true);
    try {
      const config = configFrom(draft.kind, draft.values);
      let savedId: string;
      if (draft.editing) {
        const patch: DestinationUpdatePayload = { name: draft.name.trim(), config_json: config };
        await apiFetch(`/projects/${projectId}/destinations/${draft.editing.id}`, {
          method: "PATCH",
          body: JSON.stringify(patch),
        });
        savedId = draft.editing.id;
      } else {
        const payload: DestinationCreatePayload = {
          name: draft.name.trim(),
          destination_type: draft.kind.type,
          status: "active",
          config_json: config,
        };
        const created = await apiFetch<DestinationRecord>(`/projects/${projectId}/destinations`, {
          method: "POST",
          body: JSON.stringify(payload),
        });
        savedId = created.id;
      }
      setDraft(null);
      await refresh();
      // Test straight away: "saved" is not the same as "works".
      void runTest(savedId);
    } catch (caught) {
      setFormError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const startNew = (kind: DestinationKind) => {
    setPicking(false);
    setFormError(null);
    setDraft({ kind, name: "", values: emptyValues(kind), editing: null });
  };

  const startEdit = (row: DestinationRecord) => {
    const kind = KIND_BY_TYPE.get(row.destination_type);
    if (!kind) return;
    setFormError(null);
    setDraft({ kind, name: row.name, values: valuesFrom(kind, row.config_json), editing: row });
  };

  return (
    <AppShell
      currentUser={currentUser}
      title="Destinations"
      subtitle="Where your data is delivered: database tables and files in storage."
      actions={
        <>
          <Button onClick={() => setPicking(true)}>
            <Icon name="plus" size={15} />
            Add a destination
          </Button>
          <Button variant="secondary" onClick={() => setCopying(true)}>
            <Icon name="database" size={15} />
            Copy a database
          </Button>
        </>
      }
    >
      {items.length === 0 ? (
        <EmptyState
          title="Nothing to deliver to yet"
          description="Add a database or a storage bucket, then send any dataset there from its page, by hand or on a schedule."
          action={<Button onClick={() => setPicking(true)}>Add a destination</Button>}
        />
      ) : (
        <SectionPanel title={`${items.length} destination${items.length === 1 ? "" : "s"}`}>
          <ul className="divide-y divide-line">
            {items.map((row) => {
              const kind = KIND_BY_TYPE.get(row.destination_type);
              const test = tests[row.id];
              return (
                <li key={row.id} className="flex flex-wrap items-center gap-x-4 gap-y-2 py-3">
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[color:var(--accent-faint)] text-[color:var(--accent-muted)]">
                    <Icon name={kind?.icon ?? "send"} size={17} />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[15px] font-medium text-ink">{row.name}</div>
                    <div className="text-[13px] text-ink-3">
                      {kind?.label ?? row.destination_type} · receives {kind?.receives.toLowerCase() ?? "data"} · added{" "}
                      {formatDate(row.created_at)}
                      {row.status !== "active" ? " · turned off" : ""}
                    </div>
                    {test ? (
                      <div className={cx("mt-1 flex items-start gap-1.5 text-[13px]", test.success ? "text-success" : "text-danger")}>
                        <Icon name={test.success ? "checkCircle" : "warning"} size={14} className="mt-0.5 shrink-0" />
                        <span>{test.message}</span>
                      </div>
                    ) : null}
                  </div>
                  <div className="flex shrink-0 flex-wrap gap-2">
                    <Button variant="secondary" size="sm" disabled={testing === row.id} onClick={() => void runTest(row.id)}>
                      {testing === row.id ? "Testing…" : "Test"}
                    </Button>
                    <Button variant="secondary" size="sm" onClick={() => startEdit(row)}>
                      Edit
                    </Button>
                    <DeleteRowButton
                      path={`/projects/${projectId}/destinations/${row.id}`}
                      name={row.name}
                      kind="destination"
                      consequences={["Its saved address and credentials go with it. Data already delivered stays where it is."]}
                      onDeleted={() => setItems((current) => current.filter((item) => item.id !== row.id))}
                    />
                  </div>
                </li>
              );
            })}
          </ul>
        </SectionPanel>
      )}

      <SectionPanel title="What you can deliver to">
        <ul className="grid gap-3 sm:grid-cols-2">
          {DESTINATION_KINDS.map((kind) => (
            <li key={kind.type} className="flex gap-3 rounded-2xl border border-line bg-surface p-3">
              <Icon name={kind.icon} size={17} className="mt-0.5 shrink-0 text-[color:var(--accent-muted)]" />
              <div>
                <div className="text-[14px] font-medium text-ink">{kind.label}</div>
                <div className="text-[13px] leading-5 text-ink-3">{kind.description}</div>
              </div>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-[13px] leading-5 text-ink-3">
          To move a whole database, use Copy a database: tables from PostgreSQL, MySQL or SQLite into
          PostgreSQL or MySQL. Power BI and Tableau are under BI tools. Warehouses such as Snowflake,
          BigQuery and Redshift are not supported yet.
        </p>
      </SectionPanel>

      <CopyDatabaseDialog open={copying} onClose={() => setCopying(false)} projectId={projectId} />

      <Modal
        open={picking}
        onClose={() => setPicking(false)}
        title="Add a destination"
        description="Where should data be delivered?"
        widthClassName="max-w-xl"
      >
        <ul className="space-y-2">
          {DESTINATION_KINDS.map((kind) => (
            <li key={kind.type}>
              <button
                type="button"
                onClick={() => startNew(kind)}
                className="flex w-full items-start gap-3 rounded-2xl border border-line bg-surface p-4 text-left transition hover:border-[color:var(--accent-soft)] hover:bg-[color:var(--accent-faint)]"
              >
                <Icon name={kind.icon} size={18} className="mt-0.5 shrink-0 text-[color:var(--accent-muted)]" />
                <span>
                  <span className="block text-[15px] font-semibold text-ink">{kind.label}</span>
                  <span className="mt-0.5 block text-[13px] leading-5 text-ink-3">{kind.description}</span>
                </span>
              </button>
            </li>
          ))}
        </ul>
      </Modal>

      <Modal
        open={draft !== null}
        onClose={() => setDraft(null)}
        title={draft ? (draft.editing ? `Edit ${draft.editing.name}` : `Add ${draft.kind.label}`) : ""}
        description={draft?.editing ? "Leave a secret empty to keep the saved one." : draft?.kind.description}
        widthClassName="max-w-lg"
        footer={
          <div className="flex justify-between gap-2">
            {draft && !draft.editing ? (
              <Button
                variant="ghost"
                onClick={() => {
                  setDraft(null);
                  setPicking(true);
                }}
              >
                Back
              </Button>
            ) : (
              <span />
            )}
            <Button disabled={busy} onClick={() => void save()}>
              {busy ? "Saving…" : draft?.editing ? "Save changes" : "Save and test"}
            </Button>
          </div>
        }
      >
        {draft ? (
          <div className="space-y-4">
            {formError ? (
              <p role="alert" className="rounded-xl border border-danger-line bg-danger-soft px-3 py-2 text-[13px] text-danger">
                {formError}
              </p>
            ) : null}
            <FormField label="Name" htmlFor="destination-name">
              <Input
                id="destination-name"
                value={draft.name}
                onChange={(event) => setDraft({ ...draft, name: event.target.value })}
                placeholder={`${draft.kind.label} for reports`}
                autoComplete="off"
                autoFocus
              />
            </FormField>
            {draft.kind.fields.map((field) => (
              <FormField
                key={field.key}
                label={field.required ? field.label : `${field.label} (optional)`}
                htmlFor={`destination-${field.key}`}
                description={field.help}
              >
                {field.kind === "select" ? (
                  <Select
                    id={`destination-${field.key}`}
                    value={draft.values[field.key] ?? ""}
                    onChange={(event) =>
                      setDraft({ ...draft, values: { ...draft.values, [field.key]: event.target.value } })
                    }
                  >
                    {(field.options ?? []).map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </Select>
                ) : (
                  <Input
                    id={`destination-${field.key}`}
                    type={field.kind === "password" ? "password" : field.kind === "number" ? "number" : "text"}
                    value={draft.values[field.key] ?? ""}
                    onChange={(event) =>
                      setDraft({ ...draft, values: { ...draft.values, [field.key]: event.target.value } })
                    }
                    placeholder={
                      field.kind === "password" && draft.editing ? "Leave empty to keep the saved one" : field.placeholder
                    }
                    autoComplete={field.kind === "password" ? "new-password" : "off"}
                  />
                )}
              </FormField>
            ))}
          </div>
        ) : null}
      </Modal>
    </AppShell>
  );
}
