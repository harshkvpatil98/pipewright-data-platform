import { describe, expect, it } from "vitest";

import { missingSetting } from "@/features/workflows/missing-setting";

describe("a task that is not filled in", () => {
  it("names what each kind of task still needs", () => {
    expect(missingSetting({ node_type: "extraction", config: {} })).toBe("choose which import it runs.");
    expect(missingSetting({ node_type: "transformation", config: {} })).toBe("choose which recipe it runs.");
    expect(missingSetting({ node_type: "quality_gate", config: {} })).toBe("choose which dataset it checks.");
    expect(missingSetting({ node_type: "publish", config: { dataset_from: "load" } })).toBe("choose where it delivers to.");
    expect(missingSetting({ node_type: "publish", config: { destination_id: "d" } })).toBe("choose which dataset it delivers.");
  });

  it("says nothing once it is filled in, or when it needs nothing", () => {
    expect(missingSetting({ node_type: "extraction", config: { extraction_job_id: "j" } })).toBeNull();
    expect(missingSetting({ node_type: "quality_gate", config: { dataset_from: "load" } })).toBeNull();
    expect(missingSetting({ node_type: "notify", config: {} })).toBeNull();
  });
});
