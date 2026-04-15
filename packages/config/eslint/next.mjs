import eslintConfigNext from "eslint-config-next/core-web-vitals";
import eslintConfigPrettier from "eslint-config-prettier";

export default [
  ...eslintConfigNext,
  eslintConfigPrettier,
  {
    ignores: [".next/**", "coverage/**", "node_modules/**", "next-env.d.ts"],
  },
];
