import { FlatCompat } from "@eslint/eslintrc";
import { dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const compat = new FlatCompat({
  baseDirectory: __dirname,
});

const eslintConfig = [
  {
    ignores: [
      ".amplify/**",
      ".next/**",
      "node_modules/**",
      "dist/**",
      "out/**",
      "coverage/**",
      "corpora/**",
      "public/videoml/**",
      "spikes/scheduling-calendar/**", // a standalone Next app with its own dependencies and rules
      "src/papyrus_content/projection/standard/assets/mermaid.min.js", // vendored third-party bundle
    ],
  },
  ...compat.extends("next/core-web-vitals"),
];

export default eslintConfig;
