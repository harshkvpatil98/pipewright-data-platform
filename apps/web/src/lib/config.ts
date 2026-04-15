const defaultMaxUploadSizeBytes = 25 * 1024 * 1024;

function parseMaxUploadSize(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultMaxUploadSizeBytes;
}

const trim = (v: string | undefined) => (v ?? "").trim();

/** Optional build-time labels for reviewer demos (Docker/CI can inject). */
export const appConfig = {
  appName: process.env.NEXT_PUBLIC_APP_NAME ?? "Intelligent Data Platform",
  apiBaseUrl: process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1",
  internalApiBaseUrl:
    process.env.API_INTERNAL_BASE_URL ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8000/api/v1",
  maxUploadSizeBytes: parseMaxUploadSize(process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_BYTES),
  /** Display version (e.g. align with gateway APP_VERSION or git tag). */
  releaseVersion: trim(process.env.NEXT_PUBLIC_APP_VERSION),
  gitSha: trim(process.env.NEXT_PUBLIC_GIT_SHA),
  buildDate: trim(process.env.NEXT_PUBLIC_BUILD_DATE),
} as const;
