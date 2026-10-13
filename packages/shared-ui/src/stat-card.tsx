type StatCardProps = {
  label: string;
  value: string;
  caption?: string;
};

export function StatCard({ label, value, caption }: StatCardProps) {
  return (
    <div className="rounded-[24px] border border-line bg-[color:var(--panel)] px-5 py-5 shadow-[var(--shadow-lg)]">
      <div className="text-[13px] font-medium text-ink-3">{label}</div>
      <div className="mt-3 text-3xl font-semibold tracking-tight text-ink">{value}</div>
      {caption ? <div className="mt-2 text-sm text-ink-3">{caption}</div> : null}
    </div>
  );
}
