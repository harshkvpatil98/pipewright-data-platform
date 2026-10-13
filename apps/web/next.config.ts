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

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: ["@platform/shared-types", "@platform/shared-ui"],
  async redirects() {
    return MOVED_PROJECT_PAGES.map(([from, to]) => ({
      source: `/projects/:projectId/${from}`,
      destination: `/projects/:projectId/${to}`,
      permanent: true,
    }));
  },
};

export default nextConfig;
