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

export function extractErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (typeof error.detail === "string") {
      return error.detail;
    }
    if (
      typeof error.detail === "object" &&
      error.detail !== null &&
      "detail" in error.detail &&
      typeof (error.detail as { detail?: unknown }).detail === "string"
    ) {
      return (error.detail as { detail: string }).detail;
    }
    return error.message;
  }

  if (error instanceof Error) {
    return error.message;
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
    throw new ApiError(response.status, payload);
  }

  return payload as T;
}
