import { defineConfig, globalIgnores } from "eslint/config";
import nextPlugin from "@next/eslint-plugin-next";

export default defineConfig([
  nextPlugin.flatConfig.coreWebVitals,
  globalIgnores([".next/**", "out/**"]),
]);
