const defaultMaxUploadSizeBytes = 200 * 1024 * 1024;

function parseMaxUploadSize(value: string | undefined): number {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : defaultMaxUploadSizeBytes;
}

const trim = (v: string | undefined) => (v ?? "").trim();

/** A setting that is unset or empty reads as unset (Helm renders empty values). */
const given = (v: string | undefined) => trim(v) || undefined;
const LOCAL_API = "http://localhost:8000/api/v1";
/** The browser's address for the API: relative ("/api/v1") when a proxy sends /api to the gateway. */
const browserApi = given(process.env.NEXT_PUBLIC_API_BASE_URL) ?? LOCAL_API;

/** Optional build-time labels for reviewer demos (Docker/CI can inject). */
export const appConfig = {
  appName: process.env.NEXT_PUBLIC_APP_NAME ?? "Pipewright",
  apiBaseUrl: browserApi,
  // The server cannot fetch a relative address: it needs the gateway's own.
  internalApiBaseUrl: given(process.env.API_INTERNAL_BASE_URL) ?? (browserApi.startsWith("/") ? LOCAL_API : browserApi),
  maxUploadSizeBytes: parseMaxUploadSize(process.env.NEXT_PUBLIC_MAX_UPLOAD_SIZE_BYTES),
  /** Display version (e.g. align with gateway APP_VERSION or git tag). */
  releaseVersion: trim(process.env.NEXT_PUBLIC_APP_VERSION),
  gitSha: trim(process.env.NEXT_PUBLIC_GIT_SHA),
  buildDate: trim(process.env.NEXT_PUBLIC_BUILD_DATE),
} as const;

/** The API's full address as a person would copy it ("https://pipewright.example.com/api/v1"). */
export function absoluteApiBase(): string {
  if (!appConfig.apiBaseUrl.startsWith("/")) return appConfig.apiBaseUrl;
  return typeof window === "undefined" ? appConfig.apiBaseUrl : `${window.location.origin}${appConfig.apiBaseUrl}`;
}
