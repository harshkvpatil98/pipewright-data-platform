import { SectionCard } from "@/components/dashboard/section-card";
import { AppShell } from "@/components/layout/app-shell";

type PlaceholderPageProps = {
  title: string;
  description: string;
};

export function PlaceholderPage({ title, description }: PlaceholderPageProps) {
  return (
    <AppShell title={title} subtitle={description}>
      <SectionCard
        eyebrow="Planned module"
        title={`${title} foundation`}
        description="This route is intentionally present now so feature delivery can expand against a stable application structure without later navigation or layout churn."
      >
        <div className="rounded-2xl border border-line bg-surface px-4 py-4 text-sm text-ink-2">
          Module scaffolding is ready for implementation.
        </div>
      </SectionCard>
    </AppShell>
  );
}
