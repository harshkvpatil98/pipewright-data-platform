"use client";

import { useRef, useState } from "react";
import { useRouter } from "next/navigation";

import type { DatasetUploadResponse } from "@platform/shared-types";
import { Button, FormField, Input, Modal } from "@platform/shared-ui";

import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import { appConfig } from "@/lib/config";
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

  const reset = () => {
    setName("");
    setFile(null);
    setDragActive(false);
    setError(null);
    setSubmitting(false);
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

    try {
      setError(null);
      setSubmitting(true);
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

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Upload dataset"
      description="Upload a csv, xlsx, or json file to create a dataset, profile it, and store a real ingestion run."
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" form="upload-dataset-form" disabled={submitting || !file || name.trim().length < 2}>
            {submitting ? "Creating dataset..." : "Upload dataset"}
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
            Supported formats: csv, xlsx, json. Maximum size: {formatBytes(appConfig.maxUploadSizeBytes)}.
            Uploads are stored through the platform storage layer and immediately profiled.
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
        {submitting ? (
          <div className="rounded-2xl border border-line bg-surface px-4 py-3 text-sm text-ink-2">
            Validating the upload, storing the file, and generating the initial schema, preview, and profile.
          </div>
        ) : null}
      </form>
    </Modal>
  );
}
