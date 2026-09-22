/**
 * A dependency-free password strength heuristic.
 *
 * Not a security control — the server enforces the real minimum — but honest
 * feedback while typing. It rewards length and variety and punishes the
 * patterns that make a password guessable (a single repeated character, a
 * pure sequence, an obvious common word), so "Password1" does not read as
 * strong just because it has four character classes.
 */

export type PasswordStrength = {
  score: 0 | 1 | 2 | 3 | 4;
  label: "Too weak" | "Weak" | "Fair" | "Good" | "Strong";
};

const COMMON = new Set([
  "password", "passw0rd", "letmein", "welcome", "admin", "qwerty",
  "12345678", "123456789", "changeme", "iloveyou", "pipewright",
]);

export function assessPassword(password: string): PasswordStrength {
  const pw = password ?? "";
  if (pw.length === 0) return { score: 0, label: "Too weak" };

  const lower = pw.toLowerCase();
  if (COMMON.has(lower)) return { score: 0, label: "Too weak" };

  let points = 0;
  if (pw.length >= 8) points += 1;
  if (pw.length >= 12) points += 1;
  if (pw.length >= 16) points += 1;

  const classes =
    Number(/[a-z]/.test(pw)) +
    Number(/[A-Z]/.test(pw)) +
    Number(/[0-9]/.test(pw)) +
    Number(/[^A-Za-z0-9]/.test(pw));
  if (classes >= 2) points += 1;
  if (classes >= 3) points += 1;

  // Penalise low-entropy shapes even when they are long.
  const oneCharRepeated = /^(.)\1+$/.test(pw);
  const pureSequence = /^(0123456789|abcdefghijklmnopqrstuvwxyz).*/.test(lower) && classes === 1;
  if (oneCharRepeated || pureSequence) points = Math.min(points, 1);

  const score = Math.max(0, Math.min(4, points - 1)) as PasswordStrength["score"];
  const label = (["Too weak", "Weak", "Fair", "Good", "Strong"] as const)[score];
  return { score, label };
}
