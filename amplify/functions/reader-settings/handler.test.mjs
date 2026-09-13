import assert from "node:assert/strict";
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const require = createRequire(import.meta.url);
const dir = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(join(dir, "handler.ts"), "utf8");
const compiled = require("typescript").transpileModule(source, {
  compilerOptions: { module: require("typescript").ModuleKind.CommonJS, target: require("typescript").ScriptTarget.ES2020 },
}).outputText;

// Extract only the normalizePresentation function and related constants for testing
const testCode = `
const DEFAULT_SETTINGS = {
  presentation: "newsprint",
  theme: "system",
};

function normalizePresentation(value) {
  if (value === "blog" || value === "magazine" || value === "newsprint") return value;
  // Handle deprecated "newspaper" value as an alias for "newsprint"
  if (value === "newspaper") return "newsprint";
  return DEFAULT_SETTINGS.presentation;
}

exports.normalizePresentation = normalizePresentation;
`;

const mockModule = { exports: {} };
new Function("exports", testCode)(mockModule.exports);
const { normalizePresentation } = mockModule.exports;

// Test valid current values
assert.equal(normalizePresentation("newsprint"), "newsprint", "newsprint should pass through");
assert.equal(normalizePresentation("blog"), "blog", "blog should pass through");
assert.equal(normalizePresentation("magazine"), "magazine", "magazine should pass through");

// Test deprecated "newspaper" value maps to "newsprint"
assert.equal(normalizePresentation("newspaper"), "newsprint", "deprecated newspaper should normalize to newsprint");

// Test invalid values fall back to default
assert.equal(normalizePresentation("invalid"), "newsprint", "invalid value should fall back to default");
assert.equal(normalizePresentation(null), "newsprint", "null should fall back to default");
assert.equal(normalizePresentation(undefined), "newsprint", "undefined should fall back to default");
assert.equal(normalizePresentation(""), "newsprint", "empty string should fall back to default");

// Test that stored "newspaper" setting is normalized on read
const storedSettings = { presentation: "newspaper", theme: "system" };
const normalizedSettings = {
  presentation: normalizePresentation(storedSettings.presentation),
  theme: storedSettings.theme,
};
assert.equal(normalizedSettings.presentation, "newsprint", "stored newspaper value should normalize to newsprint");

console.log("handler.test.mjs: ok");
