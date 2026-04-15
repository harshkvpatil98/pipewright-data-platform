type SectionCardProps = {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
};

export function SectionCard({ eyebrow, title, description, children }: SectionCardProps) {
  return (
    <section className="rounded-3xl border border-white/10 bg-slate-950/40 p-6 shadow-2xl shadow-slate-950/10 backdrop-blur">
      <div className="mb-5">
        <div className="text-xs uppercase tracking-[0.24em] text-sky-300">{eyebrow}</div>
        <h2 className="mt-3 text-2xl font-semibold text-white">{title}</h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-slate-400">{description}</p>
      </div>
      {children}
    </section>
  );
}
