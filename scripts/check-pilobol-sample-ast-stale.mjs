#!/usr/bin/env node
/**
 * Fail when `web/content/articles/sample.md` changes but
 * `scripts/fixtures/pilobol-sample.ast.json` was not regenerated.
 *
 * Regenerate (Markus CLI date bug — use Python):
 *   python3 scripts/regenerate-pilobol-sample-ast.py
 *
 * Run: node scripts/check-pilobol-sample-ast-stale.mjs
 */
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "..");
const markdownPath = path.join(repoRoot, "web/content/articles/sample.md");
const fixturePath = path.join(repoRoot, "scripts/fixtures/pilobol-sample.ast.json");

const markdown = readFileSync(markdownPath, "utf8");
const markdownHash = createHash("sha256").update(markdown).digest("hex");

const fixture = JSON.parse(readFileSync(fixturePath, "utf8"));
const recordedHash = fixture._papyrus_source_sha256;

if (recordedHash !== markdownHash) {
  console.error(
    "FAIL: pilobol-sample.ast.json is stale relative to web/content/articles/sample.md.\n" +
      `  markdown sha256: ${markdownHash}\n` +
      `  fixture record:  ${recordedHash ?? "(missing _papyrus_source_sha256)"}\n` +
      "  Regenerate with: python3 scripts/regenerate-pilobol-sample-ast.py",
  );
  process.exit(1);
}

console.log("pilobol-sample AST fixture is current with sample.md");
