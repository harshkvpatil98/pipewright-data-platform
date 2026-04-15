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
  const payload = contentType.includes("application/json") ? await response.json() : await response.text();

  if (!response.ok) {
    throw new ApiError(response.status, payload);
  }

  return payload as T;
}
