"use client";

import { useEffect, useMemo, useState } from "react";

import type {
  ConnectorSpec,
  ExtractionConnection,
  SqlConnectorType,
} from "@platform/shared-types";
import { SQL_CONNECTOR_TYPES } from "@platform/shared-types";
import { Button, FormField, Input, Modal, Select } from "@platform/shared-ui";

import { Icon, type IconName } from "@/components/ui/icon";
import {
  connectorConfig,
  firstMissing,
  importableConnectors,
  initialValues,
  SOURCE_GROUPS,
  splitFields,
} from "@/features/extraction/connector-form";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

type ConnectSourceDialogProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
  catalogue: ConnectorSpec[];
  /** A SQL database was picked; it has its own form on the page. */
  onPickDatabase: (type: SqlConnectorType) => void;
  onCreated: (connection: ExtractionConnection) => void;
};

const CATEGORY_ICONS: Record<string, IconName> = {
  database: "database",
  warehouse: "database",
  lakehouse: "database",
  saas: "grid",
  api: "link",
  storage: "folder",
  file: "file",
};

const TIER_TONE: Record<number, string> = {
  1: "border-success-line bg-success-soft text-success",
  2: "border-success-line bg-success-soft text-success",
  3: "border-line bg-surface-2 text-ink-3",
  4: "border-warning-line bg-warning-soft text-warning",
};

/**
 * Every source that can be imported from, in one searchable list: databases,
 * apps, APIs and storage. Each card says how far it has been tested here, and
 * the form for a connector is built from the settings that connector declares.
 */
