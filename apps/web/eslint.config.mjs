import js from "@eslint/js";
import globals from "globals";
import tseslint from "typescript-eslint";

const config = tseslint.config(
  {
    ignores: [".next/**", "coverage/**", "node_modules/**", "next-env.d.ts"],
  },
  js.configs.recommended,
  ...tseslint.configs.recommended,
  {
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      globals: {
        ...globals.browser,
        ...globals.node,
      },
    },
  },
);

export default config;
