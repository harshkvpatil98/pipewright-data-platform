import type { NextConfig } from "next";

/**
 * Old addresses that moved when the navigation was rebuilt around one
 * vocabulary (adoption-readiness A1). Bookmarks, emailed links and the docs
 * must keep working, so every renamed page redirects permanently.
 */
const MOVED_PROJECT_PAGES: [from: string, to: string][] = [
  ["extraction", "sources"],
  ["data-quality", "checks"],
];

/**
 * Headers every page is sent with (A6, W7): no guessing content types, no
 * full addresses leaked to other sites, and no camera, microphone or
 * location. Content security policy is left to the proxy in front, which
 * knows the deployment's own addresses.
 */
export const SECURITY_HEADERS = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

/**
 * No framing by other sites, except embedded dashboards (A8, Y4), whose
 * `frame-ancestors` src/proxy.ts sends from `EMBED_ALLOWED_ORIGINS`.
 */
export const FRAME_HEADERS = [{ key: "X-Frame-Options", value: "SAMEORIGIN" }];
export const FRAMED_EVERYWHERE_BUT_EMBEDS = "/:path((?!embed/).*)";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // The build checks the app with the same configuration as the typecheck
  // step, which leaves out test files: since Next 16.4 the build checks every
  // file tsconfig.json includes, and tests use Vitest's globals.
  typescript: { tsconfigPath: "tsconfig.typecheck.json" },
  transpilePackages: ["@platform/shared-types", "@platform/shared-ui"],
  async headers() {
    return [
      { source: "/:path*", headers: SECURITY_HEADERS },
      { source: FRAMED_EVERYWHERE_BUT_EMBEDS, headers: FRAME_HEADERS },
    ];
  },
  async redirects() {
    return MOVED_PROJECT_PAGES.map(([from, to]) => ({
      source: `/projects/:projectId/${from}`,
      destination: `/projects/:projectId/${to}`,
      permanent: true,
    }));
  },
};

export default nextConfig;
