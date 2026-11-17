import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { cmsProductionBuildSpec, cmsStagingBuildSpec } from "./build-specs";
import { parseSiteConfig } from "./site-config";

// Executes infra/amplify-app-shell/features/agent-sync.feature (run through scripts/test-infra-agent-sync.ts).
const examples = path.resolve(__dirname, "../examples");
const backendCommands = (spec: string): string[] => {
  const lines = spec.split("\n");
  const start = lines.indexOf("    build:") + 2;
  return lines.slice(start, lines.indexOf("frontend:")).map((line) => line.trim().replace(/^- /, "").replace(/^'(.*)'$/, "$1"));
};
const siteNames = fs.readdirSync(examples).filter((name) => name.endsWith(".site.json")).map((name) => name.replace(/\.site\.json$/, ""));

for (const name of siteNames) {
  const config = parseSiteConfig(JSON.parse(fs.readFileSync(path.join(examples, `${name}.site.json`), "utf8")));
  if (!config.cms) continue;
  const commands = backendCommands(cmsProductionBuildSpec(config));
  const procedures = commands.findIndex((line) => line.includes("papyrus procedures seed-required"));
  const agents = commands.findIndex((line) => line.includes("papyrus agents apply"));
  assert.ok(procedures >= 0 && agents === procedures + 1, `${name}: the agent definitions are applied right after the procedures are registered`);
  assert.equal(commands[agents], 'PAPYRUS_ROOT="$PWD" PAPYRUS_GRAPHQL_AUTH=iam papyrus agents apply', `${name}: build role, operator lane, the site's checkout`);
  assert.ok(!commands[agents].includes("||"), `${name}: a failing step fails the build`);
  assert.ok(!/dry-run|--check/.test(commands[agents]), `${name}: the build applies`);
  const alexa = commands.findIndex((line) => line.includes("alexa-sync"));
  assert.ok(alexa > agents, `${name}: the Alexa sync, which may fail quietly, stays last`);
  assert.ok(!cmsStagingBuildSpec(config).includes("papyrus agents apply"), `${name}: the staging build does not apply agent definitions`);
}