export function ConnectSourceDialog({
  open,
  onClose,
  projectId,
  catalogue,
  onPickDatabase,
  onCreated,
}: ConnectSourceDialogProps) {
  const [query, setQuery] = useState("");
  const [group, setGroup] = useState<string | null>(null);
  const [chosen, setChosen] = useState<ConnectorSpec | null>(null);
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setChosen(null);
    setQuery("");
    setGroup(null);
    setError(null);
  }, [open]);

  const visible = useMemo(
    () => importableConnectors(catalogue, query, group),
    [catalogue, query, group],
  );

  const choose = (spec: ConnectorSpec) => {
    if ((SQL_CONNECTOR_TYPES as readonly string[]).includes(spec.type)) {
      onPickDatabase(spec.type as SqlConnectorType);
      return;
    }
    setChosen(spec);
    setName(spec.label);
    setValues(initialValues(spec.config_fields));
    setError(null);
  };

  const save = async () => {
    if (!chosen) return;
    const missing = firstMissing(chosen.config_fields, values);
    if (missing) {
      setError(`Fill in ${missing.toLowerCase()}.`);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const created = await apiFetch<ExtractionConnection>(
        `/projects/${projectId}/extraction/connections`,
        {
          method: "POST",
          body: JSON.stringify({
            name: name.trim() || chosen.label,
            connector_type: chosen.type,
            config: connectorConfig(chosen.config_fields, values),
          }),
        },
      );
      onCreated(created);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title={chosen ? `Connect ${chosen.label}` : "Connect a source"}
      description={
        chosen
          ? chosen.description
          : "Import from a database, an app, an API or a storage bucket."
      }
      widthClassName="max-w-2xl"
      footer={
        chosen ? (
          <div className="flex justify-between gap-2">
            <Button variant="ghost" size="sm" onClick={() => setChosen(null)}>
              Back
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={busy}>
              {busy ? "Connecting…" : "Connect and check"}
            </Button>
          </div>
        ) : undefined
      }
    >
      {chosen ? (
        <div className="space-y-4">
          {error ? (
            <p
              role="alert"
              className="border-danger-line bg-danger-soft text-danger rounded-xl border px-3 py-2 text-[13px]"
            >
              {error}
            </p>
          ) : null}
          {!chosen.verified ? (
            <p className="border-warning-line bg-warning-soft text-warning rounded-xl border px-3 py-2 text-[13px] leading-5">
              <span className="font-medium">{chosen.tier_label}. </span>
              {chosen.tier_explanation}
            </p>
          ) : null}
          <FormField
            label="Name"
            htmlFor="source-name"
            description="How this source is listed in the project."
          >
            <Input
              id="source-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
          </FormField>
          {(() => {
            const { main, more } = splitFields(chosen.config_fields);
            const render = (field: (typeof chosen.config_fields)[number]) => {
              const id = `source-${field.name}`;
              const value = values[field.name] ?? "";
              const set = (next: string) =>
                setValues((current) => ({ ...current, [field.name]: next }));
              return (
                <FormField
                  key={field.name}
                  label={
                    field.required ? field.label : `${field.label} (optional)`
                  }
                  htmlFor={id}
                  description={field.help ?? undefined}
                >
                  {field.kind === "select" ? (
                    <Select
                      id={id}
                      value={value}
                      onChange={(event) => set(event.target.value)}
                    >
                      {field.required ? null : (
                        <option value="">As it comes</option>
                      )}
                      {field.options.map((option) => (
                        <option key={option} value={option}>
                          {option}
                        </option>
                      ))}
                    </Select>
                  ) : field.kind === "boolean" ? (
                    <label className="text-ink flex items-center gap-2 text-[14px]">
                      <input
                        id={id}
                        type="checkbox"
                        checked={value === "true"}
                        onChange={(event) =>
                          set(event.target.checked ? "true" : "false")
                        }
                        className="h-4 w-4"
                      />
                      Yes
                    </label>
                  ) : field.kind === "text" ? (
                    <textarea
                      id={id}
                      value={value}
                      onChange={(event) => set(event.target.value)}
                      rows={3}
                      placeholder={field.placeholder ?? undefined}
                      className="border-line bg-sunken text-ink w-full rounded-xl border px-3 py-2 font-mono text-[13px] outline-none focus:border-[color:var(--accent)]"
                    />
                  ) : (
                    <Input
                      id={id}
                      type={
                        field.kind === "secret"
                          ? "password"
                          : field.kind === "number"
                            ? "number"
                            : "text"
                      }
                      value={value}
                      onChange={(event) => set(event.target.value)}
                      placeholder={field.placeholder ?? undefined}
                      autoComplete={
                        field.kind === "secret" ? "new-password" : "off"
                      }
                    />
                  )}
                </FormField>
              );
            };
            return (
              <>
                {main.map(render)}
                {more.length > 0 ? (
                  <details className="border-line rounded-xl border px-3 py-2">
                    <summary className="text-ink-2 cursor-pointer text-[13px]">
                      More settings ({more.length}), usually fine as they are
                    </summary>
                    <div className="mt-3 space-y-4">{more.map(render)}</div>
                  </details>
                ) : null}
              </>
            );
          })()}
          <p className="text-ink-3 text-[13px]">
            {chosen.secret_fields.length > 0
              ? "Keys and passwords are stored encrypted and never shown again."
              : "Nothing secret is asked for."}
          </p>
        </div>
      ) : (
        <div>
          <label htmlFor="source-search" className="sr-only">
            Search sources
          </label>
          <div className="border-line bg-sunken flex h-10 items-center gap-2 rounded-lg border px-3 focus-within:border-[color:var(--accent)]">
            <Icon name="search" size={15} className="text-muted" />
            <input
              id="source-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder="Search, for example “github”, “s3” or “postgres”"
              style={{ outline: "none" }}
              className="text-ink placeholder:text-faint min-w-0 flex-1 bg-transparent text-[14px]"
              autoFocus
            />
          </div>
          <div className="mt-3 flex flex-wrap gap-1.5">
            {[{ id: null, label: "All" }, ...SOURCE_GROUPS].map((entry) => (
              <button
                key={entry.id ?? "all"}
                type="button"
                aria-pressed={group === entry.id}
                onClick={() => setGroup(entry.id)}
                className={cx(
                  "rounded-full border px-3 py-1 text-[13px] transition",
                  group === entry.id
                    ? "text-ink border-[color:var(--accent)] bg-[color:var(--accent-faint)]"
                    : "border-line text-ink-3 hover:text-ink",
                )}
              >
                {entry.label}
              </button>
            ))}
          </div>
          <p className="text-muted mt-3 text-[12px]">
            {visible.length} source{visible.length === 1 ? "" : "s"}. “Tested”
            ones run against a real server in our checks; “Unverified” ones are
            built from the vendor’s documentation.
          </p>
          <ul className="mt-2 max-h-[46vh] space-y-1.5 overflow-y-auto pr-1">
            {visible.map((spec) => (
              <li key={spec.type}>
                <button
                  type="button"
                  disabled={!spec.available}
                  onClick={() => choose(spec)}
                  title={
                    spec.available
                      ? spec.description
                      : (spec.unavailable_reason ?? undefined)
                  }
                  className="border-line bg-surface disabled:hover:border-line disabled:hover:bg-surface flex w-full items-start gap-3 rounded-xl border px-3 py-2.5 text-left transition hover:border-[color:var(--accent-soft)] hover:bg-[color:var(--accent-faint)] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  <Icon
                    name={CATEGORY_ICONS[spec.category] ?? "database"}
                    size={16}
                    className="mt-0.5 shrink-0 text-[color:var(--accent-muted)]"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="text-ink text-[14px] font-medium">
                        {spec.label}
                      </span>
                      <span
                        className={cx(
                          "rounded-full border px-2 py-0 text-[12px]",
                          TIER_TONE[spec.tier] ?? TIER_TONE[4],
                        )}
                      >
                        {spec.tier_label}
                      </span>
                    </span>
                    <span className="text-ink-3 block truncate text-[13px]">
                      {spec.available
                        ? spec.description
                        : spec.unavailable_reason}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </Modal>
  );
}
