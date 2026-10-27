#!/usr/bin/env node
/**
 * Exactly one Tailwind build per app. A second `@import "tailwindcss"` emits a second complete
 * stylesheet (theme, preflight, utilities) that loads later; when its content scan is narrower
 * (a consumer site keeps Papyrus under node_modules, which auto-detection skips) its `.hidden`
 * overrides the first build's `md:flex` and the References review panel never shows on desktop.
 *
 *   node scripts/test-single-tailwind-build.mjs              source check
 *   node scripts/test-single-tailwind-build.mjs <.next dir>  also check the built CSS
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL("..", import.meta.url));

function cssFiles(dir) {
  return fs.readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const file = path.join(dir, entry.name);
    return entry.isDirectory() ? cssFiles(file) : entry.name.endsWith(".css") ? [file] : [];
  });
}

export function tailwindImporters(files) {
  return files.filter((file) => /^\s*@import\s+["']tailwindcss["']/m.test(fs.readFileSync(file, "utf8")));
}

export function builtTailwindBuilds(files) {
  // A compiled Tailwind build carries the theme, base (preflight) and utilities layers.
  return files.filter((file) => {
    const css = fs.readFileSync(file, "utf8");
    return /@layer theme[,{]/.test(css) && /@layer base[,{]/.test(css) && /@layer utilities[,{]/.test(css);
  });
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const sourceImporters = tailwindImporters(cssFiles(path.join(root, "app")).concat(cssFiles(path.join(root, "components"))));
  assert.deepEqual(
    sourceImporters.map((file) => path.relative(root, file)),
    ["app/tailwind.css"],
    "only app/tailwind.css may import tailwindcss; other stylesheets use @reference",
  );
  const builtDir = process.argv[2];
  if (builtDir) {
    const built = builtTailwindBuilds(cssFiles(path.resolve(builtDir)));
    assert.equal(built.length, 1, `expected one Tailwind build in ${builtDir}, found ${built.length}: ${built.join(", ")}`);
    assert.ok(fs.readFileSync(built[0], "utf8").includes("md\\:flex"), "the Tailwind build must include the shell's md:flex utility");
  }
  console.log("single tailwind build: ok");
}
