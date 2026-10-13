"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import type { AuthUser, SupportContact } from "@platform/shared-types";
import { Icon } from "@platform/shared-ui";

import { AppFrame } from "@/components/shell/app-frame";
import type { HelpContents } from "@/lib/help/content";
import { helpPath } from "@/lib/help/pages";
import { cx } from "@/lib/utils";

type HelpLayoutProps = {
  currentUser: AuthUser | null;
  slug: string;
  title: string;
  contents: HelpContents;
  /** The page's sections, for "On this page". */
  sections: { id: string; text: string }[];
  support: SupportContact | null;
  children: React.ReactNode;
};

/**
 * The help: a list of pages on the left, the page in the middle, and its
 * sections on the right on a wide screen. Works signed in or not, so someone
 * who cannot sign in can still read how to get help.
 */
export function HelpLayout({ currentUser, slug, title, contents, sections, support, children }: HelpLayoutProps) {
  const [filter, setFilter] = useState("");
  const shown = useMemo(() => {
    const words = filter.trim().toLowerCase();
    if (!words) return contents;
    return contents
      .map((group) => ({ ...group, pages: group.pages.filter((page) => page.title.toLowerCase().includes(words)) }))
      .filter((group) => group.pages.length > 0);
  }, [contents, filter]);

  return (
    <AppFrame currentUser={currentUser} title={slug === "index" ? undefined : title}>
      <div className="mx-auto flex w-full max-w-6xl gap-10 px-6 py-8">
        <nav aria-label="Help pages" className="hidden w-56 shrink-0 md:block">
          <div className="sticky top-6">
            <label className="relative block">
              <span className="sr-only">Find a help page</span>
              <Icon name="search" size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-3" />
              <input
                value={filter}
                onChange={(event) => setFilter(event.target.value)}
                placeholder="Find a page"
                className="h-9 w-full rounded-lg border border-line bg-surface pl-8 pr-2 text-[13.5px] text-ink outline-none placeholder:text-ink-3 focus:border-[color:var(--accent-line)]"
              />
            </label>
            {shown.map((group) => (
              <div key={group.label} className="mt-5">
                <div className="px-2 text-[13px] font-medium text-ink-3">{group.label}</div>
                <ul className="mt-1.5 space-y-0.5">
                  {group.pages.map((page) => (
                    <li key={page.slug}>
                      <Link
                        href={helpPath(page.slug)}
                        aria-current={page.slug === slug ? "page" : undefined}
                        className={cx(
                          "block rounded-lg px-2 py-1.5 text-[14px] transition",
                          page.slug === slug
                            ? "bg-[color:var(--accent-soft)] font-medium text-ink"
                            : "text-ink-2 hover:bg-surface-2 hover:text-ink",
                        )}
                      >
                        {page.title}
                      </Link>
                    </li>
                  ))}
                </ul>
              </div>
            ))}
            {shown.length === 0 ? <p className="mt-4 px-2 text-[13px] text-ink-3">No page is called that.</p> : null}
          </div>
        </nav>

        <div className="min-w-0 max-w-3xl flex-1">
          <details className="mb-6 rounded-xl border border-line md:hidden">
            <summary className="cursor-pointer px-4 py-2.5 text-[14px] font-medium text-ink">All help pages</summary>
            <ul className="border-t border-line px-2 py-2">
              {contents.flatMap((group) => group.pages).map((page) => (
                <li key={page.slug}>
                  <Link href={helpPath(page.slug)} className="block rounded-lg px-2 py-1.5 text-[14px] text-ink-2 hover:bg-surface-2">
                    {page.title}
                  </Link>
                </li>
              ))}
            </ul>
          </details>

          {children}

          <footer className="mt-12 flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-line pt-5 text-[13.5px] text-ink-3">
            <span>Still stuck?</span>
            {support?.href ? (
              <a href={support.href} target="_blank" rel="noreferrer" className="text-accent underline">
                Contact support ({support.contact})
              </a>
            ) : (
              <Link href="/help#getting-help" className="text-accent underline">
                How to get help
              </Link>
            )}
            {support?.version ? <span className="ml-auto">Pipewright {support.version}</span> : null}
          </footer>
        </div>

        {sections.length > 2 ? (
          <aside aria-label="On this page" className="hidden w-48 shrink-0 xl:block">
            <div className="sticky top-6">
              <div className="text-[13px] font-medium text-ink-3">On this page</div>
              <ul className="mt-2 space-y-1.5 border-l border-line">
                {sections.map((section) => (
                  <li key={section.id}>
                    <a
                      href={`#${section.id}`}
                      className="-ml-px block border-l border-transparent pl-3 text-[13px] leading-5 text-ink-3 hover:border-[color:var(--accent)] hover:text-ink"
                    >
                      {section.text}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          </aside>
        ) : null}
      </div>
    </AppFrame>
  );
}
