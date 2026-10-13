export class ApiError extends Error {
  status: number;
  detail: unknown;

  constructor(status: number, detail: unknown) {
    super(typeof detail === "string" ? detail : `API request failed with status ${status}`);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

/** What the browser says when a request never reached the server, by engine. */
const UNREACHABLE = /failed to fetch|networkerror|load failed|network request failed/i;

export const UNREACHABLE_MESSAGE =
  "Pipewright's server could not be reached. Check your connection and try again; if it keeps happening, System status shows what is running.";

/** A field-by-field refusal (FastAPI's 422 list), as one sentence. */
function describeInvalidFields(detail: unknown): string | null {
  if (!Array.isArray(detail) || detail.length === 0) return null;
  const parts = detail.slice(0, 3).map((item) => {
    const entry = item as { loc?: unknown[]; msg?: string };
    const field = Array.isArray(entry.loc) ? entry.loc.filter((part) => part !== "body").join(" › ") : "";
    return field ? `${field}: ${entry.msg ?? "not valid"}` : (entry.msg ?? "not valid");
  });
  return `Some details need changing. ${parts.join("; ")}.`;
}

export function extractErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") {
      return error.detail;
    }
    const inner =
      typeof error.detail === "object" && error.detail !== null && "detail" in error.detail
        ? (error.detail as { detail?: unknown }).detail
        : undefined;
    if (typeof inner === "string") {
      return inner;
    }
    const fields = describeInvalidFields(inner);
    if (fields) {
      return fields;
    }
    if (error.status >= 500) {
      return "Something went wrong on Pipewright's server. Try again; if it keeps happening, tell whoever runs Pipewright for you.";
    }
    return error.message;
  }

  if (error instanceof Error) {
    return UNREACHABLE.test(error.message) ? UNREACHABLE_MESSAGE : error.message;
  }

  return "Something went wrong. Please try again.";
}

export async function parseApiResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") ?? "";

  // Read the body as text first, and only parse it if there is any.
  //
  // A 204 carries no body and the API still labels it `application/json`, so
  // `response.json()` threw "Unexpected end of JSON input" -- on a request
  // that had succeeded. Every DELETE in the API answers 204, which is why
  // removing a project member appeared to fail while actually removing them:
  // the row was gone, the parse threw, the page showed an error and skipped
  // its reload, so the member stayed on screen until a refresh.
  const raw = await response.text();
  const payload = raw
    ? contentType.includes("application/json")
      ? (JSON.parse(raw) as unknown)
      : raw
    : undefined;

  if (!response.ok) {
    // An address whose id is malformed ("/workflows/new", a link cut short)
    // names nothing, so it is "not found", as a well-formed id that matches
    // nothing is. The API says 422 for it; pages that turn 404 into their
    // not-found page then do so for both, instead of crashing.
    const status = response.status === 422 && namesAMalformedPathPart(payload) ? 404 : response.status;
    throw new ApiError(status, payload);
  }

  return payload as T;
}

/** True when a 422 is only about the address: every complaint is about a path part. */
function namesAMalformedPathPart(payload: unknown): boolean {
  const detail = (payload as { detail?: unknown } | undefined)?.detail;
  return (
    Array.isArray(detail) &&
    detail.length > 0 &&
    detail.every((item) => Array.isArray((item as { loc?: unknown }).loc) && (item as { loc: unknown[] }).loc[0] === "path")
  );
}
