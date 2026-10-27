#!/usr/bin/env node
/**
 * node scripts/bundle-chat-lambdas.mjs --out DIR
 *
 * Bundles the two private-chat worker handlers (infra/shared-chat-runtime/lambda) with the pinned Chatticus runtime
 * into DIR (run-worker.js, probe-worker.js). Pass DIR to the chat stack as `-c chatLambdas=DIR`
 * (docs/private-newsroom-chat-per-site.md). Run from a Papyrus checkout with `npm ci` done.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const outIndex = process.argv.indexOf("--out");
const out = outIndex >= 0 ? path.resolve(process.argv[outIndex + 1] ?? "") : "";
if (!out || out === path.parse(out).root) {
  console.error("Usage: node scripts/bundle-chat-lambdas.mjs --out DIR");
  process.exit(1);
}
const require = createRequire(path.join(root, "package.json"));
const esbuild = require("esbuild");
fs.rmSync(out, { recursive: true, force: true });
await esbuild.build({
  absWorkingDir: root,
  entryPoints: ["infra/shared-chat-runtime/lambda/run-worker.ts", "infra/shared-chat-runtime/lambda/probe-worker.ts"],
  outdir: out,
  bundle: true,
  packages: "bundle",
  platform: "node",
  format: "cjs",
  target: "node22",
  alias: { "chatticus/chat-runtime": require.resolve("chatticus/chat-runtime") },
});
const emitted = fs.readdirSync(out).sort();
if (JSON.stringify(emitted) !== JSON.stringify(["probe-worker.js", "run-worker.js"])) {
  throw new Error(`Unexpected chat Lambda asset files: ${emitted.join(", ")}`);
}
console.log(`bundled ${emitted.join(", ")} -> ${out}`);
