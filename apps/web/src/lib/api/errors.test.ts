import { ApiError, UNREACHABLE_MESSAGE, extractErrorMessage, parseApiResponse } from "@/lib/api/errors";

describe("api error handling", () => {
  it("extracts detail messages from ApiError payloads", () => {
    const error = new ApiError(400, { detail: "Readable validation error" });
    expect(extractErrorMessage(error)).toBe("Readable validation error");
  });

  it("falls back to generic error messages for unknown values", () => {
    expect(extractErrorMessage("unexpected")).toBe("Something went wrong. Please try again.");
  });
});

describe("parseApiResponse", () => {
  it("accepts a 204 that is labelled json but carries no body", async () => {
    // The bug this covers: every DELETE in the API answers 204 with
    // `content-type: application/json` and an empty body, so calling
    // `.json()` threw "Unexpected end of JSON input" on a request that had
    // succeeded. Removing a member deleted the row and then reported failure.
    const response = new Response(null, {
      status: 204,
      headers: { "content-type": "application/json" },
    });

    await expect(parseApiResponse(response)).resolves.toBeUndefined();
  });

  it("still parses a json body when there is one", async () => {
    const response = new Response(JSON.stringify({ id: "abc" }), {
      status: 200,
      headers: { "content-type": "application/json" },
    });

    await expect(parseApiResponse<{ id: string }>(response)).resolves.toEqual({ id: "abc" });
  });

  it("raises the server's own message on a refusal", async () => {
    // The delete guards answer 409 with a sentence saying what to do instead,
    // and that sentence is the whole value of the response.
    const response = new Response(JSON.stringify({ detail: "Still owns 3 project(s)." }), {
      status: 409,
      headers: { "content-type": "application/json" },
    });

    await expect(parseApiResponse(response)).rejects.toMatchObject({
      status: 409,
      detail: { detail: "Still owns 3 project(s)." },
    });
  });

  it("does not choke on an error response with an empty body", async () => {
    const response = new Response(null, {
      status: 500,
      headers: { "content-type": "application/json" },
    });

    await expect(parseApiResponse(response)).rejects.toMatchObject({ status: 500 });
  });

  it("treats a malformed id in the address as not found", async () => {
    const malformed = new Response(
      JSON.stringify({ detail: [{ type: "uuid_parsing", loc: ["path", "workflow_id"], msg: "Input should be a valid UUID" }] }),
      { status: 422, headers: { "content-type": "application/json" } },
    );
    await expect(parseApiResponse(malformed)).rejects.toMatchObject({ status: 404 });

    const badBody = new Response(
      JSON.stringify({ detail: [{ type: "missing", loc: ["body", "name"], msg: "Field required" }] }),
      { status: 422, headers: { "content-type": "application/json" } },
    );
    await expect(parseApiResponse(badBody)).rejects.toMatchObject({ status: 422 });
  });
});

describe("messages a person can act on", () => {
  it("says the server could not be reached, in any browser's words", () => {
    for (const raw of ["Failed to fetch", "NetworkError when attempting to fetch resource.", "Load failed"]) {
      expect(extractErrorMessage(new TypeError(raw))).toBe(UNREACHABLE_MESSAGE);
    }
  });

  it("names the fields a refused form got wrong", () => {
    const refused = new ApiError(422, {
      detail: [{ loc: ["body", "name"], msg: "Field required", type: "missing" }],
    });
    expect(extractErrorMessage(refused)).toBe("Some details need changing. name: Field required.");
  });

  it("does not show a status code for a server failure", () => {
    expect(extractErrorMessage(new ApiError(502, undefined))).toMatch(
      /^Something went wrong on Pipewright's server/,
    );
  });
});

