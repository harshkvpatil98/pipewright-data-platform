"use client";

import { cx } from "@/lib/utils";

import { PRESENCE_COLOURS, type PresencePerson } from "./use-presence";

/**
 * People shown by their initials, each ringed in their own colour (C2):
 * at the top of the Studio, and on the step each has open.
 */
export function PresenceDots({
  people,
  label,
  size = "md",
}: {
  people: PresencePerson[];
  /** What having one of these means, for the tooltip: "is here". */
  label: (person: PresencePerson) => string;
  size?: "sm" | "md";
}) {
  if (people.length === 0) return null;
  const shown = people.slice(0, 4);
  const more = people.length - shown.length;
  return (
    <span className="flex shrink-0 items-center -space-x-1.5" aria-label={people.map(label).join("; ")} role="group">
      {shown.map((person) => (
        <span
          key={person.client_id}
          title={label(person)}
          className={cx(
            "flex items-center justify-center rounded-full border-2 bg-surface font-semibold text-ink",
            size === "sm" ? "h-6 w-6 text-[12px]" : "h-8 w-8 text-[12px]",
          )}
          style={{ borderColor: PRESENCE_COLOURS[person.colour % PRESENCE_COLOURS.length] }}
        >
          {person.initials}
        </span>
      ))}
      {more > 0 ? (
        <span
          title={`${more} more`}
          className={cx(
            "flex items-center justify-center rounded-full border-2 border-line bg-surface-2 text-[12px] text-ink-2",
            size === "sm" ? "h-6 w-6" : "h-8 w-8",
          )}
        >
          +{more}
        </span>
      ) : null}
    </span>
  );
}
