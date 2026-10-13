import { describe, expect, it } from "vitest";

import { configFrom, KIND_BY_TYPE, missingField, valuesFrom } from "@/features/destinations/destination-kinds";

const mysql = KIND_BY_TYPE.get("mysql")!;
const s3 = KIND_BY_TYPE.get("s3")!;

describe("destination kinds", () => {
  it("sends numbers as numbers and leaves out empty optional fields", () => {
    const config = configFrom(s3, { bucket: "b", prefix: "", region: "", endpoint_url: "http://minio:9000", access_key_id: "k", secret_access_key: "s" });
    expect(config).toEqual({ bucket: "b", endpoint_url: "http://minio:9000", access_key_id: "k", secret_access_key: "s" });
    expect(configFrom(mysql, { host: "h", port: "3306", database: "d", username: "u", password: "p" }).port).toBe(3306);
  });

  it("never shows a saved secret, and keeps it when the field stays empty", () => {
    const values = valuesFrom(mysql, { host: "h", port: 3306, database: "d", username: "u", password: "***" });
    expect(values.password).toBe("");
    expect(configFrom(mysql, values)).not.toHaveProperty("password");
  });

  it("names the first required field left empty, except a secret when editing", () => {
    const values = { host: "h", port: "3306", database: "", username: "u", password: "" };
    expect(missingField(mysql, values, false)).toBe("Database");
    expect(missingField(mysql, { ...values, database: "d" }, true)).toBeNull();
    expect(missingField(mysql, { ...values, database: "d" }, false)).toBe("Password");
  });
});
