import Link from "next/link";

import { Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "@platform/shared-ui";

import type { Block, Inline } from "@/lib/help/markdown";

/**
 * One help page, drawn from the blocks `parseMarkdown` makes, in the
 * product's own type scale and colours rather than a Markdown stylesheet.
 */
export function HelpArticle({ blocks }: { blocks: Block[] }) {
  return (
    <article className="min-w-0">
      {blocks.map((block, index) => (
        <HelpBlock key={index} block={block} first={index === 0} />
      ))}
    </article>
  );
}

function HelpBlock({ block, first }: { block: Block; first: boolean }) {
  switch (block.kind) {
    case "heading":
      if (block.level === 1) {
        return (
          <h1 id={block.id} className="scroll-mt-20 text-[26px] font-semibold tracking-tight text-ink">
            {block.text}
          </h1>
        );
      }
      if (block.level === 2) {
        return (
          <h2
            id={block.id}
            className={`scroll-mt-20 text-[19px] font-semibold text-ink ${first ? "" : "mt-9 border-t border-line pt-7"}`}
          >
            {block.text}
          </h2>
        );
      }
      return (
        <h3 id={block.id} className="mt-6 scroll-mt-20 text-[15.5px] font-semibold text-ink">
          {block.text}
        </h3>
      );
    case "paragraph":
      return (
        <p className="mt-3 text-[14.5px] leading-7 text-ink-2">
          <InlineText parts={block.content} />
        </p>
      );
    case "list": {
      const Tag = block.ordered ? "ol" : "ul";
      return (
        <Tag
          className={`mt-3 space-y-2 pl-6 text-[14.5px] leading-7 text-ink-2 ${block.ordered ? "list-decimal" : "list-disc"} marker:text-[color:var(--accent-muted)]`}
        >
          {block.items.map((item, index) => (
            <li key={index} className="pl-1">
              <InlineText parts={item} />
            </li>
          ))}
        </Tag>
      );
    }
    case "quote":
      return (
        <div className="mt-4 rounded-xl border border-[color:var(--accent-line)] bg-[color:var(--accent-faint)] px-4 py-3 text-[14px] leading-6 text-ink-2">
          <InlineText parts={block.content} />
        </div>
      );
    case "code":
      return (
        <pre className="mt-3 overflow-x-auto rounded-xl border border-line bg-sunken px-4 py-3 font-mono text-[13px] leading-6 text-ink">
          <code>{block.text}</code>
        </pre>
      );
    case "table":
      return (
        <div className="mt-4 rounded-xl border border-line px-4 py-1">
          <Table>
            <TableHead>
              <TableRow>
                {block.header.map((cell, index) => (
                  <TableHeaderCell key={index}>
                    <InlineText parts={cell} />
                  </TableHeaderCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {block.rows.map((row, rowIndex) => (
                <TableRow key={rowIndex}>
                  {row.map((cell, index) => (
                    <TableCell key={index} className="text-ink-2">
                      <InlineText parts={cell} />
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      );
  }
}

function InlineText({ parts }: { parts: Inline[] }) {
  return (
    <>
      {parts.map((part, index) => {
        switch (part.kind) {
          case "strong":
            return (
              <strong key={index} className="font-semibold text-ink">
                {part.text}
              </strong>
            );
          case "code":
            return (
              <code key={index} className="rounded-md bg-surface-2 px-1.5 py-0.5 font-mono text-[0.88em] text-ink">
                {part.text}
              </code>
            );
          case "link":
            return /^https?:/.test(part.href) ? (
              <a key={index} href={part.href} target="_blank" rel="noreferrer" className="text-accent underline">
                {part.text}
              </a>
            ) : (
              <Link key={index} href={part.href} className="text-accent underline">
                {part.text}
              </Link>
            );
          default:
            return <span key={index}>{part.text}</span>;
        }
      })}
    </>
  );
}
