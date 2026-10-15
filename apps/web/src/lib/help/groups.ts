/**
 * The help pages, in the order the help's side list shows them (A6, W2).
 * Each is a Markdown file in `docs/user/`, named by its slug; `help.test.ts`
 * fails if a file is missing from this list or the list names a file that
 * does not exist. No imports, so the static docs site's builder
 * (`scripts/build-docs-site.mjs`) can read it as it is.
 */
export const HELP_GROUPS: { label: string; slugs: string[] }[] = [
  { label: "Start here", slugs: ["index", "glossary", "whats-new"] },
  { label: "Using Pipewright", slugs: ["overview", "data", "build", "automate", "trust", "share"] },
  { label: "Running Pipewright", slugs: ["admin", "security", "api"] },
];

export const HELP_SLUGS = HELP_GROUPS.flatMap((group) => group.slugs);
