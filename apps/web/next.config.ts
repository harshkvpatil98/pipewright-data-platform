import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: ["@platform/shared-types", "@platform/shared-ui"],
};

export default nextConfig;
