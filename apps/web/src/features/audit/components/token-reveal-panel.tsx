"use client";

import { useState } from "react";

import { Button, Input, SectionPanel } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

/**
 * Turning a reversible token back into its value (E1): the tokenise tool in
 * a recipe replaces a value with a token only this deployment's key turns
 * back. An administrator only, and each reveal is in the audit trail above.
 */
export function TokenRevealPanel() {
  const [token, setToken] = useState("");
  const [keyName, setKeyName] = useState("default");
  const [value, setValue] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const reveal = async () => {
    setBusy(true);
    setProblem(null);
    setValue(null);
    try {
      const answer = await apiFetch<{ value: string }>("/transformations/tokens/reveal", {
        method: "POST",
        body: JSON.stringify({ token: token.trim(), key_name: keyName.trim() || "default" }),
      });
      setValue(answer.value);
    } catch (caught) {
      setProblem(extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  return (
    <SectionPanel
      title="Reveal a token"
      description="A recipe's tokenise step replaces a value with a token that only this deployment's key turns back. Each reveal is recorded in the audit trail."
    >
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-[260px] flex-1 flex-col gap-1">
          <span className="text-xs text-muted">Token</span>
          <Input
            value={token}
            onChange={(event) => setToken(event.target.value)}
            placeholder="tok_…"
            spellCheck={false}
            autoComplete="off"
          />
        </label>
        <label className="flex w-44 flex-col gap-1">
          <span className="text-xs text-muted">Key name</span>
          <Input value={keyName} onChange={(event) => setKeyName(event.target.value)} autoComplete="off" />
        </label>
        <Button variant="secondary" disabled={busy || !token.trim().startsWith("tok_")} onClick={() => void reveal()}>
          {busy ? "Revealing…" : "Reveal"}
        </Button>
      </div>
      {value !== null ? (
        <p className="mt-3 rounded-lg border border-line bg-sunken px-3 py-2 font-mono text-[13px] text-ink">{value}</p>
      ) : null}
      {problem ? <p className="mt-3 text-[13px] text-danger">{problem}</p> : null}
    </SectionPanel>
  );
}
