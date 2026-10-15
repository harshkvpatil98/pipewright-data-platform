import { fileURLToPath } from "node:url";

import { configDefaults, defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
    // The shared UI package would otherwise load the workspace root's React
    // beside this app's, and a hook in one of its components would find none.
    dedupe: ["react", "react-dom"],
  },
  css: {
    postcss: {
      plugins: [],
    },
  },
  test: {
    // Default to node so pure unit tests run without loading jsdom (avoids broken jsdom/whatwg-url on some Node setups).
    environment: "node",
    globals: true,
    // Browser tests run under Playwright (e2e/), not Vitest.
    exclude: [...configDefaults.exclude, "e2e/**"],
  },
});
