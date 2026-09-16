"use client";

import { useCallback, useEffect, useState } from "react";

import { Button } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { cx } from "@/lib/utils";

/**
 * The recipe as code.
 *
 * Both directions, which is the whole point: edit the YAML and the visual
 * recipe updates, edit visually and the YAML updates. That is what lets a team
 * keep a recipe in git and review it in a pull request without giving up the
 * editor.
 *
 * The server owns the format. Parsing YAML here would be a second
 * implementation of a contract that has to be exact, and it would drift.
 */
export function RecipeYamlPanel({
  steps,
  onApply,
  onClose,
}: {
  steps: { step_type: string; config: Record<string, unknown> }[];
  onApply: (steps: { step_type: string; config: Record<string, unknown> }[]) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const [edited, setEdited] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  // Render whatever the recipe currently is, until somebody starts typing --
  // overwriting their edit because a step changed elsewhere would lose work.
  useEffect(() => {
    if (edited) return;
    let cancelled = false;
    apiFetch<{ yaml: string }>("/workbench/recipe/yaml", {
      method: "POST",
      body: JSON.stringify({ steps }),
    })
      .then((response) => {
        if (!cancelled) setText(response.yaml);
      })
      .catch((error) => {
        if (!cancelled) setProblem(extractErrorMessage(error));
      });
    return () => {
      cancelled = true;
    };
  }, [steps, edited]);

  const apply = useCallback(async () => {
    setBusy(true);
    try {
      const parsed = await apiFetch<{ steps: { step_type: string; config: Record<string, unknown> }[] }>(
        "/workbench/recipe/parse",
        { method: "POST", body: JSON.stringify({ yaml: text }) },
      );
      onApply(parsed.steps);
      setProblem(null);
      setEdited(false);
    } catch (error) {
      setProblem(extractErrorMessage(error));
    } finally {
      setBusy(false);
    }
  }, [text, onApply]);

  const download = useCallback(() => {
    const url = URL.createObjectURL(new Blob([text], { type: "text/yaml" }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = "recipe.yaml";
    anchor.click();
    URL.revokeObjectURL(url);
  }, [text]);

  return (
    <div className="flex h-full min-h-0 flex-col gap-3">
      <p className="text-xs text-muted">
        The steps above, as a file. Edit it and press Apply, or keep it in git and review
        changes in a pull request.
      </p>

      <textarea
        value={text}
        onChange={(event) => {
          setText(event.target.value);
          setEdited(true);
          setProblem(null);
        }}
        spellCheck={false}
        aria-label="Recipe as YAML"
        className={cx(
          "min-h-0 flex-1 resize-none rounded-xl border bg-sunken p-3 font-mono text-[12px] leading-5 text-ink outline-none",
          problem ? "border-[color:var(--danger-line)]" : "border-line",
        )}
      />

      {problem ? (
        <p className="rounded-lg border border-[color:var(--danger-line)] bg-[color:var(--danger-soft)] px-3 py-2 text-xs text-ink">
          {problem}
        </p>
      ) : null}

      <div className="flex flex-wrap justify-end gap-2">
        <Button variant="ghost" size="sm" onClick={download} disabled={!text}>
          Download
        </Button>
        {edited ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              setEdited(false);
              setProblem(null);
            }}
          >
            Discard edits
          </Button>
        ) : null}
        <Button size="sm" onClick={() => void apply()} disabled={busy || !edited}>
          {busy ? "Applying…" : "Apply to recipe"}
        </Button>
        <Button variant="ghost" size="sm" onClick={onClose}>
          Close
        </Button>
      </div>
    </div>
  );
}
