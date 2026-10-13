import { describe, expect, it } from "vitest";

import { describeCron } from "@/lib/cron-words";

describe("describeCron", () => {
  it.each([
    ["0 * * * *", "Every hour, on the hour"],
    ["15 * * * *", "Every hour at 15 past"],
    ["*/10 * * * *", "Every 10 minutes"],
    ["0 */6 * * *", "Every 6 hours"],
    ["0 9 * * *", "Every day at 09:00"],
    ["30 18 * * 1-5", "Every weekday at 18:30"],
    ["0 9 * * 1", "Every Monday at 09:00"],
    ["0 9 * * 0", "Every Sunday at 09:00"],
    ["0 9 * * 7", "Every Sunday at 09:00"],
    ["0 9 1 * *", "On the first of every month at 09:00"],
    ["0 9 22 * *", "On the 22nd of every month at 09:00"],
  ])("reads %s as %s", (expression, words) => {
    expect(describeCron(expression)).toBe(words);
  });

  it("says custom rather than guessing", () => {
    expect(describeCron("0 9 1 1 *")).toBe("A custom timetable");
    expect(describeCron("0 9 * * 1,3")).toBe("A custom timetable");
    expect(describeCron("nonsense")).toBe("A custom timetable");
    expect(describeCron("0 25 * * *")).toBe("A custom timetable");
  });
});
