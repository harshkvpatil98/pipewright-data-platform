"use client";

import { useEffect, useState } from "react";

import type { SessionPolicy } from "@platform/shared-types";
import { Button, FormField, Textarea } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

import type { Organisation } from "./organisations-page";

type NetworkAccessProps = {
  organisation: Organisation;
  onSaved: (organisation: Organisation) => void;
};

/**
 * Where an organisation's people may connect from. Empty means anywhere; with
 * a list, sign-in and every request from elsewhere are refused, API tokens
 * included. The server refuses a list that would lock out whoever saves it.
 */
export function NetworkAccess({ organisation, onSaved }: NetworkAccessProps) {
  const [value, setValue] = useState((organisation.allowed_networks ?? []).join("\n"));
  const [address, setAddress] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    apiFetch<SessionPolicy>("/auth/session-policy")
      .then((policy) => setAddress(policy.address))
      .catch(() => setAddress(null));
  }, []);

  const save = async () => {
    setBusy(true);
    setError(null);
    setSaved(false);
    try {
      const entries = value.split(/[\n,]+/).map((line) => line.trim()).filter(Boolean);
      const updated = await apiFetch<Organisation>(`/organisations/${organisation.id}`, {
        method: "PATCH",
        body: JSON.stringify({ allowed_networks: entries }),
      });
      setValue((updated.allowed_networks ?? []).join("\n"));
      setSaved(true);
      onSaved(updated);
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const listed = organisation.allowed_networks ?? [];
  return (
    <div className="mt-3 border-t border-line pt-3">
      <FormField
        label="Where its people can connect from"
        htmlFor={`networks-${organisation.id}`}
        description={
          listed.length > 0
            ? "Sign-in and every request from anywhere else are refused, API tokens included. Leave it empty to allow anywhere."
            : "Anywhere, for now. Add an address or range per line, such as 203.0.113.7 or 10.0.0.0/8."
        }
        error={error ?? undefined}
      >
        <Textarea
          id={`networks-${organisation.id}`}
          rows={3}
          value={value}
          onChange={(event) => {
            setValue(event.target.value);
            setSaved(false);
          }}
          placeholder={"203.0.113.0/24\n10.0.0.0/8"}
          className="font-mono"
        />
      </FormField>
      <div className="mt-2 flex flex-wrap items-center gap-3">
        <Button size="sm" disabled={busy} onClick={() => void save()}>
          {busy ? "Saving…" : "Save the list"}
        </Button>
        {address ? <span className="text-[13px] text-ink-3">You are connecting from {address}.</span> : null}
        {saved ? <span className="text-[13px] text-success">Saved.</span> : null}
      </div>
    </div>
  );
}
