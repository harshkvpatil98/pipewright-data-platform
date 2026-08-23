type SectionPanelProps = {
  title: string;
  description?: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
  contentClassName?: string;
};

export function SectionPanel({
  title,
  description,
  actions,
  children,
  contentClassName,
}: SectionPanelProps) {
  return (
    <section className="overflow-hidden rounded-[28px] border border-line bg-[color:var(--panel)] shadow-[var(--shadow-lg)]">
      <div className="flex flex-col gap-4 border-b border-line px-5 py-5 lg:flex-row lg:items-start lg:justify-between lg:px-6 lg:py-5">
        <div className="max-w-3xl">
          <h2 className="text-lg font-semibold text-ink">{title}</h2>
          {description ? <p className="mt-2 text-sm leading-6 text-ink-3">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
      </div>
      <div className={contentClassName ?? "px-5 py-5 lg:px-6 lg:py-6"}>{children}</div>
    </section>
  );
}
