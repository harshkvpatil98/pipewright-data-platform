type PageHeaderProps = {
  eyebrow?: string;
  title: string;
  description: string;
  actions?: React.ReactNode;
  meta?: React.ReactNode;
};

export function PageHeader({
  eyebrow = "Data operations control plane",
  title,
  description,
  actions,
  meta,
}: PageHeaderProps) {
  return (
    <header className="border-b border-line px-6 py-6 lg:px-10">
      <div className="flex flex-col gap-5 xl:flex-row xl:items-start xl:justify-between">
        <div className="max-w-3xl">
          <div className="text-[11px] uppercase tracking-[0.28em] text-[color:var(--accent-muted)]">
            {eyebrow}
          </div>
          <h1 className="mt-3 text-3xl font-semibold tracking-tight text-ink lg:text-[2rem]">
            {title}
          </h1>
          <p className="mt-3 text-sm leading-6 text-ink-3">{description}</p>
          {meta ? <div className="mt-4 flex flex-wrap gap-2">{meta}</div> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
      </div>
    </header>
  );
}
