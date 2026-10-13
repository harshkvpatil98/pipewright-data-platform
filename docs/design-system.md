# Design system

How Pipewright looks and talks, in one page, so a new screen matches the
rest without anyone having to remember. Three tests hold most of it (see
[What keeps it true](#what-keeps-it-true)); this page explains what they
enforce and why.

## Principles

From the adoption-readiness spec (A0, S5), in order of precedence:

1. **The data is the page.** Chrome earns its space or goes.
2. **One primary action per screen.** At most three actions in a page header;
   the rest go in an `ActionMenu`.
3. **No error before input.** A page opens neutral; problems appear after
   someone has done something.
4. **No word a business user would have to look up.** The vocabulary below is
   the dictionary.
5. **Every empty state says what to do next, and offers the button.**

## Tokens

Colours are semantic CSS variables in `apps/web/src/app/globals.css`, with
light and dark values. Use the role, never a hex value or a Tailwind palette
colour (`blue-500`), so both themes and future rebrands keep working.

| Role | Tokens | Use for |
|---|---|---|
| Surfaces | `canvas`, `surface`, `surface-2`, `sunken`, `panel`, `panel-strong` | The page, cards, raised and recessed areas |
| Text | `ink`, `ink-2`, `ink-3`, `muted`, `faint` | Body text, then progressively quieter text |
| Lines | `line`, `line-strong`, `line-soft` | Borders and dividers |
| Accent | `accent`, `accent-soft`, `accent-faint`, `accent-line`, `accent-ink` | The primary action, the current place, links |
| States | `success`, `warning`, `danger`, `info`, each with `-soft`, `-line`, `-ink` | Outcomes, never decoration |
| Charts | `series-1` to `series-8` | Chart series, in order |
| Workflow | `flow-*`, `edge-*` | Workflow canvas nodes and edges only |

**Type.** Nothing below 12px, anywhere: classes, the grid's canvas, SVG
labels. The working sizes are 12px (captions, badges), 13px (secondary text,
table headers), 14px (body, table cells), 16px and up for headings, 26px for
a page title. Sentence case everywhere; no uppercase text and no tracked-out
letter-spacing.

**Density.** Rows and cells take their padding from `--density-*`
(`cell-pad`), so comfortable and compact both work without per-page code.

**Theme.** Light, dark and "follow the system" are all supported, and
"system" stays the default. **Use light for screenshots, demos and docs**: it
is what most buyers' laptops show, and it prints.

## Components

Everything below comes from `packages/shared-ui`. A page does not build its
own version of any of them; `lib/components.test.ts` fails a hand-built
table, dialog, tab list or pill.

| Component | Use it for | Notes |
|---|---|---|
| `Button`, `buttonClassName` | Every action; `buttonClassName` makes a `<Link>` look like one | `primary` once per screen, then `secondary`, `ghost`, `danger`. Never wraps |
| `Modal` | A dialog, or a drawer with `side="right"` | Title, one-line description, body, footer with the actions |
| `Overlay` | Anything else that sits above the page: palettes, the tour | Handles Escape, the scrim and the dialog role. `layer` sets stacking |
| `Badge`, `StatusBadge` | A short label: a state, a kind, a count | Pick a `tone`. `StatusBadge` maps a stored status to a tone and sentence case |
| `Table` and its parts | Every list of rows | `minWidth` scrolls instead of squashing; `dense` for long lists; `edge="panel"` when the table sits in a bordered box; `TableHeaderCell` takes `sort` and `onSort` |
| `PageHeader` | The top of a page (through `AppShell`) | Title, a purpose line of 15 words at most, actions |
| `EmptyState` | Nothing here yet | Say what to do next and pass the button as `action`. `size="compact"` inside a list |
| `StatTile` | One number that drives an action | Only where the number matters; a page of zeros shows its empty state instead |
| `Tabs` | Views of one thing | Arrow keys move between tabs |
| `ToastProvider`, `useToast` | A short confirmation or failure that needs no place on the page | `toast.success`, `toast.error`, `toast.notify` with actions |
| `FormField`, `Input`, `Select`, `Textarea` | Forms | `FormField` takes `label`, `description` and `error` |
| `SectionPanel` | A titled block of a page | Title, optional description of at most 25 words, actions |
| `Icon` | The in-house icon set | No icon libraries |

Page templates live in the app: `AppShell` for list, detail and settings
pages, `AppFrame` for editors such as the Studio.

## Voice

The voice guide (A0, S6), as the language lint enforces it:

- **The product's words.** Recipe, not pipeline. Check, not rule. Import, not
  extraction. Schema change, not drift. Deliver or send, not publish.
  Organisation, not tenant. Version, not snapshot. "Loaded up to", not
  watermark. "Update matching rows", not upsert.
- **No code on screen.** No field or table names (`summary_json`,
  `pipeline_runs`), no HTTP verbs and paths, no raw identifiers as the main
  fact. Identifiers belong behind "Technical details".
- **Short.** A page's purpose line is one sentence of at most 15 words; a
  section or dialog description at most 25. Say what the thing does, not why
  it was built; rationale goes in the docs.
- **Sentence case** for titles, buttons, tabs and badges. Proper names keep
  their capitals: PostgreSQL, Power BI, Studio, Home.
- **UK spelling**: organisation, catalogue in prose ("Catalog" is the tab),
  colour, centre.
- **No em-dashes** in on-screen text; a full stop or a comma does the job.
- **Errors say what happened, then what to do next.**
- **Stored codes get labels.** A status, role, format or kind from the API is
  shown through a label function (`lib/labels.ts`, `lib/run-labels.ts`,
  `StatusBadge`), never as the raw value.

Server text that reaches the screen follows the same voice: run logs, audit
notes, comparison notes and the audit trail's summaries
(`service_governance/audit_words.py`) are written in these words at the
source.

## What keeps it true

| Test | Fails when |
|---|---|
| `apps/web/src/lib/language.test.ts` | A retired word, a code name, an HTTP path, an em-dash, a long purpose line or description, Title Case on a button or heading, or US spelling reaches the screen |
| `apps/web/src/lib/type-scale.test.ts` | Any text is set below 12px, in uppercase, or tracked out |
| `apps/web/src/lib/components.test.ts` | A page builds its own table, dialog, tab list, pill or one of the shared components |
| `apps/web/src/lib/navigation.test.ts` | A page has no browser-tab title, or a tab's "About this page" help is missing or long |
| `apps/api-gateway/tests/test_audit_words.py` | An audited route has no words of its own |

The language lint has one allowlist, each entry with its reason. Add to it
only when the word is the person's own (a vendor's field name they copy, a
database setting they must change), never because the product's wording is
inconvenient.

## Adding a page

1. Put it in `apps/web/src/lib/navigation.ts` (an area's tab, or a standalone
   page), with a `metadata` title and a `help` entry.
2. Build it on `AppShell` with a purpose line of 15 words or fewer.
3. Use the shared components; give every list an empty state with a button.
4. Show stored codes through a label function.
5. Run `npm run verify`; the tests above will say what is left.
