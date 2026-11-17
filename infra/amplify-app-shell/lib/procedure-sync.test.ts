import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { cmsProductionBuildSpec, cmsStagingBuildSpec, papyrusVersionToPep440 } from "./build-specs";
import { parseSiteConfig } from "./site-config";

// Executes infra/amplify-app-shell/features/procedure-sync.feature (run through scripts/test-infra-procedure-sync.ts).
const examples = path.resolve(__dirname, "../examples");
const example = (name: string, change: (config: any) => void = () => {}): any => {
  const config = JSON.parse(fs.readFileSync(path.join(examples, `${name}.site.json`), "utf8"));
  change(config);
  return config;
};
const backendCommands = (spec: string): string[] => {
  const lines = spec.split("\n");
  const start = lines.indexOf("    build:") + 2;
  return lines.slice(start, lines.indexOf("frontend:")).map((line) => line.trim().replace(/^- /, "").replace(/^'(.*)'$/, "$1"));
};
const siteNames = fs.readdirSync(examples).filter((name) => name.endsWith(".site.json")).map((name) => name.replace(/\.site\.json$/, ""));

// Scenario: The production build registers the procedures after the backend deploy
for (const name of siteNames) {
  const config = parseSiteConfig(example(name));
  if (!config.cms) continue;
  const commands = backendCommands(cmsProductionBuildSpec(config));
  const deploy = commands.indexOf("npx papyrus-infra backend-deploy");
  const sync = commands.findIndex((line) => line.includes("papyrus procedures seed-required"));
  assert.ok(deploy >= 0 && sync > deploy, `${name}: the registration comes after the backend deploy`);
  const install = commands.findIndex((line) => line.includes("uv pip install") && line.includes("papyrus-newsroom"));
  assert.ok(install > deploy && install < sync, `${name}: the pinned engine is installed before the command runs`);
  assert.ok(commands[install].includes(`==${papyrusVersionToPep440(config.papyrusVersion)}"`), `${name}: it installs the Papyrus version the site pins`);
  assert.equal(commands[sync], 'PAPYRUS_ROOT="$PWD" PAPYRUS_GRAPHQL_AUTH=iam papyrus procedures seed-required', `${name}: build role, operator lane, the site's checkout`);
  assert.ok(!commands[sync].includes("||"), `${name}: a failing registration fails the build`);
  assert.ok(!/dry-run|--check/.test(commands[sync]), `${name}: the build applies`);
  const alexa = commands.findIndex((line) => line.includes("alexa-sync"));
  assert.ok(alexa > sync, `${name}: the Alexa sync, which may fail quietly, stays last`);
}

// Scenario: The CI receipt gate still comes first and the staging build is unchanged
{
  const raw = example("dataparade", (config) => {
    config.autoDeploy = false;
    config.ci = { gate: "leftblock-receipt" };
  });
  const config = parseSiteConfig(raw);
  const commands = backendCommands(cmsProductionBuildSpec(config));
  assert.ok(commands[0].includes("AWS_COMMIT_ID"), "the gate is still the first backend command");
  assert.ok(commands.findIndex((line) => line.startsWith("npm ci")) < commands.findIndex((line) => line.includes("seed-required")));
  assert.ok(!cmsStagingBuildSpec(config).includes("seed-required"), "the staging build does not register procedures");
}
