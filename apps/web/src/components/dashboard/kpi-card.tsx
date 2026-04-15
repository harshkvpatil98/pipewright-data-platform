type KpiCardProps = {
  label: string;
  value: string;
  children?: React.ReactNode;
};

export function KpiCard({ label, value, children }: KpiCardProps) {
  return (
    <div className="rounded-3xl border border-white/10 bg-white/5 p-5 shadow-2xl shadow-slate-950/10 backdrop-blur">
      <div className="mb-4 flex items-center justify-between gap-3 text-sm text-slate-400">{children}</div>
      <div className="text-sm uppercase tracking-[0.18em] text-slate-500">{label}</div>
      <div className="mt-3 text-2xl font-semibold text-white">{value}</div>
    </div>
  );
}
