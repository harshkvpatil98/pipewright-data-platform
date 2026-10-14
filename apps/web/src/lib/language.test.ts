import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

import ts from "typescript";
import { describe, expect, it } from "vitest";

import { RETIRED, US_SPELLING } from "@/lib/voice";

/*
 * The language lint (adoption-readiness A5). It reads every string a person
 * can see, through the TypeScript parser rather than a regex over the file,
 * and holds them to the voice guide (A0, S6): the product's own words, short
 * purpose lines, sentence case, UK spelling, no code names, no em-dashes.
 */

const ROOTS = [
  fileURLToPath(new URL("..", import.meta.url)),
  fileURLToPath(new URL("../../../../packages/shared-ui/src", import.meta.url)),
];

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(entry) && !entry.includes(".test.") && !entry.endsWith(".d.ts") ? [path] : [];
  });
}

/** Attributes whose value is read by a person. */
const SHOWN_ATTRIBUTES = new Set([
  "title",
  "subtitle",
  "description",
  "label",
  "placeholder",
  "aria-label",
  "alt",
  "help",
  "hint",
  "caption",
  "message",
  "heading",
  "tooltip",
  "confirmLabel",
  "actionLabel",
]);

type Shown = { file: string; line: number; text: string; context: string; leading: boolean };

