type SectionCardProps = {
  eyebrow: string;
  title: string;
  description: string;
  children: React.ReactNode;
};

export function SectionCard({ eyebrow, title, description, children }: SectionCardProps) {
  return (
    <section className="rounded-3xl border border-line bg-sunken p-6 shadow-[var(--shadow-lg)] backdrop-blur">
      <div className="mb-5">
        <div className="text-xs uppercase tracking-[0.24em] text-info">{eyebrow}</div>
        <h2 className="mt-3 text-2xl font-semibold text-ink">{title}</h2>
        <p className="mt-3 max-w-3xl text-sm leading-6 text-ink-3">{description}</p>
      </div>
      {children}
    </section>
  );
}
