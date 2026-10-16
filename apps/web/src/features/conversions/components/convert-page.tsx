"use client";

import Link from "next/link";
import { useRef, useState } from "react";

import type { AuthUser } from "@platform/shared-types";
import {
  Badge,
  Button,
  buttonClassName,
  FormField,
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

import { AppShell } from "@/components/layout/app-shell";
import {
  countsWords,
  MADE_TONE,
  madeHref,
  madeWords,
  reportMarkdown,
  STATUS_TONE,
  visibleSections,
  type ConversionFormat,
  type ConversionPreview,
  type ConversionResult,
} from "@/features/conversions/conversion-words";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { countOf } from "@/lib/format";

type ConvertPageProps = {
  currentUser: AuthUser;
  projectId: string;
  formats: ConversionFormat[];
};

/**
 * Bring work in from another tool (E2, X3): a dbt project, an Airflow workflow, an
 * Alteryx workflow, an Informatica mapping, an SSIS package, a Talend job or
 * a Power Query. Reading the file changes nothing; it says, part by part,
 * what it would make and why the rest would not be, and asks for the
 * datasets it reads that this project does not have by that name.
 */
export function ConvertPageView({ currentUser, projectId, formats }: ConvertPageProps) {
  const toast = useToast();
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [preview, setPreview] = useState<ConversionPreview | null>(null);
  const [result, setResult] = useState<ConversionResult | null>(null);
  const [busy, setBusy] = useState<"reading" | "making" | null>(null);
  const [onlyProblems, setOnlyProblems] = useState(false);

  const body = (chosen: File, choices: Record<string, string>) => {
    const form = new FormData();
    form.append("file", chosen);
    if (Object.keys(choices).length) form.append("mapping", JSON.stringify(choices));
    return form;
  };

  const read = async (chosen: File, choices: Record<string, string>) => {
    setBusy("reading");
    setResult(null);
    try {
      setPreview(
        await apiFetch<ConversionPreview>(`/projects/${projectId}/conversions/preview`, {
          method: "POST",
          body: body(chosen, choices),
        }),
      );
    } catch (caught) {
      setPreview(null);
      toast.error("Could not read that file", extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const choose = (chosen: File | undefined) => {
    if (!chosen) return;
    setFile(chosen);
    setMapping({});
    void read(chosen, {});
    if (fileInput.current) fileInput.current.value = "";
  };

  const pick = (key: string, datasetId: string) => {
    if (!file) return;
    const next = { ...mapping };
    if (datasetId) next[key] = datasetId;
    else delete next[key];
    setMapping(next);
    void read(file, next);
  };

  const make = async () => {
    if (!file) return;
    setBusy("making");
    try {
      const made = await apiFetch<ConversionResult>(`/projects/${projectId}/conversions`, {
        method: "POST",
        body: body(file, mapping),
      });
      setResult(made);
      setPreview(made);
      const count = made.made.filter((item) => item.status === "made").length;
      toast.success("Converted", `${countOf(count, "thing")} made in this project.`);
    } catch (caught) {
      toast.error("Could not make it", extractErrorMessage(caught));
    } finally {
      setBusy(null);
    }
  };

  const downloadReport = () => {
    if (!preview) return;
    const blob = new Blob([reportMarkdown(preview)], { type: "text/markdown" });
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = `conversion-report-${preview.format}.md`;
    link.click();
    URL.revokeObjectURL(link.href);
  };

  const sections = preview ? visibleSections(preview.sections, onlyProblems) : [];
  const accepted = formats.flatMap((format) => format.extensions).join(",");
  const nothing = preview !== null && preview.recipes.length + preview.checks.length + preview.seeds.length +
    preview.workflows.length === 0;

  return (
    <AppShell
      currentUser={currentUser}
      title="Bring work in"
      subtitle="Convert another tool's work into recipes, checks and workflows here."
      actions={
        <Link href={`/projects/${projectId}/pipelines`} className={buttonClassName("secondary")}>
          Back to recipes
        </Link>
      }
    >
      <SectionPanel
        title="Choose a file"
        description="Reading it changes nothing: you see what it would make, part by part, and why anything would not be."
      >
        <ul className="mb-4 grid gap-2 text-[13px] text-ink-2 sm:grid-cols-2">
          {formats.map((format) => (
            <li key={format.key} className="rounded-xl border border-line bg-sunken px-3 py-2">
              <span className="font-medium text-ink">{format.title.charAt(0).toUpperCase() + format.title.slice(1)}</span>
              <span className="block text-ink-3">{format.upload}</span>
            </li>
          ))}
        </ul>
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => fileInput.current?.click()} disabled={busy !== null}>
            {busy === "reading" ? "Reading…" : file ? "Choose another file" : "Choose a file"}
          </Button>
          {file ? <span className="text-[13px] text-ink-2">{file.name}</span> : null}
          <input
            ref={fileInput}
            type="file"
            accept={accepted}
            className="hidden"
            aria-label="File to convert"
            onChange={(event) => choose(event.target.files?.[0])}
          />
        </div>
      </SectionPanel>

      {preview ? (
        <SectionPanel
          title={`Converting ${preview.title}`}
          description={`${countsWords(preview.counts)}. It makes ${madeWords(preview).toLowerCase()}.`}
          actions={
            <div className="flex flex-wrap gap-2">
              <Button variant="secondary" size="sm" onClick={downloadReport}>
                Download the report
              </Button>
              <Button size="sm" onClick={() => void make()} disabled={busy !== null || nothing || result !== null}>
                {busy === "making" ? "Making it…" : result ? "Made" : "Make it in this project"}
              </Button>
            </div>
          }
        >
          {preview.needs.length ? (
            <div className="mb-5 space-y-3">
              <h3 className="text-[13px] font-semibold text-ink">What it reads</h3>
              <p className="text-[13px] text-ink-3">
                Each is a dataset this project has, matched by its name. Choose another where the match is wrong or missing,
                and the file is read again.
              </p>
              <div className="grid gap-3 md:grid-cols-2">
                {preview.needs.map((need, index) => (
                  <FormField
                    key={need.key}
                    label={need.what.charAt(0).toUpperCase() + need.what.slice(1)}
                    htmlFor={`conversion-need-${index}`}
                    description={need.status === "missing" ? need.reason ?? "No dataset here matches it." : need.columns.length ?
                      `It reads ${need.columns.slice(0, 6).join(", ")}${need.columns.length > 6 ? " and more" : ""}.` : undefined}
                  >
                    <Select
                      id={`conversion-need-${index}`}
                      value={mapping[need.key] ?? need.dataset_id ?? ""}
                      onChange={(event) => pick(need.key, event.target.value)}
                      disabled={busy !== null || result !== null}
                    >
                      <option value="">{need.status === "missing" ? "Choose a dataset…" : "Match by name"}</option>
                      {preview.choices.map((choice) => (
                        <option key={choice.id} value={choice.id}>
                          {choice.name}
                        </option>
                      ))}
                    </Select>
                  </FormField>
                ))}
              </div>
            </div>
          ) : null}

          {result ? (
            <div className="mb-5 space-y-2">
              <h3 className="text-[13px] font-semibold text-ink">What was made</h3>
              <Table minWidth={560}>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>What</TableHeaderCell>
                    <TableHeaderCell>Name</TableHeaderCell>
                    <TableHeaderCell>Done</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {result.made.map((item) => {
                    const href = madeHref(projectId, item);
                    return (
                      <TableRow key={`${item.kind}:${item.key}`}>
                        <TableCell className="text-ink-3">{item.kind.charAt(0).toUpperCase() + item.kind.slice(1)}</TableCell>
                        <TableCell className="text-ink">
                          {href ? <Link className="text-accent hover:underline" href={href}>{item.name}</Link> : item.name}
                        </TableCell>
                        <TableCell>
                          <Badge tone={MADE_TONE[item.status]}>{item.status.charAt(0).toUpperCase() + item.status.slice(1)}</Badge>
                          {item.detail ? <span className="ml-2 text-[13px] text-ink-3">{item.detail}</span> : null}
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
            </div>
          ) : null}

          <div className="mb-3 flex items-center justify-between gap-3">
            <h3 className="text-[13px] font-semibold text-ink">Part by part</h3>
            <label className="flex items-center gap-2 text-[13px] text-ink-2">
              <input
                type="checkbox"
                checked={onlyProblems}
                onChange={(event) => setOnlyProblems(event.target.checked)}
                className="h-4 w-4 rounded border-line-strong bg-sunken"
              />
              Only what did not convert
            </label>
          </div>
          <div className="space-y-3">
            {sections.map((section) => (
              <details key={section.title} open={sections.length <= 8} className="rounded-xl border border-line bg-sunken px-3.5 py-2.5">
                <summary className="cursor-pointer text-[13px] font-medium text-ink">{section.title}</summary>
                <ul className="mt-2 space-y-2">
                  {section.entries.map((entry, index) => (
                    <li key={`${entry.subject}:${index}`} className="text-[13px]">
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={STATUS_TONE[entry.status]}>{entry.status.charAt(0).toUpperCase() + entry.status.slice(1)}</Badge>
                        <span className="text-ink">{entry.subject}</span>
                      </div>
                      {entry.reason ? <p className="mt-1 text-ink-2">{entry.reason}</p> : null}
                      {entry.became.length ? (
                        <ul className="mt-1 list-disc space-y-0.5 pl-5 text-ink-2">
                          {entry.became.map((line, lineIndex) => <li key={lineIndex}>{line}</li>)}
                        </ul>
                      ) : null}
                      {entry.notes.map((note, noteIndex) => (
                        <p key={noteIndex} className="mt-1 text-ink-3">Note: {note}</p>
                      ))}
                    </li>
                  ))}
                </ul>
              </details>
            ))}
            {!sections.length ? <p className="text-[13px] text-ink-3">Every part converted.</p> : null}
          </div>
          {preview.notes.length ? (
            <p className="mt-4 text-[13px] text-ink-3">{preview.notes.join(" ")}</p>
          ) : null}
        </SectionPanel>
      ) : null}
    </AppShell>
  );
}
