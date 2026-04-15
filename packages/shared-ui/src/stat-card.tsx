type StatCardProps = {
  label: string;
  value: string;
  caption?: string;
};

export function StatCard({ label, value, caption }: StatCardProps) {
  return (
    <div className="rounded-[24px] border border-white/8 bg-[color:var(--panel)] px-5 py-5 shadow-[0_20px_60px_rgba(2,6,23,0.22)]">
      <div className="text-xs uppercase tracking-[0.2em] text-slate-500">{label}</div>
      <div className="mt-3 text-3xl font-semibold tracking-tight text-white">{value}</div>
      {caption ? <div className="mt-2 text-sm text-slate-400">{caption}</div> : null}
    </div>
  );
}
