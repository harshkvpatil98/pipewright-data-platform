import { AppShell } from "@/components/layout/app-shell";
import { Skeleton } from "@platform/shared-ui";

export default function ProjectDetailLoading() {
  return (
    <AppShell
      eyebrow="Project workspace"
      title="Loading project"
      subtitle="Preparing sources, datasets, and summary metrics for this workspace."
    >
      <div className="grid gap-4 md:grid-cols-4">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
      <Skeleton className="h-[540px]" />
    </AppShell>
  );
}