function shownStrings(): Shown[] {
  const found: Shown[] = [];
  for (const root of ROOTS) {
    for (const file of sourceFiles(root)) {
      const source = ts.createSourceFile(file, readFileSync(file, "utf8"), ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      const name = file.split("/src/").pop() ?? file;
      const add = (node: ts.Node, text: string, context: string, leading = true) => {
        const clean = text.replace(/\s+/g, " ").trim();
        // Web addresses and CSS media queries are code, not words on screen.
        if (/^\/|^\(prefers-/.test(clean)) return;
        if (clean) found.push({ file: name, line: source.getLineAndCharacterOfPosition(node.getStart()).line + 1, text: clean, context, leading });
      };
      const contextOf = (node: ts.Node): string => {
        let current: ts.Node | undefined = node.parent;
        while (current) {
          if (ts.isJsxAttribute(current)) {
            const element = current.parent.parent;
            const tag = ts.isJsxOpeningElement(element) || ts.isJsxSelfClosingElement(element) ? element.tagName.getText() : "";
            return `${tag}.${current.name.getText()}`;
          }
          if (ts.isJsxElement(current)) return current.openingElement.tagName.getText();
          if (ts.isCallExpression(current)) return `call:${current.expression.getText().split("(")[0]}`;
          if (ts.isPropertyAssignment(current)) return `prop:${current.name.getText()}`;
          current = current.parent;
        }
        return "";
      };
      const visit = (node: ts.Node) => {
        if (ts.isJsxText(node)) {
          // Text that opens its element, rather than following a value ("{n} times").
          const siblings = ts.isJsxElement(node.parent) ? node.parent.children : undefined;
          const first = siblings?.find((child) => !(ts.isJsxText(child) && !child.text.trim()));
          add(node, node.text, contextOf(node), !siblings || first === node);
        } else if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) {
          const parent = node.parent;
          const context = contextOf(node);
          if (ts.isImportDeclaration(parent) || ts.isExportDeclaration(parent) || context.startsWith("call:require")) {
            // module paths
          } else if (ts.isJsxAttribute(parent)) {
            if (SHOWN_ATTRIBUTES.has(parent.name.getText())) add(node, node.text, context);
          } else if (/^[A-Z“"‘(][^]*\s/.test(node.text) && !/^[A-Z0-9_ ]+$/.test(node.text)) {
            add(node, node.text, context);
          }
        } else if (ts.isTemplateExpression(node)) {
          const holder = node.parent && ts.isJsxExpression(node.parent) ? node.parent.parent : undefined;
          if (holder && ts.isJsxAttribute(holder) && !SHOWN_ATTRIBUTES.has(holder.name.getText())) {
            ts.forEachChild(node, visit);
            return;
          }
          const text = node.head.text + node.templateSpans.map((span) => ` {} ${span.literal.text}`).join("");
          if (/^[A-Z“"‘(][^]*\s/.test(node.head.text) || ts.isJsxExpression(node.parent)) add(node, text, contextOf(node));
        }
        ts.forEachChild(node, visit);
      };
      visit(source);
    }
  }
  return found;
}

/**
 * The catalogue's words (A8, Y7): the shell and the navigation read them
 * through `t()`, so the parse above no longer sees them. Each is given the
 * place it is shown in, so the same rules hold.
 */
function catalogueStrings(): Shown[] {
  const found: Shown[] = [];
  const walk = (node: unknown, key: string) => {
    if (typeof node === "string") {
      if (key === "locale" || key.startsWith("$") || key.endsWith(".keywords")) return;
      const context = /^nav\..*\.label$/.test(key)
        ? "NavTab.label"
        : key.endsWith(".description")
          ? "Catalogue.description"
          : key.startsWith("shell.keys.") || /^shell\.palette\.(navigate|open|esc|nothingMatches\w+)$/.test(key)
            ? "Catalogue.fragment"
            : "Catalogue.label";
      found.push({ file: "messages/en.json", line: 0, text: node.replace(/\s+/g, " ").trim(), context: `${context}:${key}`, leading: true });
    } else if (Array.isArray(node)) {
      node.forEach((line) => found.push({ file: "messages/en.json", line: 0, text: String(line), context: `Catalogue.help:${key}`, leading: true }));
    } else if (node && typeof node === "object") {
      for (const [part, value] of Object.entries(node)) walk(value, key ? `${key}.${part}` : part);
    }
  };
  walk(JSON.parse(readFileSync(fileURLToPath(new URL("../../messages/en.json", import.meta.url)), "utf8")), "");
  return found;
}

const SHOWN = [...shownStrings(), ...catalogueStrings()];

/**
 * Exceptions, each with its reason. A word belongs here only when it is the
 * person's own (SQL they type, a vendor's field name they copy) rather than
 * the product's.
 */
const ALLOWED: { file: string; text: RegExp; reason: string }[] = [
  { file: "features/bi-connections/components/bi-connections-page.tsx", text: /^Tenant ID$/, reason: "Microsoft's name for the field the person copies from the Azure portal" },
  { file: "features/extraction/components/live-sources-panel.tsx", text: /wal_level/, reason: "the PostgreSQL setting a database administrator must change, by its name" },
  { file: "features/audit/components/run-audit-page.tsx", text: /^(Run|Recipe) ID$/, reason: "inside Technical details, hidden until someone asks for identifiers" },
];

function allowed(item: Shown): boolean {
  return ALLOWED.some((entry) => item.file === entry.file && entry.text.test(item.text));
}

function offenders(test: (item: Shown) => boolean): string[] {
  return SHOWN.filter((item) => test(item) && !allowed(item)).map((item) => `${item.file}:${item.line}: ${item.text.slice(0, 120)}`);
}

describe("on-screen language", () => {
  it("reads at least the strings it means to", () => {
    expect(SHOWN.length).toBeGreaterThan(2500);
    expect(SHOWN.filter((item) => item.file === "messages/en.json").length).toBeGreaterThan(250);
    expect(SHOWN.filter((item) => item.context === "AppShell.subtitle").length).toBeGreaterThan(40);
    expect(SHOWN.filter((item) => item.file.endsWith("tour/tours.ts") && item.context === "prop:body").length).toBeGreaterThan(10);
  });

  it("uses the product's words, not retired or engine words", () => {
    const hits: string[] = [];
    for (const [pattern, instead] of RETIRED) {
      for (const hit of offenders((item) => pattern.test(item.text))) hits.push(`${hit}  (say: ${instead})`);
    }
    expect(hits).toEqual([]);
  });

  it("never names a stored field, a log column or an id", () => {
    expect(
      offenders((item) =>
        /\b\w+_json\b|\b(step_type|run_type|organisation_id|pipeline_runs|next_run_at|row_count|column_count)\b|\b(Run|Pipeline|Recipe|Dataset|Parent dataset|Related run|user|Datasource|Power BI dataset) id\b/i.test(
          item.text,
        ),
      ),
    ).toEqual([]);
  });

  it("does not show HTTP verbs and paths", () => {
    expect(offenders((item) => /\b(GET|POST|PUT|PATCH|DELETE) \/\w/.test(item.text))).toEqual([]);
  });

  it("writes sentences without em-dashes", () => {
    expect(offenders((item) => /\S\s*—\s*\S/.test(item.text))).toEqual([]);
  });

  it("keeps a page's purpose line to 15 words and a description to 25", () => {
    const words = (text: string) => text.split(/\s+/).filter(Boolean).length;
    expect(offenders((item) => item.context === "AppShell.subtitle" && words(item.text) > 15)).toEqual([]);
    expect(offenders((item) => /\.description(:|$)/.test(item.context) && words(item.text) > 25)).toEqual([]);
    expect(offenders((item) => item.context.startsWith("Catalogue.help:") && words(item.text) > 25)).toEqual([]);
    expect(offenders((item) => item.file.endsWith("tour/tours.ts") && item.context === "prop:body" && words(item.text) > 25)).toEqual([]);
  });

  it("uses sentence case on buttons, headings and titles", () => {
    const PROPER = new Set(
      "I Home PostgreSQL MySQL SQLite MariaDB S3 SQL CSV Excel JSON YAML Parquet Power BI Tableau Slack GitHub HubSpot Stripe Shopify Salesforce Google Sheets Pipewright Studio API APIs OIDC SSO URL CSV PDF HTML Avro ORC Microsoft Azure Entra Okta TOTP Monday Tuesday Wednesday Thursday Friday Saturday Sunday January February March April May June July August September October November December UTC AS OF".split(
        " ",
      ),
    );
    const titleCase = (text: string) => {
      const words = text.replace(/[^\p{L}\p{N}\s'’-]/gu, " ").split(/\s+/).filter(Boolean);
      if (words.length < 2 || words.length > 7) return false;
      return words.slice(1).some((word) => /^\p{Lu}\p{Ll}/u.test(word) && !PROPER.has(word));
    };
    const SHORT_PLACES = /^(Button|h1|h2|h3|h4|button|Link|SectionPanel\.title|Modal\.title|AppShell\.title|EmptyState\.title|Badge|TableHeaderCell|NavTab\.label:.*|Catalogue\.label:.*)$/;
    // Each sentence on its own: "Project: Sales. Switch project" is two.
    const anyTitleCase = (text: string) => text.split(/[.!?]\s+/).some(titleCase);
    expect(offenders((item) => SHORT_PLACES.test(item.context) && anyTitleCase(item.text))).toEqual([]);
  });

  it("starts every label, button and heading with a capital", () => {
    const LABEL_PLACES = /^(Button|Badge|TableHeaderCell|h1|h2|h3|SectionPanel\.title|Modal\.title|AppShell\.title|EmptyState\.title|NavTab\.label:.*|Catalogue\.label:.*)$/;
    expect(offenders((item) => item.leading && LABEL_PLACES.test(item.context) && /^[a-z]/.test(item.text))).toEqual([]);
  });

  it("counts in words, never with (s)", () => {
    expect(offenders((item) => /\w\(s\)/.test(item.text))).toEqual([]);
  });

  it("spells the UK way", () => {
    expect(
      offenders((item) =>
        US_SPELLING.test(item.text),
      ),
    ).toEqual([]);
  });
});
