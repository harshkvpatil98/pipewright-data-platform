import { apiDownload } from "@/lib/api/client";

/**
 * Download a file the API generates and hand it to the browser to save.
 * Goes through `apiDownload`, so an ended session goes to sign-in and an
 * error reads the API's own message, like every other request.
 */
export async function downloadFromApi(path: string, fallbackFilename: string): Promise<void> {
  const { blob, filename } = await apiDownload(path);
  saveBlob(blob, filename ?? fallbackFilename);
}

/** Offer a blob to the browser as a download. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.click();
  URL.revokeObjectURL(url);
}
