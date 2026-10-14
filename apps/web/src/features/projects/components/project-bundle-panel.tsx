"use client";

import { useRouter } from "next/navigation";
import { useRef, useState } from "react";

import {
  Badge,
  Button,
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
  useToast,
} from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf } from "@/lib/format";

type BundleItem = { section: string; kind: string; name: string; action: "create" | "skip"; reason: string | null };
type BundleReference = { kind: string; name: string; status: "matched" | "chosen" | "missing" | "made"; id: string | null; used_by: string[] };
type BundlePreview = {
  items: BundleItem[];
  references: BundleReference[];
  choices: Record<string, { id: string; name: string }[]>;
  creates: number;
  skips: number;
};
type BundleResult = BundlePreview & { made: { section: string; name: string; id: string }[] };

const KIND_WORDS: Record<string, string> = {
  dataset: "Dataset",
  import: "Import",
  destination: "Destination",
  connection: "Connection",
};

/** "Dataset “Orders”, used by the recipe “Clean”" for a reference the project lacks. */
export function referenceWords(reference: Pick<BundleReference, "kind" | "name" | "used_by">): string {
  const used = reference.used_by.length ? `, used by the ${reference.used_by.slice(0, 2).join(" and the ")}` : "";
  const more = reference.used_by.length > 2 ? ` and ${countOf(reference.used_by.length - 2, "more")}` : "";
  return `${KIND_WORDS[reference.kind] ?? reference.kind} “${reference.name}”${used}${more}`;
}

/**
 * Move a project's work: its recipes, checks, metrics, charts, dashboards,
 * workflows and schedules, as one file (A8, Y2). Importing previews first,
 * and asks for anything the bundle needs that this project lacks.
 */
export function ProjectBundlePanel({ projectId, projectName }: { projectId: string; projectName: string }) {
  const router = useRouter();
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [bundle, setBundle] = useState<Record<string, unknown> | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<BundlePreview | null>(null);
  const [busy, setBusy] = useState(false);

  const download = async () => {
    try {
      const exported = await apiFetch<Record<string, unknown>>(`/projects/${projectId}/bundle`);
      const blob = new Blob([JSON.stringify(exported, null, 2)], { type: "application/json" });
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = `${projectName.replace(/[^A-Za-z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase() || "project"}-bundle.json`;
      link.click();
      URL.revokeObjectURL(link.href);
    } catch (caught) {
      toast.error("Could not make the bundle", extractErrorMessage(caught));
    }
  };

  const look = async (next: Record<string, unknown>, choices: Record<string, string>) => {
    setBusy(true);
    try {
      setPreview(
        await apiFetch<BundlePreview>(`/projects/${projectId}/bundle/preview`, {
          method: "POST",
          body: JSON.stringify({ bundle: next, mapping: choices }),
        }),
      );
    } catch (caught) {
      toast.error("Could not read the bundle", extractErrorMessage(caught));
      setBundle(null);
    } finally {
      setBusy(false);
    }
  };

  const choose = async (file: File | undefined) => {
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as Record<string, unknown>;
      setBundle(parsed);
      setMapping({});
      await look(parsed, {});
    } catch {
      toast.error("Could not read the bundle", "That file is not a bundle. Download one from a project's Settings.");
    } finally {
      if (fileInput.current) fileInput.current.value = "";
    }
  };

  const pick = (reference: BundleReference, id: string) => {
    if (!bundle) return;
    const key = `${reference.kind}:${reference.name}`;
    const next = { ...mapping };
    if (id) next[key] = id;
    else delete next[key];
    setMapping(next);
    void look(bundle, next);
  };

  const importNow = async () => {
    if (!bundle) return;
    setBusy(true);
    try {
      const result = await apiFetch<BundleResult>(`/projects/${projectId}/bundle/import`, {
        method: "POST",
        body: JSON.stringify({ bundle, mapping }),
      });
      toast.success("Imported", `${countOf(result.made.length, "thing")} made; ${countOf(result.skips, "thing")} skipped.`);
      setBundle(null);
      setPreview(null);
      router.refresh();
    } catch (caught) {
      toast.error("Could not import the bundle", extractErrorMessage(caught));
    } finally {
      setBusy(false);
    }
  };

  const unresolved = (preview?.references ?? []).filter(
    (reference) => (reference.status === "missing" || reference.status === "chosen") && reference.kind in KIND_WORDS,
  );

  return (
    <>
      <SectionPanel
        title="Move this project's work"
        description="Take its recipes, checks, metrics, charts, dashboards, workflows and schedules to another project. Data and passwords stay here."
      >
        <div className="flex flex-wrap gap-2">
          <Button variant="secondary" onClick={() => void download()}>
            Download a bundle
          </Button>
          <Button variant="secondary" onClick={() => fileInput.current?.click()} disabled={busy}>
            Import a bundle
          </Button>
          <input
            ref={fileInput}
            type="file"
            accept="application/json,.json"
            className="hidden"
            aria-label="Bundle file"
            onChange={(event) => void choose(event.target.files?.[0])}
          />
        </div>
      </SectionPanel>

      <Modal
        open={preview !== null}
        title="Import a bundle"
        description="What will be made in this project, and what will be left out and why. Nothing changes until you import."
        onClose={() => {
          setPreview(null);
          setBundle(null);
        }}
        widthClassName="max-w-3xl"
        footer={
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => { setPreview(null); setBundle(null); }}>
              Cancel
            </Button>
            <Button onClick={() => void importNow()} disabled={busy || !preview || preview.creates === 0}>
              {busy ? "Working…" : preview ? `Import ${countOf(preview.creates, "thing")}` : "Import"}
            </Button>
          </div>
        }
      >
        {preview ? (
          <div className="space-y-4">
            {unresolved.length ? (
              <div className="space-y-3 rounded-xl border border-warning-line bg-warning-soft px-3.5 py-3">
                <p className="text-[13px] font-medium text-ink">
                  This project lacks what some of it uses. Choose a stand-in, or leave it and those things are skipped.
                </p>
                {unresolved.map((reference, index) => (
                  <FormField key={`${reference.kind}:${reference.name}`} label={referenceWords(reference)} htmlFor={`bundle-reference-${index}`}>
                    <Select
                      value={mapping[`${reference.kind}:${reference.name}`] ?? ""}
                      onChange={(event) => pick(reference, event.target.value)}
                    >
                      <option value="">Leave it out</option>
                      {(preview.choices[reference.kind] ?? []).map((choice) => (
                        <option key={choice.id} value={choice.id}>
                          {choice.name}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                ))}
              </div>
            ) : null}
            <Table minWidth={520}>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>What</TableHeaderCell>
                  <TableHeaderCell>Name</TableHeaderCell>
                  <TableHeaderCell>Will it be made?</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {preview.items.map((item) => (
                  <TableRow key={`${item.section}:${item.name}`}>
                    <TableCell className="text-ink-3">{item.kind.charAt(0).toUpperCase() + item.kind.slice(1)}</TableCell>
                    <TableCell className="text-ink">{item.name}</TableCell>
                    <TableCell>
                      {item.action === "create" ? (
                        <Badge tone="success">Yes</Badge>
                      ) : (
                        <span className="text-[13px] text-ink-3">
                          <Badge tone="neutral">No</Badge> {item.reason}
                        </span>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </div>
        ) : null}
      </Modal>
    </>
  );
}
