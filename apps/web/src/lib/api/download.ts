import { appConfig } from "@/lib/config";
import { getAccessToken } from "@/lib/auth/session";

/**
 * Authenticated binary/text download from the public API (browser client).
 * Parses filename from Content-Disposition when present.
 */
export async function downloadFromApi(path: string, fallbackFilename: string): Promise<void> {
  const token = getAccessToken();
  const response = await fetch(`${appConfig.apiBaseUrl}${path}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    cache: "no-store",
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `Download failed (${response.status})`);
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition");
  let filename = fallbackFilename;
  const quoted = disposition?.match(/filename="([^"]+)"/);
  if (quoted?.[1]) {
    filename = quoted[1];
  }

  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.rel = "noopener";
  anchor.click();
  URL.revokeObjectURL(url);
}
