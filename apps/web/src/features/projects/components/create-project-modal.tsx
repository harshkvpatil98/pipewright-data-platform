"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Button, FormField, Input, Modal, Select, Textarea } from "@platform/shared-ui";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import type { CreateProjectPayload, ProjectDetail, ProjectStatus } from "@platform/shared-types";

type CreateProjectModalProps = {
  open: boolean;
  onClose: () => void;
};

const initialState = {
  name: "",
  description: "",
  status: "active" as ProjectStatus,
  slug: "",
};

export function CreateProjectModal({ open, onClose }: CreateProjectModalProps) {
  const router = useRouter();
  const [form, setForm] = useState(initialState);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const slugHint = useMemo(() => {
    if (form.slug.trim()) {
      return form.slug.trim();
    }
    return form.name
      .toLowerCase()
      .trim()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "");
  }, [form.name, form.slug]);

  const reset = () => {
    setForm(initialState);
    setError(null);
    setSubmitting(false);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError(null);

    if (form.name.trim().length < 2) {
      setError("Give the project a name of at least two characters.");
      return;
    }

    if (form.slug.trim() && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(form.slug.trim())) {
      setError("The short name can only use lowercase letters, numbers and hyphens.");
      return;
    }

    const payload: CreateProjectPayload = {
      name: form.name.trim(),
      description: form.description.trim() || null,
      status: form.status,
      slug: form.slug.trim() || null,
    };

    try {
      setSubmitting(true);
      const project = await apiFetch<ProjectDetail>("/projects", {
        method: "POST",
        body: JSON.stringify(payload),
      });
      handleClose();
      router.push(`/projects/${project.id}`);
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
      title="New project"
      description="A project keeps one team's or one subject's data, recipes and dashboards together."
      widthClassName="max-w-lg"
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button
            type="submit"
            form="create-project-form"
            disabled={submitting || form.name.trim().length < 2}
          >
            {submitting ? "Creating…" : "Create project"}
          </Button>
        </div>
      }
    >
      <form id="create-project-form" className="space-y-5" onSubmit={handleSubmit}>
        <FormField label="Name" htmlFor="project-name">
          <Input
            id="project-name"
            value={form.name}
            onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
            placeholder="Sales reporting"
            autoFocus
          />
        </FormField>
        <FormField label="What it is for (optional)" htmlFor="project-description">
          <Textarea
            id="project-description"
            value={form.description}
            onChange={(event) =>
              setForm((current) => ({ ...current, description: event.target.value }))
            }
            placeholder="Weekly sales numbers for the regional managers."
            rows={2}
          />
        </FormField>
        <details className="rounded-xl border border-line px-3 py-2">
          <summary className="cursor-pointer text-[13px] text-ink-2">More options</summary>
          <div className="mt-3 space-y-4">
            <FormField label="Status" htmlFor="project-status">
              <Select
                id="project-status"
                value={form.status}
                onChange={(event) =>
                  setForm((current) => ({ ...current, status: event.target.value as ProjectStatus }))
                }
              >
                <option value="active">Active</option>
                <option value="draft">Draft: still being set up</option>
              </Select>
            </FormField>
            <FormField
              label="Short name for links"
              htmlFor="project-slug"
              description={
                slugHint
                  ? `Leave blank to use ${slugHint}. Lowercase letters, numbers and hyphens.`
                  : "Made from the name if left blank."
              }
            >
              <Input
                id="project-slug"
                value={form.slug}
                onChange={(event) =>
                  setForm((current) => ({ ...current, slug: event.target.value.toLowerCase() }))
                }
                placeholder={slugHint || "sales-reporting"}
              />
            </FormField>
          </div>
        </details>
        {error ? (
          <div
            role="alert"
            className="rounded-2xl border border-danger-line bg-danger-soft px-4 py-3 text-sm text-danger"
          >
            {error}
          </div>
        ) : null}
      </form>
    </Modal>
  );
}
