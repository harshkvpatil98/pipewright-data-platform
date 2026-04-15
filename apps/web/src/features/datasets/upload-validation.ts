const supportedDatasetExtensions = [".csv", ".xlsx", ".json"] as const;

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
    return "Unsupported file type. Upload csv, xlsx, or json files.";
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
