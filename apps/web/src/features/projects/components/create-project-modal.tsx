"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { Button } from "@platform/shared-ui";
import { FormField } from "@platform/shared-ui";
import { Input } from "@platform/shared-ui";
import { Modal } from "@platform/shared-ui";
import { Select } from "@platform/shared-ui";
import { Textarea } from "@platform/shared-ui";
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
      setError("Project name must be at least 2 characters.");
      return;
    }

    if (form.slug.trim() && !/^[a-z0-9]+(?:-[a-z0-9]+)*$/.test(form.slug.trim())) {
      setError("Slug can only contain lowercase letters, numbers, and hyphens.");
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
      title="Create project"
      description="Create a new workspace for datasets, registered sources, and future pipeline execution."
      footer={
        <div className="flex items-center justify-end gap-3">
          <Button variant="secondary" onClick={handleClose} disabled={submitting}>
            Cancel
          </Button>
          <Button type="submit" form="create-project-form" disabled={submitting || form.name.trim().length < 2}>
            {submitting ? "Creating..." : "Create project"}
          </Button>
        </div>
      }
    >
      <form id="create-project-form" className="space-y-5" onSubmit={handleSubmit}>
        <div className="grid gap-5 lg:grid-cols-2">
          <FormField label="Project name" htmlFor="project-name" description="Use a descriptive workspace name for the data initiative.">
            <Input
              id="project-name"
              value={form.name}
              onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
              placeholder="Revenue quality monitoring"
              autoFocus
            />
          </FormField>
          <FormField label="Status" htmlFor="project-status" description="You can change status conventions later as lifecycle rules expand.">
            <Select
              id="project-status"
              value={form.status}
              onChange={(event) => setForm((current) => ({ ...current, status: event.target.value as ProjectStatus }))}
            >
              <option value="active">Active</option>
              <option value="draft">Draft</option>
              <option value="archived">Archived</option>
            </Select>
          </FormField>
        </div>
        <FormField label="Description" htmlFor="project-description" description="Capture the business purpose, scope, or ownership context.">
          <Textarea
            id="project-description"
            value={form.description}
            onChange={(event) => setForm((current) => ({ ...current, description: event.target.value }))}
            placeholder="Monitor inbound source registrations and dataset readiness for finance analytics."
          />
        </FormField>
        <FormField
          label="Optional slug"
          htmlFor="project-slug"
          description={slugHint ? `Suggested identifier: ${slugHint}` : "A stable URL-friendly identifier will be generated automatically if left blank."}
        >
          <Input
            id="project-slug"
            value={form.slug}
            onChange={(event) => setForm((current) => ({ ...current, slug: event.target.value.toLowerCase() }))}
            placeholder="revenue-quality-monitoring"
          />
        </FormField>
        {error ? <div className="rounded-2xl border border-rose-400/20 bg-rose-400/10 px-4 py-3 text-sm text-rose-200">{error}</div> : null}
      </form>
    </Modal>
  );
}
