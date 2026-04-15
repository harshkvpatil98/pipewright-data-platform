import { AppShell } from "@/components/layout/app-shell";
import { Skeleton } from "@platform/shared-ui";

export default function ProjectsLoading() {
  return (
    <AppShell
      eyebrow="Workspace management"
      title="Projects"
      subtitle="Loading project workspaces and portfolio metrics."
    >
      <div className="grid gap-4 md:grid-cols-3">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
      <Skeleton className="h-[420px]" />
    </AppShell>
  );
}
