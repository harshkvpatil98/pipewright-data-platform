/**
 * Sorting the rows on screen, for looking only.
 *
 * The preview holds the first rows of the result, so this orders those rows
 * and nothing else; the Studio says so wherever it shows a view sort, and
 * offers a sort step for the whole table. Empty values go last either way,
 * numbers compare as numbers, and text compares the way people read it
 * ("item 2" before "item 10", case ignored).
 */

export type ViewSort = { column: string; direction: "asc" | "desc" };

const collator = new Intl.Collator(undefined, { numeric: true, sensitivity: "base" });

function isEmpty(value: unknown): boolean {
  return value === null || value === undefined || value === "";
}

function compare(left: unknown, right: unknown): number {
  if (typeof left === "number" && typeof right === "number") return left - right;
  if (typeof left === "boolean" && typeof right === "boolean") return Number(left) - Number(right);
  return collator.compare(String(left), String(right));
}

export function sortForView<T extends Record<string, unknown>>(rows: T[], sort: ViewSort | null): T[] {
  if (!sort) return rows;
  const sign = sort.direction === "asc" ? 1 : -1;
  return rows
    .map((row, index) => ({ row, index }))
    .sort((a, b) => {
      const left = a.row[sort.column];
      const right = b.row[sort.column];
      const leftEmpty = isEmpty(left);
      const rightEmpty = isEmpty(right);
      if (leftEmpty || rightEmpty) {
        if (leftEmpty && rightEmpty) return a.index - b.index;
        return leftEmpty ? 1 : -1;
      }
      return sign * compare(left, right) || a.index - b.index;
    })
    .map(({ row }) => row);
}
