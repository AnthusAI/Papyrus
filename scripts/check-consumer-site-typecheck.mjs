#!/usr/bin/env node
/**
 * Build a minimal publication-site fixture against a packed @anthusai/papyrus
 * tarball and type-check it with only the dependencies real site repos declare.
 *   node scripts/check-consumer-site-typecheck.mjs <path to anthusai-papyrus-<version>.tgz>
 * Fails when a Papyrus source file needs a package the sites do not install.
 *
 * With `--build` it also runs `next build` of the generated app shell, the way a site's Amplify job does.
 * The fixture carries the root `overrides: { zod: "^3.25.76" }` every site has, which flattens nested
 * zod 4 dependencies (chatticus), so a dependency that needs a newer zod than the sites resolve fails here.
 */
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const withBuild = process.argv.includes("--build");
const tarballArgument = process.argv.slice(2).find((argument) => !argument.startsWith("--"));
if (!tarballArgument || !fs.existsSync(tarballArgument)) {
  console.error("usage: node scripts/check-consumer-site-typecheck.mjs <anthusai-papyrus tarball>");
  process.exit(1);
}
const tarball = path.resolve(tarballArgument);

const siteRepositoryDependencies = {
  "@aws-amplify/backend": "^1.22.0",
  "@aws-amplify/backend-cli": "^1.8.2",
  "@aws-amplify/seed": "^1.1.2",
  "aws-cdk-lib": "^2.257.0",
  constructs: "^10.4.2",
  next: "^15.5.18",
  react: "^19.2.6",
  "react-dom": "^19.2.6",
  zod: "^3.25.76",
};
const siteRepositoryDevDependencies = {
  "@types/node": "^22.0.0",
  "@types/react": "^19.2.0",
  typescript: "^5.9.0",
};

const fixtureFiles = {
  "package.json": JSON.stringify(
    {
      name: "consumer-site-fixture",
      private: true,
      type: "module",
      dependencies: { "@anthusai/papyrus": `file:${tarball}`, ...siteRepositoryDependencies },
      devDependencies: siteRepositoryDevDependencies,
      overrides: { "@aws-cdk/toolkit-lib": "1.32.0", "@opentelemetry/core": "2.11.0", zod: "^3.25.76" },
    },
    null,
    2,
  ),
  "tsconfig.json": JSON.stringify(
    {
      compilerOptions: {
        target: "ES2022",
        baseUrl: ".",
        lib: ["dom", "dom.iterable", "es2022"],
        allowJs: false,
        skipLibCheck: true,
        strict: true,
        noEmit: true,
        esModuleInterop: true,
        module: "esnext",
        moduleResolution: "bundler",
        resolveJsonModule: true,
        isolatedModules: true,
        jsx: "preserve",
        incremental: true,
        plugins: [{ name: "next" }],
        paths: {
          "@/*": ["./*"],
          "papyrus-site": ["./papyrus.config.ts"],
          "papyrus-site-theme": ["./publication/theme.css"],
          "papyrus-amplify-outputs": ["./amplify_outputs.json"],
        },
      },
      include: ["**/*.ts", "**/*.tsx", "papyrus-modules.d.ts", "next-env.d.ts"],
      exclude: ["node_modules", ".next", ".papyrus"],
    },
    null,
    2,
  ),
  "next.config.mjs": 'import { withPapyrus } from "@anthusai/papyrus/next";\n\nexport default withPapyrus({});\n',
  "papyrus-modules.d.ts": 'declare module "*.css";\n',
  "papyrus.config.ts": 'import { defineSite } from "@anthusai/papyrus/define-site";\n\nexport default defineSite({});\n',
  "amplify/backend.ts":
    'import { defineSiteBackend } from "@anthusai/papyrus/backend";\nimport site from "../papyrus.config";\n\nexport default defineSiteBackend(site);\n',
  "amplify/data/resource.ts": 'export type { Schema } from "@anthusai/papyrus/amplify/data/resource";\n',
  // Every site carries this file; without it Next passes the Tailwind sources through uncompiled.
  "postcss.config.mjs": 'export default { plugins: { "@tailwindcss/postcss": {} } };\n',
  "publication/theme.css": "",
  "amplify_outputs.json": "{}\n",
};

function runInFixture(fixture, command, commandArguments) {
  try {
    execFileSync(command, commandArguments, { cwd: fixture, stdio: "inherit" });
  } catch (error) {
    console.error(`FAIL: ${command} ${commandArguments.join(" ")} exited with ${error.status}`);
    process.exit(1);
  }
}

const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-consumer-site-"));
try {
  for (const [relativePath, content] of Object.entries(fixtureFiles)) {
    const destination = path.join(fixture, relativePath);
    fs.mkdirSync(path.dirname(destination), { recursive: true });
    fs.writeFileSync(destination, content);
  }
  runInFixture(fixture, "npm", ["install", "--no-audit", "--no-fund"]);
  try {
    execFileSync("npm", ["ls", "zod", "--all"], { cwd: fixture, stdio: "inherit" });
  } catch {
    // `npm ls` exits non-zero on override-invalid trees; it is diagnostics only.
  }
  runInFixture(fixture, "npx", ["papyrus-app", "sync"]);
  runInFixture(fixture, "npx", ["tsc", "--noEmit"]);
  console.log("ok: consumer site fixture type-checks against the packed package");
  if (withBuild) {
    // Staging drafts mode skips the build-time AppSync enumeration, so no deployed backend or secrets are needed.
    process.env.SITE_ENV = "staging";
    process.env.PAPYRUS_CONTENT_SOURCE = "drafts";
    runInFixture(fixture, "npx", ["next", "build"]);
    // The shell's responsive utilities must not be overridden by a second Tailwind build.
    execFileSync("node", [path.join(path.dirname(fileURLToPath(import.meta.url)), "test-single-tailwind-build.mjs"), path.join(fixture, ".next/static/css")], { stdio: "inherit" });
    console.log("ok: consumer site fixture builds against the packed package");
  }
} finally {
  fs.rmSync(fixture, { recursive: true, force: true });
}
