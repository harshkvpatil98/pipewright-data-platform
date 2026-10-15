"use client";

import { useState } from "react";

import type { DiscoveredTablesResponse, ExtractionConnection, LiveKind } from "@platform/shared-types";
import { Button, FormField, Input, Select } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

import { tableList } from "../live-words";

type FeedSettingsFormProps = {
  projectId: string;
  kind: LiveKind;
  values: Record<string, string>;
  onValues: (next: Record<string, string>) => void;
  /** What is saved, when editing: a secret shows only whether it is set. */
  saved?: Record<string, unknown>;
  connections: ExtractionConnection[];
  connectionId: string;
  onConnection?: (id: string) => void;
  tables: string;
  onTables: (text: string) => void;
  idPrefix: string;
};

/**
 * A kind's own settings, drawn from what it declares, and for change capture
 * the connection it reads through and the tables it follows (with a way to
 * list the tables the connection has).
 */
export function FeedSettingsForm({
  projectId,
  kind,
  values,
  onValues,
  saved = {},
  connections,
  connectionId,
  onConnection,
  tables,
  onTables,
  idPrefix,
}: FeedSettingsFormProps) {
  const [found, setFound] = useState<string[] | null>(null);
  const [finding, setFinding] = useState(false);
  const [findError, setFindError] = useState<string | null>(null);
  const usable = connections.filter((connection) => kind.connection_types.includes(connection.connector_type));
  const followsTables = kind.family === "change_capture";
  const chosen = tableList(tables);

  const find = async () => {
    if (!connectionId) return;
    setFinding(true);
    setFindError(null);
    try {
      const listed = await apiFetch<DiscoveredTablesResponse>(
        `/projects/${projectId}/extraction/connections/${connectionId}/tables`,
      );
      setFound(listed.items.map((item) => item.qualified_name));
    } catch (caught) {
      setFindError(extractErrorMessage(caught));
    } finally {
      setFinding(false);
    }
  };

  const toggle = (name: string) => {
    const next = chosen.includes(name) ? chosen.filter((item) => item !== name) : [...chosen, name];
    onTables(next.join(", "));
  };

  return (
    <div className="space-y-4">
      {kind.connection_types.length ? (
        <FormField
          label="Connection"
          htmlFor={`${idPrefix}-connection`}
          description={
            usable.length
              ? `The ${kind.label.replace(" change capture", "")} connection to follow. The test says what to change in the database if anything is missing.`
              : `This project has no ${kind.connection_types.join(" or ")} connection yet. Add one on the Sources tab first.`
          }
        >
          <Select
            id={`${idPrefix}-connection`}
            value={connectionId}
            disabled={!onConnection}
            onChange={(event) => {
              onConnection?.(event.target.value);
              setFound(null);
            }}
          >
            <option value="">Choose…</option>
            {usable.map((connection) => (
              <option key={connection.id} value={connection.id}>
                {connection.name}
              </option>
            ))}
          </Select>
        </FormField>
      ) : null}

      {kind.fields.map((field) => {
        const id = `${idPrefix}-${field.key}`;
        const value = values[field.key] ?? "";
        const set = (next: string) => onValues({ ...values, [field.key]: next });
        const isSaved = field.kind === "secret" && saved[field.key] === true;
        const optional = !field.required || field.default !== null || isSaved;
        return (
          <FormField
            key={field.key}
            label={optional ? `${field.label} (optional)` : field.label}
            htmlFor={id}
            description={isSaved ? "Saved. Leave it blank to keep it." : field.help || undefined}
          >
            {field.kind === "select" ? (
              <Select id={id} value={value} onChange={(event) => set(event.target.value)}>
                {field.options.map((option) => (
                  <option key={option} value={option}>
                    {optionWords(option)}
                  </option>
                ))}
              </Select>
            ) : field.kind === "boolean" ? (
              <input
                id={id}
                type="checkbox"
                checked={value === "true"}
                onChange={(event) => set(event.target.checked ? "true" : "false")}
                className="h-4 w-4"
              />
            ) : field.kind === "text" ? (
              <textarea
                id={id}
                value={value}
                onChange={(event) => set(event.target.value)}
                rows={4}
                placeholder={isSaved ? "Saved" : field.placeholder || undefined}
                className="border-line bg-sunken text-ink w-full rounded-xl border px-3 py-2 font-mono text-[13px] outline-none focus:border-[color:var(--accent)]"
              />
            ) : (
              <Input
                id={id}
                type={field.kind === "secret" ? "password" : field.kind === "number" ? "number" : "text"}
                value={value}
                onChange={(event) => set(event.target.value)}
                placeholder={isSaved ? "Saved" : field.placeholder || undefined}
                autoComplete={field.kind === "secret" ? "new-password" : "off"}
              />
            )}
          </FormField>
        );
      })}

      {followsTables ? (
        <div className="space-y-2">
          <FormField
            label={kind.key === "mongodb_cdc" ? "Collections to follow" : "Tables to follow"}
            htmlFor={`${idPrefix}-tables`}
            description="Separate several with commas. Each is kept as a dataset of its own, as it is now: a first full copy, then its changes."
          >
            <Input
              id={`${idPrefix}-tables`}
              value={tables}
              onChange={(event) => onTables(event.target.value)}
              placeholder={kind.key === "mongodb_cdc" ? "orders, customers" : "public.orders, public.customers"}
            />
          </FormField>
          {kind.connection_types.length ? (
            <div className="space-y-2">
              <Button variant="ghost" size="sm" disabled={!connectionId || finding} onClick={() => void find()}>
                {finding ? "Listing…" : kind.key === "mongodb_cdc" ? "List its collections" : "List its tables"}
              </Button>
              {findError ? <p className="text-[13px] text-danger">{findError}</p> : null}
              {found ? (
                found.length ? (
                  <ul className="flex max-h-40 flex-wrap gap-2 overflow-auto">
                    {found.map((name) => (
                      <li key={name}>
                        <button
                          type="button"
                          onClick={() => toggle(name)}
                          aria-pressed={chosen.includes(name)}
                          className={
                            chosen.includes(name)
                              ? "rounded-full border border-accent-line bg-accent-soft px-3 py-1 text-[13px] text-accent"
                              : "rounded-full border border-line bg-surface px-3 py-1 text-[13px] text-ink-2 hover:border-[color:var(--accent)]"
                          }
                        >
                          {name}
                        </button>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-[13px] text-ink-3">The connection lists nothing to follow.</p>
                )
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

/** A setting's option as a person would read it. */
function optionWords(option: string): string {
  const words: Record<string, string> = {
    earliest: "Everything it still keeps",
    latest: "Only what arrives from now",
    PLAINTEXT: "None",
    SSL: "Encrypted (TLS)",
    SASL_PLAINTEXT: "Signed in, not encrypted",
    SASL_SSL: "Signed in and encrypted",
  };
  return words[option] ?? option;
}
