import { describe, expect, it } from "vitest";

import type { MetricSeries } from "@platform/shared-types";

import { alertState, measureChoices, measureKey } from "@/features/dataset-metrics/components/metric-alerts-panel";

const series = (metric_key: string, column_name: string | null, label: string): MetricSeries => ({
  metric_key,
  column_name,
  label,
  unit: null,
  points: [],
  latest: null,
  previous: null,
  change_percentage: null,
});

/* The Alerts panel on a dataset's Metrics page (A8, Y5). */
describe("metric alerts", () => {
  it("offers the measures recorded, and every dataset's own before any are", () => {
    expect(measureChoices([]).map((item) => item.label)).toEqual([
      "row count",
      "completeness",
      "duplicate rows",
      "column count",
    ]);
    const recorded = measureChoices([series("row_count", null, "row count"), series("mean_value", "amount", "average of 'amount'")]);
    expect(recorded.map(measureKey)).toEqual([
      "row_count|",
      "completeness_score|",
      "duplicate_row_percentage|",
      "column_count|",
      "mean_value|amount",
    ]);
    const columnsFirst = measureChoices([series("column_count", null, "column count"), series("null_percentage", "email", "null rate of 'email'")]);
    expect(columnsFirst[0].metric_key).toBe("row_count");
  });

  it("says whether an alert is past its line", () => {
    expect(alertState({ enabled: true, state: "crossed" })).toEqual({ word: "Past its line", tone: "warning" });
    expect(alertState({ enabled: true, state: "ok" })).toEqual({ word: "Within", tone: "success" });
    expect(alertState({ enabled: false, state: "crossed" })).toEqual({ word: "Off", tone: "neutral" });
  });
});
