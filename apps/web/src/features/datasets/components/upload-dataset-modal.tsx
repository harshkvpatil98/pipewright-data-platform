"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type {
  AnalyseUploadResponse,
  DatasetUploadResponse,
  IngestSpec,
} from "@platform/shared-types";
import { Button, FormField, Input, Modal } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { appConfig } from "@/lib/config";
import { IngestReviewPanel } from "@/features/datasets/components/ingest-review-panel";
import { blockingQuestions, specProblems } from "@/features/datasets/ingest-review";
import {
  formatBytes,
  getSupportedDatasetExtensions,
  validateDatasetUploadFile,
} from "@/features/datasets/upload-validation";

type UploadDatasetModalProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
};

export function UploadDatasetModal({ open, onClose, projectId }: UploadDatasetModalProps) {
  const router = useRouter();
  const inputRef = useRef<HTMLInputElement | null>(null);
  const supportedFormats = getSupportedDatasetExtensions();
  const [name, setName] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // The review step. `analysis` is what the file turned out to be; `spec` is
  // that answer as the person has edited it, and is what gets imported.
  const [analysis, setAnalysis] = useState<AnalyseUploadResponse | null>(null);
  const [spec, setSpec] = useState<IngestSpec | null>(null);
  const [analysing, setAnalysing] = useState(false);
  const [rememberAs, setRememberAs] = useState("");

  const reset = () => {
    setName("");
    setFile(null);
    setDragActive(false);
    setError(null);
    setSubmitting(false);
    setAnalysis(null);
    setSpec(null);
    setAnalysing(false);
    setRememberAs("");
    if (inputRef.current) {
      inputRef.current.value = "";
    }
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const acceptFile = (nextFile: File | null) => {
    const validationError = validateDatasetUploadFile(nextFile, appConfig.maxUploadSizeBytes);
    if (validationError) {
      setFile(null);
      setError(validationError);
      return;
    }

    if (!nextFile) {
      return;
    }

    setFile(nextFile);
    if (!name.trim()) {
      setName(nextFile.name.replace(/\.[^.]+$/, ""));
    }
    setError(null);
    setAnalysis(null);
    setSpec(null);
    void analyse(nextFile);
  };

  /**
   * Work out how to read the file, storing nothing.
   *
   * Runs the moment a file is chosen rather than on a button, because the
   * answer is what the person needs in order to decide anything else — and a
   * failure here costs nothing, since nothing has been written.
   */
  const analyse = async (target: File) => {
    const formData = new FormData();
    formData.append("file", target);
    try {
      setAnalysing(true);
      setError(null);
      const response = await apiFetch<AnalyseUploadResponse>(
        `/projects/${projectId}/datasets/analyze`,
        { method: "POST", body: formData },
      );
      setAnalysis(response);
      setSpec(response.spec);
    } catch (analyseError) {
      setError(extractErrorMessage(analyseError));
      setAnalysis(null);
      setSpec(null);
    } finally {
      setAnalysing(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (name.trim().length < 2) {
      setError("Dataset name must be at least 2 characters.");
      return;
    }
    const validationError = validateDatasetUploadFile(file, appConfig.maxUploadSizeBytes);
    if (validationError) {
      setError(validationError);
      return;
    }

    if (!file) {
      return;
    }

    const formData = new FormData();
    formData.append("file", file);
    // The spec the person has reviewed and edited travels with the file. It is
    // the whole point of the review step: the import reads the file the way
    // they confirmed, not the way a second inference pass would decide.
    if (spec) {
      formData.append("ingest_spec", JSON.stringify(spec));
    }

    try {
      setError(null);
      setSubmitting(true);

      if (spec && rememberAs.trim() && analysis) {
        // Saved before the import, so a failed import does not lose the
        // decisions somebody just made by hand.
        await apiFetch(`/projects/${projectId}/ingest-specs`, {
          method: "POST",
          body: JSON.stringify({
            label: rememberAs.trim(),
            file_name: file.name,
            spec,
            columns: analysis.preview.columns,
          }),
        });
      }

      const response = await apiFetch<DatasetUploadResponse>(
        `/projects/${projectId}/datasets/upload?dataset_name=${encodeURIComponent(name.trim())}`,
        {
          method: "POST",
          body: formData,
        },
      );
      handleClose();
      router.push(`/projects/${projectId}/datasets/${response.dataset.id}`);
      router.refresh();
    } catch (submitError) {
      setError(extractErrorMessage(submitError));
      setSubmitting(false);
    }
  };

  const questions = analysis ? blockingQuestions(analysis) : [];
  const problems = spec ? specProblems(spec) : [];
  const blocked = questions.length > 0 || problems.length > 0;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Upload dataset"
      description="Choose a file and the platform works out how to read it — separator, encoding, header row, every column's type — and shows you before anything is stored."
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="upload-dataset-form"
            disabled={submitting || analysing || blocked || !file || name.trim().length < 2}
            title={
              questions.length > 0
                ? "Answer the questions above first."
                : problems[0] ?? undefined
            }
          >
            {submitting ? "Creating dataset..." : analysis ? "Import as reviewed" : "Upload dataset"}
          </Button>
        </div>
      }
      widthClassName="max-w-3xl"
    >
      <form id="upload-dataset-form" className="space-y-5" onSubmit={handleSubmit}>
        <FormField
          label="Dataset name"
          htmlFor="dataset-upload-name"
          description="This will become the project-scoped dataset label shown in the workspace."
        >
          <Input
            id="dataset-upload-name"
            value={name}
            onChange={(event) => setName(event.target.value)}
            placeholder="Customer orders April"
          />
        </FormField>

        <div>
          <div className="mb-2 text-sm font-medium text-ink">Source file</div>
          <p className="mb-3 text-xs leading-5 text-ink-3">
            Spreadsheets, delimited text, JSON, XML, Parquet, Avro, ORC, SQL dumps and the
            statistical formats — compressed or not. Maximum size:{" "}
            {formatBytes(appConfig.maxUploadSizeBytes)}. The contents decide the format, so a
            file with the wrong extension still reads correctly.
          </p>
          <button
            type="button"
            onClick={() => inputRef.current?.click()}
            onDragOver={(event) => {
              event.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragActive(false);
              acceptFile(event.dataTransfer.files[0] ?? null);
            }}
            className={[
              "flex min-h-[180px] w-full flex-col items-center justify-center rounded-[24px] border border-dashed px-6 py-8 text-center transition",
              dragActive
                ? "border-[color:var(--accent)] bg-[color:var(--accent-faint)]"
                : "border-line bg-surface hover:border-line-strong hover:bg-surface",
            ].join(" ")}
          >
            <div className="text-sm font-medium text-ink">
              {file ? file.name : "Drag and drop a file here"}
            </div>
            <div className="mt-2 text-sm text-ink-3">
              {file ? `${Math.round(file.size / 1024)} KB selected` : "or click to browse your local files"}
            </div>
          </button>
          <input
            ref={inputRef}
            type="file"
            hidden
            accept={supportedFormats.join(",")}
            onChange={(event) => acceptFile(event.target.files?.[0] ?? null)}
          />
        </div>

        {error ? (
          <div className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger">
            {error}
          </div>
        ) : null}

        {analysing ? (
          <div className="rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-ink-2">
            Working out how to read this file. Nothing has been stored.
          </div>
        ) : null}

        {analysis && spec ? (
          <>
            <IngestReviewPanel analysis={analysis} spec={spec} onSpecChange={setSpec} />

            {problems.length > 0 ? (
              <div className="rounded-2xl border border-warning-line bg-warning-soft px-4 py-3 text-sm text-warning">
                <ul className="space-y-1">
                  {problems.map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            <FormField
              label="Remember these settings (optional)"
              htmlFor="dataset-upload-remember"
              description="Give this a name and the next file with the same columns is read the same way, rather than inferred again from different data."
            >
              <Input
                id="dataset-upload-remember"
                value={rememberAs}
                onChange={(event) => setRememberAs(event.target.value)}
                placeholder="Monthly bank statement"
              />
            </FormField>
          </>
        ) : null}

        {submitting ? (
          <div className="rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-ink-2">
            Storing the file and generating the schema, preview and profile.
          </div>
        ) : null}
      </form>
    </Modal>
  );
}
