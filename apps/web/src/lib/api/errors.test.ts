import { ApiError, extractErrorMessage } from "@/lib/api/errors";

describe("api error handling", () => {
  it("extracts detail messages from ApiError payloads", () => {
    const error = new ApiError(400, { detail: "Readable validation error" });
    expect(extractErrorMessage(error)).toBe("Readable validation error");
  });

  it("falls back to generic error messages for unknown values", () => {
    expect(extractErrorMessage("unexpected")).toBe("Something went wrong. Please try again.");
  });
});
