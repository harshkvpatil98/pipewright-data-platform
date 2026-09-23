import { MAX_SESSION_MINUTES, MIN_SESSION_MINUTES } from "@platform/shared-types";

/**
 * What the session-length box means, and what it is allowed to say.
 *
 * Empty is a real answer -- it means "follow the deployment default", the same
 * thing null means in the database. Without that distinction a tenant that has
 * never set a policy would acquire one the first time somebody opened the
 * dialog and saved a name.
 *
 * The server clamps whatever arrives to the same range, so this exists to stop
 * a value being silently corrected rather than to be the rule.
 */
export function isSessionMinutesValid(raw: string): boolean {
  const value = raw.trim();
  if (value === "") return true;
  if (!/^\d+$/.test(value)) return false;
  const minutes = Number(value);
  return minutes >= MIN_SESSION_MINUTES && minutes <= MAX_SESSION_MINUTES;
}

/** The value to send: a number, or null for "deployment default". */
export function sessionMinutesPayload(raw: string): number | null {
  const value = raw.trim();
  return value === "" ? null : Number(value);
}

/** How the box is filled in when the dialog opens. */
export function sessionMinutesInput(stored: number | null): string {
  return stored === null ? "" : String(stored);
}
