/**
 * Which files the upload modal will accept, and why.
 *
 * The list is wider than it was: Phase 11's readers cover the whole family of
 * delimited text, workbooks, the JSON shapes, XML, the columnar formats that
 * carry their own schema, SQL dumps, and the statistical formats. The
 * extension is only a gate -- the platform reads the *bytes* and overrules the
 * name, so a workbook somebody renamed `.csv` still loads correctly.
 *
 * Which is exactly why this refuses as little as possible: a file rejected
 * here never reaches the sniffer that would have understood it.
 */

const supportedDatasetExtensions = [
  // Delimited text, whatever it is called.
  ".csv", ".tsv", ".tab", ".psv", ".txt", ".dat",
  // Workbooks.
  ".xlsx", ".xlsm", ".xls",
  // The three things people mean by "a JSON file".
  ".json", ".jsonl", ".ndjson",
  // Markup and config.
  ".xml", ".yaml", ".yml",
  // Formats that carry their own schema.
  ".parquet", ".pq", ".avro", ".orc",
  // A database dump, whose CREATE TABLE is better than any inference.
  ".sql",
  // Statistical packages, whose labels are worth keeping.
  ".sas7bdat", ".dta",
  // Containers. The sniffer unwraps them and reads what is inside.
  ".gz", ".bz2", ".xz", ".zip",
] as const;

export function getSupportedDatasetExtensions(): readonly string[] {
  return supportedDatasetExtensions;
}

export function validateDatasetUploadFile(
  file: File | null,
  maxUploadSizeBytes: number,
): string | null {
  if (!file) {
    return "Choose a file to upload.";
  }

  const extension = `.${file.name.split(".").pop()?.toLowerCase() ?? ""}`;
  if (!supportedDatasetExtensions.includes(extension as (typeof supportedDatasetExtensions)[number])) {
    return `${extension} files are not supported. Upload a spreadsheet, delimited text, JSON, XML, Parquet, Avro, ORC, or a SQL dump.`;
  }

  if (file.size <= 0) {
    return "Uploaded file is empty.";
  }

  if (file.size > maxUploadSizeBytes) {
    return `File exceeds the maximum size of ${formatBytes(maxUploadSizeBytes)}.`;
  }

  return null;
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }

  const units = ["KB", "MB", "GB"];
  let value = bytes / 1024;
  let unitIndex = 0;

  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }

  const rounded = value >= 10 ? Math.round(value) : Math.round(value * 10) / 10;
  return `${rounded} ${units[unitIndex]}`;
}
