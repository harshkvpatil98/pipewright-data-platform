type PageHeaderProps = {
  title: string;
  /** One sentence saying what the page is for: 15 words at most (A0 voice guide). */
  subtitle: string;
  /** At most three; the rest go in an overflow menu. */
  actions?: React.ReactNode;
  /** Badges and facts about the object the page shows. */
  meta?: React.ReactNode;
};

/** The top of every list, detail and settings page: its name, its purpose, its actions. */
export function PageHeader({ title, subtitle, actions, meta }: PageHeaderProps) {
  return (
    <header className="mb-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0 max-w-3xl">
          <h1 className="text-[26px] font-semibold tracking-tight text-ink">{title}</h1>
          <p className="mt-1.5 text-[14px] leading-6 text-ink-3">{subtitle}</p>
        </div>
        {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
      {meta ? <div className="mt-4 flex flex-wrap items-center gap-2">{meta}</div> : null}
    </header>
  );
}
