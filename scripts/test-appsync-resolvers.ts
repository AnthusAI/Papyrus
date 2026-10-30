/**
 * Every AppSync JavaScript resolver passes AppSync's own lint rules before it ships. The APPSYNC_JS runtime refuses
 * code that plain JavaScript accepts (a classic for loop, ++, and more), and a refusal only shows up when a site deploys:
 * 5.60.0's postMessage used a for loop, and every site's backend rolled back. This runs the rules AppSync applies.
 */
import assert from "node:assert/strict";
import { readdirSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import appsync from "@aws-appsync/eslint-plugin";
import { ESLint } from "eslint";

const root = join(import.meta.dirname, "..");
const resolverDirectory = join(root, "amplify/data/resolvers");
const lint = (overrideConfig: object[]) => new ESLint({ cwd: root, overrideConfigFile: true, overrideConfig });
const rules = [{ ...appsync.configs.base, files: ["**/*.js"], languageOptions: { ecmaVersion: 2022, sourceType: "module" } }];

test("every AppSync resolver passes the APPSYNC_JS runtime's lint rules", async () => {
  const files = readdirSync(resolverDirectory).filter((name) => name.endsWith(".js"));
  assert.ok(files.length >= 5, "the message resolvers are all checked");
  for (const result of await lint(rules).lintFiles(files.map((name) => join(resolverDirectory, name)))) {
    assert.equal(result.errorCount, 0, `${result.filePath}: ${result.messages.map((message) => `${message.line}:${message.column} ${message.ruleId}`).join(", ")}`);
  }
});

test("the rules catch what the runtime refuses", async () => {
  const [result] = await lint(rules).lintText("export function request(ctx) { for (let i = 0; i < 2; i++) {} return {}; }", { filePath: join(resolverDirectory, "probe.js") });
  const found = result.messages.map((message) => message.ruleId);
  assert.ok(found.includes("@aws-appsync/no-for") && found.includes("@aws-appsync/no-disallowed-unary-operators"), found.join(", "));
});
