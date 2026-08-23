import { describe, expect, it } from "vitest";

import {
  classify,
  describeProfile,
  profileColumn,
  qualityBands,
} from "@/features/studio/grid/column-profile";

describe("classifying values", () => {
  it("separates null from empty", () => {
    // Different facts: a column that is half empty strings behaves very
    // differently from one that is half nulls, and collapsing them hides that.
    expect(classify(null)).toBe("null");
    expect(classify(undefined)).toBe("null");
    expect(classify("")).toBe("empty");
    expect(classify("   ")).toBe("empty");
    expect(classify("a")).toBe("value");
  });

  it("treats zero and false as values, not absence", () => {
    expect(classify(0)).toBe("value");
    expect(classify(false)).toBe("value");
  });
});

describe("profiling a column", () => {
  it("counts nulls, empties and values separately", () => {
    const profile = profileColumn("c", ["a", "b", "", null, "a"]);
    expect(profile.nulls).toBe(1);
    expect(profile.empties).toBe(1);
    expect(profile.values).toBe(3);
  });

  it("counts distinct values", () => {
    expect(profileColumn("c", ["a", "b", "a", "c"]).distinct).toBe(3);
  });

  it("summarises a numeric column", () => {
    const profile = profileColumn("n", [1, 2, 3, 4]);
    expect(profile.numeric).toEqual({ min: 1, max: 4, mean: 2.5, median: 2.5 });
  });

  it("takes the middle value for an odd count", () => {
    expect(profileColumn("n", [1, 5, 3]).numeric?.median).toBe(3);
  });

  it("does not summarise a column with any non-numeric value", () => {
    // One bad row means the summary would describe a subset, not the column.
    expect(profileColumn("n", [1, 2, "x"]).numeric).toBeNull();
  });

  it("summarises numbers held as strings", () => {
    expect(profileColumn("n", ["1", "2", "3"]).numeric?.max).toBe(3);
  });

  it("ignores nulls when deciding whether a column is numeric", () => {
    expect(profileColumn("n", [1, null, 3]).numeric?.min).toBe(1);
  });

  it("reports the length range", () => {
    const profile = profileColumn("c", ["a", "abcd"]);
    expect(profile.shortest).toBe(1);
    expect(profile.longest).toBe(4);
  });

  it("ranks the most frequent values", () => {
    const profile = profileColumn("c", ["a", "a", "a", "b", "b", "c"]);
    expect(profile.top[0]).toEqual({ value: "a", count: 3, share: 0.5 });
    expect(profile.top[1].value).toBe("b");
  });

  it("caps the top values so a legend stays readable", () => {
    const many = Array.from({ length: 900 }, (_, index) => `v${index}`);
    expect(profileColumn("c", many).top.length).toBeLessThanOrEqual(8);
  });

  it("handles an empty column without dividing by zero", () => {
    const profile = profileColumn("c", []);
    expect(profile.distinct).toBe(0);
    expect(profile.numeric).toBeNull();
    expect(profile.top).toEqual([]);
  });

  it("handles an all-null column", () => {
    const profile = profileColumn("c", [null, null]);
    expect(profile.nulls).toBe(2);
    expect(profile.values).toBe(0);
    expect(profile.numeric).toBeNull();
  });

  it("records whether it saw every row", () => {
    // Reporting a sample as if it were the whole table is the dishonest option.
    expect(profileColumn("c", ["a"], { complete: true }).complete).toBe(true);
    expect(profileColumn("c", ["a"]).complete).toBe(false);
  });
});

describe("the header quality bar", () => {
  it("gives proportions that add to one", () => {
    const bands = qualityBands(profileColumn("c", ["a", "", null, "b"]));
    const total = bands.reduce((sum, band) => sum + band.share, 0);
    expect(total).toBeCloseTo(1);
  });

  it("omits bands with nothing in them", () => {
    const bands = qualityBands(profileColumn("c", ["a", "b"]));
    expect(bands).toHaveLength(1);
    expect(bands[0].kind).toBe("value");
  });

  it("draws nothing for an empty column", () => {
    expect(qualityBands(profileColumn("c", []))).toEqual([]);
  });
});

describe("describing a profile", () => {
  it("leads with the problem", () => {
    const text = describeProfile(profileColumn("c", ["a", null, null, null]));
    expect(text).toContain("75% null");
  });

  it("says when it only saw part of the table", () => {
    // Otherwise "12% null" reads as a fact about the data rather than a sample.
    expect(describeProfile(profileColumn("c", ["a"]))).toContain("first 1 rows");
    expect(describeProfile(profileColumn("c", ["a"], { complete: true }))).toContain("1 rows");
  });
});
