"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button, SectionPanel } from "@platform/shared-ui";
import { ConfirmDeleteDialog } from "@/components/ui/confirm-delete-dialog";
import { apiFetch } from "@/lib/api/client";
import { extractErrorMessage } from "@/lib/api/errors";
import type { ProjectDetail } from "@platform/shared-types";

type ProjectSettingsPanelProps = {
  project: ProjectDetail;
};

const STATUS_OPTIONS = ["active", "draft", "archived"] as const;

/**
 * Renaming, describing, archiving and deleting a project.
 *
 * None of these were possible: a project was created and then permanent and
 * unnamed for ever, while its own card invited you to "add one" to a
 * description with no request that could. The slug is deliberately not
 * editable -- it is what links point at, and rewriting it when the display
 * name changes would break every bookmark aimed at the old one.
 */
export function ProjectSettingsPanel({ project }: ProjectSettingsPanelProps) {
  const router = useRouter();
  const [name, setName] = useState(project.name);
  const [description, setDescription] = useState(project.description ?? "");
  const [status, setStatus] = useState(project.status);
  const [saving, setSaving] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);

  const dirty =
    name.trim() !== project.name ||
    description.trim() !== (project.description ?? "") ||
    status !== project.status;

  const save = async () => {
    setSaving(true);
    setError(null);
    setFeedback(null);
    try {
      await apiFetch(`/projects/${project.id}`, {
        method: "PATCH",
        body: JSON.stringify({
          name: name.trim(),
          // An empty box means "no description", which the API takes as an
          // explicit null -- a different request from not mentioning it.
          description: description.trim() ? description.trim() : null,
          status,
        }),
      });
      setFeedback("Project updated.");
      router.refresh();
    } catch (caught) {
      setError(extractErrorMessage(caught));
    } finally {
      setSaving(false);
    }
  };

  const holdings = [
    project.dataset_count ? `${project.dataset_count} dataset(s)` : null,
    project.source_count ? `${project.source_count} source(s)` : null,
  ].filter(Boolean) as string[];

  return (
    <>
      <SectionPanel
        title="Project settings"
        description="Rename this workspace, describe what it is for, archive it when it is no longer in use, or delete it outright."
      >
        <div className="space-y-4">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="space-y-1.5">
              <span className="text-[12px] text-ink-3">Name</span>
              <input
                value={name}
                onChange={(event) => setName(event.target.value)}
                aria-label="Project name"
                className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-sm text-ink outline-none focus:border-accent"
              />
            </label>
            <label className="space-y-1.5">
              <span className="text-[12px] text-ink-3">Status</span>
              <select
                value={status}
                onChange={(event) => setStatus(event.target.value as ProjectDetail["status"])}
                aria-label="Project status"
                className="h-9 w-full rounded-lg border border-line bg-sunken px-3 text-sm text-ink outline-none focus:border-accent"
              >
                {STATUS_OPTIONS.map((value) => (
                  <option key={value} value={value}>
                    {value}
                  </option>
                ))}
              </select>
            </label>
          </div>

          <label className="block space-y-1.5">
            <span className="text-[12px] text-ink-3">Description</span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              rows={3}
              placeholder="What this workspace is for."
              aria-label="Project description"
              className="w-full rounded-lg border border-line bg-sunken px-3 py-2 text-sm leading-6 text-ink outline-none focus:border-accent"
            />
          </label>

          {feedback ? <p className="text-sm text-accent">{feedback}</p> : null}
          {error ? (
            <p role="alert" className="text-sm text-danger">
              {error}
            </p>
          ) : null}

          <div className="flex items-center justify-between gap-3 border-t border-line pt-4">
            <Button variant="danger" size="sm" onClick={() => setConfirming(true)}>
              Delete project
            </Button>
            <Button size="sm" onClick={() => void save()} disabled={!dirty || saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          </div>
        </div>
      </SectionPanel>

      <ConfirmDeleteDialog
        open={confirming}
        name={project.name}
        kind="project"
        requireTypedName
        consequences={[
          holdings.length
            ? `Everything inside it goes too: ${holdings.join(" and ")}, plus their runs, pipelines and history.`
            : "Everything inside it goes too, including its runs, pipelines and history.",
          "Anyone you shared this project with loses access to it.",
        ]}
        onConfirm={() => apiFetch(`/projects/${project.id}`, { method: "DELETE" })}
        onDeleted={() => router.push("/projects")}
        onClose={() => setConfirming(false)}
      />
    </>
  );
}
