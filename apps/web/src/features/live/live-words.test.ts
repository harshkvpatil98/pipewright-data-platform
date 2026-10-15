import { describe, expect, it } from "vitest";

import type { LiveKind, LiveKindField, LiveWindow } from "@platform/shared-types";

import {
  behindWords,
  durationWords,
  everyWords,
  feedState,
  fieldValues,
  firstMissing,
  kindsOf,
  lateWords,
  settingsFrom,
  tableList,
  tableState,
  windowWords,
} from "./live-words";

const field = (key: string, kind: LiveKindField["kind"], extra: Partial<LiveKindField> = {}): LiveKindField => ({
  key,
  label: key[0].toUpperCase() + key.slice(1),
  kind,
  required: true,
  default: null,
  help: "",
  placeholder: "",
  options: [],
  ...extra,
});

describe("live feed words", () => {
  it("says how often in plain words", () => {
    expect(durationWords(5)).toBe("5 seconds");
    expect(durationWords(60)).toBe("1 minute");
    expect(durationWords(7200)).toBe("2 hours");
    expect(durationWords(90)).toBe("90 seconds");
    expect(everyWords(60)).toBe("every minute");
    expect(everyWords(5)).toBe("every 5 seconds");
    expect(everyWords(1)).toBe("every second");
  });

  it("says what a feed is doing", () => {
    const now = Date.parse("2026-10-15T12:00:00Z");
    expect(feedState({ status: "paused", failures: 0, last_event_at: null, family: "queue" }, now).word).toBe("Paused");
    expect(feedState({ status: "failing", failures: 3, last_event_at: null, family: "queue" }, now).tone).toBe("danger");
    expect(feedState({ status: "active", failures: 0, last_event_at: null, family: "queue" }, now).word).toBe(
      "Waiting for its first event",
    );
    expect(feedState({ status: "active", failures: 0, last_event_at: "2026-10-15T11:58:00Z", family: "queue" }, now).word).toBe(
      "Receiving",
    );
    expect(feedState({ status: "active", failures: 0, last_event_at: "2026-10-15T10:00:00Z", family: "queue" }, now).word).toBe(
      "Quiet",
    );
    expect(behindWords(0)).toBeNull();
    expect(behindWords(1)).toBe("1 event waiting at the source");
    expect(tableState({ state: "log_only", last_error: null }).word).toBe("Changes only");
    expect(tableState({ state: "waiting", last_error: "no table" }).word).toBe("Needs attention");
  });

  it("describes windows and late events without jargon", () => {
    const base: LiveWindow = { kind: "tumbling", size_seconds: 300, time_column: "at", lateness_seconds: 0, late: "drop", restate_for_seconds: 0 };
    expect(windowWords(base)).toBe("Back to back windows of 5 minutes");
    expect(windowWords({ ...base, kind: "hopping", advance_seconds: 60 })).toBe("Windows of 5 minutes, a new one every minute");
    expect(windowWords({ ...base, kind: "sliding" })).toBe("The last 5 minutes, at every change");
    expect(windowWords({ ...base, kind: "session", gap_seconds: 1800 })).toBe("Sessions ending after 30 minutes of quiet");
    expect(lateWords(base)).toBe("Does not wait for late events. One later still is counted and left out.");
    expect(lateWords({ ...base, lateness_seconds: 30, late: "restate", restate_for_seconds: 3600 })).toBe(
      "Waits 30 seconds for late events. One later still updates a window closed within 1 hour.",
    );
    for (const words of [windowWords(base), lateWords(base)]) expect(words).not.toMatch(/—|watermark|tumbling/i);
  });

  it("turns a kind's fields into a form and back", () => {
    const fields = [
      field("topic", "string"),
      field("port", "number", { required: false, default: 1883 }),
      field("tls", "boolean", { required: false, default: false }),
      field("password", "secret", { required: false }),
      field("token", "secret"),
    ];
    const values = fieldValues(fields, { topic: "orders", password: true });
    expect(values).toEqual({ topic: "orders", port: "1883", tls: "false", password: "", token: "" });
    expect(settingsFrom(fields, { ...values, port: "1884", tls: "true" })).toEqual({ topic: "orders", port: 1884, tls: true });
    expect(firstMissing(fields, values)).toBe("Token");
    expect(firstMissing(fields, values, { token: true })).toBeNull();
    expect(tableList("public.orders, public.orders\ncustomers,  ")).toEqual(["public.orders", "customers"]);
  });

  it("lists a family's kinds, ones that work here first", () => {
    const kind = (key: string, label: string, available: boolean) =>
      ({ key, label, family: "queue", available }) as unknown as LiveKind;
    expect(kindsOf([kind("b", "Beta", false), kind("a", "Alpha", true), kind("c", "Cee", true)], "queue").map((k) => k.key)).toEqual([
      "a",
      "c",
      "b",
    ]);
  });
});
