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
    <section className="rounded-[28px] border border-white/8 bg-[color:var(--panel)] shadow-[0_20px_60px_rgba(2,6,23,0.24)]">
      <div className="flex flex-col gap-4 border-b border-white/8 px-5 py-5 lg:flex-row lg:items-start lg:justify-between lg:px-6">
        <div>
          <h2 className="text-lg font-semibold text-white">{title}</h2>
          {description ? <p className="mt-2 text-sm leading-6 text-slate-400">{description}</p> : null}
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-3">{actions}</div> : null}
      </div>
      <div className={contentClassName ?? "px-5 py-5 lg:px-6"}>{children}</div>
    </section>
  );
}
