import { describe, expect, it } from "vitest";

import {
  isSessionMinutesValid,
  sessionMinutesInput,
  sessionMinutesPayload,
} from "./session-policy";

describe("the organisation session-length box", () => {
  it("treats empty as a real answer, not a missing one", () => {
    expect(isSessionMinutesValid("")).toBe(true);
    expect(isSessionMinutesValid("   ")).toBe(true);
    // Empty round-trips to null, which is what "deployment default" is stored as.
    expect(sessionMinutesPayload("")).toBeNull();
    expect(sessionMinutesInput(null)).toBe("");
  });

  it("accepts a whole number of minutes inside the range", () => {
    expect(isSessionMinutesValid("5")).toBe(true);
    expect(isSessionMinutesValid("60")).toBe(true);
    expect(isSessionMinutesValid("43200")).toBe(true);
    expect(sessionMinutesPayload("15")).toBe(15);
    expect(sessionMinutesInput(15)).toBe("15");
  });

  it("refuses a session too short to use or too long to mean anything", () => {
    expect(isSessionMinutesValid("0")).toBe(false);
    expect(isSessionMinutesValid("4")).toBe(false);
    expect(isSessionMinutesValid("43201")).toBe(false);
  });

  it("refuses anything that is not a whole number", () => {
    expect(isSessionMinutesValid("-5")).toBe(false);
    expect(isSessionMinutesValid("12.5")).toBe(false);
    expect(isSessionMinutesValid("1e3")).toBe(false);
    expect(isSessionMinutesValid("sixty")).toBe(false);
  });
});
