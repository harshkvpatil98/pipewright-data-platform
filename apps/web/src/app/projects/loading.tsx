import { AppShell } from "@/components/layout/app-shell";
import { Skeleton } from "@platform/shared-ui";

export default function ProjectsLoading() {
  return (
    <AppShell
      title="Loading…"
      subtitle="Just a moment."
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
