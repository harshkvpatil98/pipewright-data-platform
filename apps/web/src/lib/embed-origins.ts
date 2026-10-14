/**
 * Which other sites may show an embedded dashboard in a frame (A8, Y4).
 *
 * An administrator lists them in `EMBED_ALLOWED_ORIGINS`, read when each page
 * is served, so changing it needs a restart and not a rebuild. Each entry is a
 * site's address: `https://portal.example.com`, `https://*.example.com`, or
 * `http://localhost:8080` while trying it out. Anything else is ignored and
 * named on the dashboard's Embed panel, so a typo is seen rather than silent.
 */

const ORIGIN = /^https:\/\/(\*\.)?[a-z0-9]([a-z0-9-]*[a-z0-9])?(\.[a-z0-9]([a-z0-9-]*[a-z0-9])?)*(:\d{1,5})?$/;
const LOCAL = /^http:\/\/(localhost|127\.0\.0\.1)(:\d{1,5})?$/;

export type EmbedOrigins = { allowed: string[]; ignored: string[] };

export function parseEmbedOrigins(value: string | undefined): EmbedOrigins {
  const allowed: string[] = [];
  const ignored: string[] = [];
  for (const raw of (value ?? "").split(/[\s,]+/)) {
    const entry = raw.trim().replace(/\/+$/, "");
    if (!entry) continue;
    const lower = entry.toLowerCase();
    if (ORIGIN.test(lower) || LOCAL.test(lower)) {
      if (!allowed.includes(lower)) allowed.push(lower);
    } else {
      ignored.push(entry);
    }
  }
  return { allowed, ignored };
}

/** The `frame-ancestors` an embed page is sent with: this site, and the listed ones. */
export function frameAncestors(origins: EmbedOrigins): string {
  return ["'self'", ...origins.allowed].join(" ");
}

export function embedOrigins(): EmbedOrigins {
  return parseEmbedOrigins(process.env.EMBED_ALLOWED_ORIGINS);
}
