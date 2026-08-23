/**
 * The tool catalogue, as the Studio sees it.
 *
 * The server owns the library -- it is the thing that runs the tools, and a
 * second copy here would drift within a release. What lives here is the small
 * amount of logic the UI needs on top: which tools suit a column, how to rank
 * them for a query, and how to turn a filled-in form into a step config.
 *
 * Ranking is duplicated from the server on purpose, and only for the *loaded*
 * catalogue: filtering a list already in memory has to happen per keystroke,
 * and a round trip per keystroke is the difference between a palette that feels
 * instant and one nobody uses. The server's version stays authoritative for
 * anything that has to be complete.
 */

export type ToolParam = {
  key: string;
  label: string;
  kind: "text" | "number" | "integer" | "boolean" | "column" | "columns" | "select" | "list";
  required: boolean;
  default: unknown;
  options: string[];
  help: string;
  placeholder: string;
  minimum: number | null;
  maximum: number | null;
};

export type ToolExample = {
  rows: Record<string, unknown>[];
  params: Record<string, unknown>;
  column: string | null;
  output: string | null;
  expect: unknown[];
  note: string;
};

export type Tool = {
  name: string;
  title: string;
  category: string;
  summary: string;
  synonyms: string[];
  accepts: "any" | "text" | "numeric" | "temporal" | "boolean" | "textual";
  column_scoped: boolean;
  params: ToolParam[];
  example: ToolExample;
};

export type ToolCatalogue = { categories: string[]; items: Tool[] };

/** Filler words that carry no signal, mirroring the server's list. */
const STOPWORDS = new Set([
  "a", "an", "and", "as", "at", "by", "for", "from", "in", "into", "of", "on",
  "or", "the", "to", "with",
]);

export function queryWords(query: string): string[] {
  return query
    .trim()
    .toLowerCase()
    .split(/[^a-z0-9]+/)
    .filter((word) => word.length > 0 && !STOPWORDS.has(word));
}

function scoreOne(word: string, tool: Tool): number {
  const haystacks: [string, number][] = [
    [tool.title.toLowerCase(), 100],
    [tool.name.toLowerCase().replace(/[._]/g, " "), 90],
    ...tool.synonyms.map((synonym) => [synonym.toLowerCase(), 80] as [string, number]),
    [tool.category.toLowerCase(), 30],
    [tool.summary.toLowerCase(), 20],
  ];

  let best = 0;
  for (const [text, weight] of haystacks) {
    if (text === word) best = Math.max(best, weight + 50);
    else if (new RegExp(`\\b${word.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`).test(text)) {
      best = Math.max(best, weight + 25);
    } else if (text.includes(word)) best = Math.max(best, weight);
  }
  return best;
}

/**
 * Rank tools against a query. Every word must match something.
 *
 * Requiring every word is what keeps a second word useful: with an any-word
 * rule, adding detail to a query makes the results worse.
 */
export function rankTools(tools: Tool[], query: string): Tool[] {
  const words = queryWords(query);
  if (words.length === 0) return tools;

  const scored: { tool: Tool; score: number }[] = [];
  for (const tool of tools) {
    let total = 0;
    for (const word of words) {
      const best = scoreOne(word, tool);
      if (best === 0) {
        total = 0;
        break;
      }
      total += best;
    }
    if (total > 0) scored.push({ tool, score: total });
  }

  scored.sort((left, right) =>
    right.score - left.score || left.tool.name.localeCompare(right.tool.name),
  );
  return scored.map((entry) => entry.tool);
}

/** The type families a tool declares it works on. */
export function acceptsType(tool: Tool, columnType: string | undefined): boolean {
  if (tool.accepts === "any" || !columnType) return true;
  const type = columnType.toLowerCase();
  const numeric = /(int|float|double|decimal|numeric|real|number)/.test(type);
  const temporal = /(date|time|timestamp)/.test(type);
  const boolean = /bool/.test(type);
  const text = /(str|text|char|object|uuid)/.test(type);
  const unknown = !numeric && !temporal && !boolean && !text;

  // An unprofiled column is offered everything: hiding tools because the
  // profiler could not decide makes it untouchable, which is exactly when
  // people need them.
  if (unknown) return true;
  if (tool.accepts === "numeric") return numeric;
  if (tool.accepts === "temporal") return temporal;
  if (tool.accepts === "boolean") return boolean;
  if (tool.accepts === "text") return text;
  return text || !temporal;
}

/** The tools worth putting on a column's context menu, best first. */
export function toolsForColumn(tools: Tool[], columnType: string | undefined): Tool[] {
  return tools.filter((tool) => tool.column_scoped && acceptsType(tool, columnType));
}

export function groupByCategory(tools: Tool[]): { category: string; tools: Tool[] }[] {
  const groups = new Map<string, Tool[]>();
  for (const tool of tools) {
    const bucket = groups.get(tool.category);
    if (bucket) bucket.push(tool);
    else groups.set(tool.category, [tool]);
  }
  return [...groups.entries()].map(([category, entries]) => ({ category, tools: entries }));
}

/** The starting values for a tool's form, from its declared defaults. */
export function defaultValues(tool: Tool): Record<string, unknown> {
  const values: Record<string, unknown> = {};
  for (const param of tool.params) {
    values[param.key] = param.default ?? (param.kind === "boolean" ? false : "");
  }
  return values;
}

/**
 * Turn a filled-in form into the step config the API expects.
 *
 * Empty optional values are dropped rather than sent as "": the server tells
 * required from absent, and sending an empty string for an omitted parameter
 * turns "use the default" into "use nothing".
 */
export function toConfig(
  tool: Tool,
  column: string | null,
  into: string | null,
  values: Record<string, unknown>,
): Record<string, unknown> {
  const config: Record<string, unknown> = { tool: tool.name };
  if (tool.column_scoped && column) config.column = column;
  if (into && into.trim()) config.into = into.trim();
  for (const param of tool.params) {
    const value = values[param.key];
    if (value === "" || value === undefined || value === null) {
      if (param.required && param.default === null) config[param.key] = value ?? "";
      continue;
    }
    config[param.key] = value;
  }
  return config;
}

/** A one-line "this in, that out" for the tool card. */
export function exampleLine(tool: Tool): string | null {
  const { example } = tool;
  if (!example.expect.length || !example.rows.length) return null;
  const column = example.column ?? Object.keys(example.rows[0])[0];
  const given = example.rows[0]?.[column];
  const produced = example.expect[0];
  const render = (value: unknown) =>
    value === null || value === undefined
      ? "empty"
      : value === ""
        ? "blank"
        : JSON.stringify(value).replace(/^"|"$/g, "");
  return `${render(given)} → ${render(produced)}`;
}
