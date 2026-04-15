import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

export default defineConfig({
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
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
  },
});
