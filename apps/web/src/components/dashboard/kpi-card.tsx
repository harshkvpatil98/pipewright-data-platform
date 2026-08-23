type KpiCardProps = {
  label: string;
  value: string;
  children?: React.ReactNode;
};

export function KpiCard({ label, value, children }: KpiCardProps) {
  return (
    <div className="rounded-3xl border border-line bg-surface p-5 shadow-[var(--shadow-lg)] backdrop-blur">
      <div className="mb-4 flex items-center justify-between gap-3 text-sm text-ink-3">{children}</div>
      <div className="text-sm uppercase tracking-[0.18em] text-muted">{label}</div>
      <div className="mt-3 text-2xl font-semibold text-ink">{value}</div>
    </div>
  );
}
