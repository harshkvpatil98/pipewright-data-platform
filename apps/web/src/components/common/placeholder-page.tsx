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
        <div className="rounded-2xl border border-white/10 bg-white/5 px-4 py-4 text-sm text-slate-300">
          Module scaffolding is ready for implementation.
        </div>
      </SectionCard>
    </AppShell>
  );
}
