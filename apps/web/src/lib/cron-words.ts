/**
 * A schedule's timetable in words: "Every day at 09:00", not "0 9 * * *".
 *
 * Covers the shapes the schedule form's presets write and the common ones
 * people type. Anything else is "A custom timetable", and the page shows the
 * expression beside it; a wrong translation would be worse than none.
 */

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const isNumber = (part: string) => /^\d+$/.test(part);
const pad = (value: number) => String(value).padStart(2, "0");

function ordinal(day: number): string {
  if (day === 1) return "first";
  const suffix = day % 10 === 1 && day !== 11 ? "st" : day % 10 === 2 && day !== 12 ? "nd" : day % 10 === 3 && day !== 13 ? "rd" : "th";
  return `${day}${suffix}`;
}

export function describeCron(expression: string): string {
  const parts = expression.trim().split(/\s+/);
  if (parts.length !== 5) return "A custom timetable";
  const [minute, hour, dayOfMonth, month, dayOfWeek] = parts;

  const step = /^\*\/(\d+)$/;
  if (step.test(minute) && hour === "*" && dayOfMonth === "*" && month === "*" && dayOfWeek === "*") {
    const n = Number(minute.match(step)![1]);
    return n === 1 ? "Every minute" : `Every ${n} minutes`;
  }
  if (!isNumber(minute) || month !== "*") return "A custom timetable";
  const m = Number(minute);
  if (m > 59) return "A custom timetable";

  if (hour === "*" && dayOfMonth === "*" && dayOfWeek === "*") {
    return m === 0 ? "Every hour, on the hour" : `Every hour at ${pad(m)} past`;
  }
  if (step.test(hour) && dayOfMonth === "*" && dayOfWeek === "*") {
    const n = Number(hour.match(step)![1]);
    return `Every ${n} hours${m ? ` at ${pad(m)} past` : ""}`;
  }
  if (!isNumber(hour) || Number(hour) > 23) return "A custom timetable";
  const time = `${pad(Number(hour))}:${pad(m)}`;

  if (dayOfMonth === "*" && dayOfWeek === "*") return `Every day at ${time}`;
  if (dayOfMonth === "*" && (dayOfWeek === "1-5" || dayOfWeek === "MON-FRI")) {
    return `Every weekday at ${time}`;
  }
  if (dayOfMonth === "*" && isNumber(dayOfWeek) && Number(dayOfWeek) <= 7) {
    return `Every ${DAYS[Number(dayOfWeek) % 7]} at ${time}`;
  }
  if (dayOfWeek === "*" && isNumber(dayOfMonth) && Number(dayOfMonth) >= 1 && Number(dayOfMonth) <= 31) {
    return `On the ${ordinal(Number(dayOfMonth))} of every month at ${time}`;
  }
  return "A custom timetable";
}
