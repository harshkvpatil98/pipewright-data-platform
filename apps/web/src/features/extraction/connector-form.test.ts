import { describe, expect, it } from "vitest";

import type { ConnectorConfigField, ConnectorSpec } from "@platform/shared-types";

import {
  connectorConfig,
  firstMissing,
  importableConnectors,
  initialValues,
  splitFields,
} from "@/features/extraction/connector-form";

const field = (overrides: Partial<ConnectorConfigField> & Pick<ConnectorConfigField, "name">): ConnectorConfigField => ({
  label: overrides.name,
  kind: "string",
  required: false,
  default: null,
  help: null,
  options: [],
  placeholder: null,
  ...overrides,
});

const spec = (overrides: Partial<ConnectorSpec> & Pick<ConnectorSpec, "type" | "label">): ConnectorSpec => ({
  category: "api",
  description: "",
  config_fields: [],
  capabilities: ["test", "read"],
  secret_fields: [],
  driver_package: null,
  documentation_url: null,
  available: true,
  unavailable_reason: null,
  tier: 2,
  tier_label: "Tested",
  tier_badge: "◑",
  tier_explanation: "",
  verified: true,
  verified_by: null,
  origin: "handwritten",
  ...overrides,
});

describe("the connector catalogue", () => {
  const catalogue = [
    spec({ type: "zeta", label: "Zeta", verified: false, tier: 4 }),
    spec({ type: "github", label: "GitHub", category: "saas" }),
    spec({ type: "webhook_out", label: "Hooks", capabilities: ["test", "write"] }),
    spec({ type: "athena", label: "Athena", category: "database", available: false }),
    spec({ type: "rest_api", label: "REST API" }),
  ];

  it("offers only what can be read, available and tested first", () => {
    expect(importableConnectors(catalogue, "", null).map((s) => s.type)).toEqual(["github", "rest_api", "zeta", "athena"]);
  });

  it("filters by group and by every word typed", () => {
    expect(importableConnectors(catalogue, "", "saas").map((s) => s.type)).toEqual(["github"]);
    expect(importableConnectors(catalogue, "rest api", null).map((s) => s.type)).toEqual(["rest_api"]);
  });
});

describe("a connector's form", () => {
  const fields = [
    field({ name: "base_url", required: true }),
    field({ name: "page_size", kind: "number", default: 100 }),
    field({ name: "token", kind: "secret" }),
    field({ name: "verify", kind: "boolean", default: true }),
  ];

  it("starts from the defaults and sends typed values, leaving empty ones out", () => {
    const values = initialValues(fields);
    expect(values).toEqual({ base_url: "", page_size: "100", token: "", verify: "true" });
    expect(connectorConfig(fields, { ...values, base_url: " https://api.example.com " })).toEqual({
      base_url: "https://api.example.com",
      page_size: 100,
      verify: true,
    });
  });

  it("names the first required field left empty", () => {
    expect(firstMissing(fields, initialValues(fields))).toBe("base_url");
    expect(firstMissing(fields, { base_url: "x" })).toBeNull();
  });
});

describe("splitFields", () => {
  it("keeps required fields and the first few up front", () => {
    const fields = ["a", "b", "c", "d", "e", "f"].map((name) => field({ name, required: name === "f" }));
    const { main, more } = splitFields(fields, 3);
    expect(main.map((f) => f.name)).toEqual(["a", "b", "c", "f"]);
    expect(more.map((f) => f.name)).toEqual(["d", "e"]);
  });
});
