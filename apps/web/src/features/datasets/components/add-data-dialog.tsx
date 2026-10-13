"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import type { DatasetUploadResponse } from "@platform/shared-types";
import { Button, Icon, type IconName, Modal } from "@platform/shared-ui";

import { UploadDatasetModal } from "@/features/datasets/components/upload-dataset-modal";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";

type Sample = {
  id: string;
  name: string;
  description: string;
  columns: string[];
  row_count: number;
};

type AddDataDialogProps = {
  open: boolean;
  onClose: () => void;
  projectId: string;
};

/**
 * Every way data gets into a project, on one screen: a file, a database, or a
 * sample. The sample is for the person who has nothing to hand yet, or does
 * not want to put real data into something they are still trying out.
 */
export function AddDataDialog({ open, onClose, projectId }: AddDataDialogProps) {
  const router = useRouter();
  const [uploadOpen, setUploadOpen] = useState(false);
  const [samples, setSamples] = useState<Sample[] | null>(null);
  const [adding, setAdding] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || samples) return;
    apiFetch<{ items: Sample[] }>("/samples")
      .then((response) => setSamples(response.items))
      .catch(() => setSamples([]));
  }, [open, samples]);

  const addSample = async (sample: Sample) => {
    setAdding(sample.id);
    setError(null);
    try {
      const response = await apiFetch<DatasetUploadResponse>(
        `/projects/${projectId}/samples/${sample.id}`,
        { method: "POST" },
      );
      onClose();
      router.push(`/projects/${projectId}/datasets/${response.dataset.id}`);
      router.refresh();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setAdding(null);
    }
  };

  return (
    <>
      <Modal
        open={open && !uploadOpen}
        title="Add data"
        description="Bring in a file, connect a source, or start with sample data."
        onClose={onClose}
        widthClassName="max-w-xl"
      >
        <div className="space-y-3">
          <Choice
            icon="upload"
            title="Upload a file"
            description="CSV, Excel, JSON, Parquet and more. You see how it will be read before anything is saved."
            action={
              <Button size="sm" onClick={() => setUploadOpen(true)}>
                Choose a file
              </Button>
            }
          />
          <Choice
            icon="link"
            title="Connect a source"
            description="A database, an app such as GitHub or HubSpot, an API or a storage bucket. Import once or keep it up to date."
            action={
              <Button
                size="sm"
                variant="secondary"
                onClick={() => {
                  onClose();
                  router.push(`/projects/${projectId}/sources?connect=1`);
                }}
              >
                Connect
              </Button>
            }
          />

          <section className="rounded-2xl border border-line bg-surface p-4">
            <div className="flex items-start gap-3">
              <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[color:var(--accent-faint)] text-[color:var(--accent-muted)]">
                <Icon name="sparkles" size={17} />
              </span>
              <div className="min-w-0 flex-1">
                <h3 className="text-[15px] font-semibold text-ink">Try sample data</h3>
                <p className="mt-0.5 text-[13px] leading-5 text-ink-3">
                  A small, slightly untidy shop: orders, customers and invoices that share customer
                  ids. Good for trying the cleaning tools and checks.
                </p>
              </div>
            </div>
            {error ? (
              <p role="alert" className="mt-3 text-[13px] text-danger">
                {error}
              </p>
            ) : null}
            <ul className="mt-3 divide-y divide-line rounded-xl border border-line">
              {samples === null ? (
                <li className="px-3 py-3 text-[13px] text-muted">Loading…</li>
              ) : samples.length === 0 ? (
                <li className="px-3 py-3 text-[13px] text-muted">
                  Sample data is not available on this server.
                </li>
              ) : (
                samples.map((sample) => (
                  <li key={sample.id} className="flex items-center justify-between gap-3 px-3 py-2.5">
                    <div className="min-w-0">
                      <div className="text-[14px] font-medium text-ink">{sample.name}</div>
                      <div className="text-[12.5px] text-ink-3">
                        {sample.row_count} rows · {sample.description}
                      </div>
                    </div>
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={adding !== null}
                      onClick={() => void addSample(sample)}
                    >
                      {adding === sample.id ? "Adding…" : "Add"}
                    </Button>
                  </li>
                ))
              )}
            </ul>
          </section>
        </div>
      </Modal>

      <UploadDatasetModal
        open={open && uploadOpen}
        onClose={() => {
          setUploadOpen(false);
          onClose();
        }}
        projectId={projectId}
      />
    </>
  );
}

function Choice({
  icon,
  title,
  description,
  action,
}: {
  icon: IconName;
  title: string;
  description: string;
  action: React.ReactNode;
}) {
  return (
    <section className="flex items-center gap-3 rounded-2xl border border-line bg-surface p-4">
      <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-[color:var(--accent-faint)] text-[color:var(--accent-muted)]">
        <Icon name={icon} size={17} />
      </span>
      <div className="min-w-0 flex-1">
        <h3 className="text-[15px] font-semibold text-ink">{title}</h3>
        <p className="mt-0.5 text-[13px] leading-5 text-ink-3">{description}</p>
      </div>
      <div className="shrink-0">{action}</div>
    </section>
  );
}
