/**
 * Getting a result out of the workbench.
 *
 * The roadmap's promise for 17.1 is that a query result can be transformed
 * further or exported "without leaving". Exporting is this file; transforming
 * further is the notebook, which takes the same SQL as its first cell.
 */

/** RFC 4180: quote when the value contains a delimiter, a quote or a newline. */
export function csvCell(value: unknown): string {
  if (value === null || value === undefined) return "";
  const text = typeof value === "object" ? JSON.stringify(value) : String(value);
  if (/[",\n\r]/.test(text)) return `"${text.replace(/"/g, '""')}"`;
  return text;
}

export function toCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const lines = [columns.map(csvCell).join(",")];
  for (const row of rows) {
    lines.push(columns.map((column) => csvCell(row[column])).join(","));
  }
  // A trailing newline: a file without one appends to the next thing that reads it.
  return `${lines.join("\n")}\n`;
}

/** A filename that survives a filesystem and still says what it holds. */
export function exportName(summary: string, extension: string): string {
  const stem =
    summary
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-+|-+$/g, "")
      .slice(0, 60) || "result";
  return `${stem}.${extension}`;
}
