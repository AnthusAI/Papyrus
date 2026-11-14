// Executes infra/amplify-app-shell/features/build-timeout.feature: the app shell sets Amplify's _BUILD_TIMEOUT from cms.buildTimeoutMinutes.
// Run by scripts/test-build-timeout.ts, which starts it inside the infrastructure package (one copy of aws-cdk-lib).
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { test } from "node:test";
import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { parse } from "yaml";
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { MAX_BUILD_TIMEOUT_MINUTES, parseSiteConfig } from "./site-config";

const repo = path.resolve(__dirname, "../../..");
const env = { account: "111122223333", region: "us-east-1" };
const example = (change: (config: any) => void = () => {}) => {
  const config = JSON.parse(fs.readFileSync(path.join(repo, "infra/amplify-app-shell/examples/shipped.site.json"), "utf8"));
  change(config);
  return config;
};
const synth = (config: unknown) => Template.fromStack(new AmplifyAppShellStack(new App(), "Shell", parseSiteConfig(config), { env })).toJSON();
const appVariables = (template: any) => {
  // The CMS app is the WEB_COMPUTE one; a split site also has a reader app, which runs no backend build.
  const apps = Object.values<any>(template.Resources).filter((resource) => resource.Type === "AWS::Amplify::App" && resource.Properties.Platform === "WEB_COMPUTE");
  assert.equal(apps.length, 1);
  return Object.fromEntries((apps[0].Properties.EnvironmentVariables ?? []).map((variable: any) => [variable.Name, variable.Value]));
};

test("the app shell sets the build timeout from the site config, on the app and on no branch", () => {
  const template = synth(example((c) => (c.cms.buildTimeoutMinutes = 90)));
  assert.equal(appVariables(template)._BUILD_TIMEOUT, "90");
  const branches = Object.values<any>(template.Resources).filter((resource) => resource.Type === "AWS::Amplify::Branch");
  assert.ok(branches.length > 0);
  for (const branch of branches) {
    assert.ok(!(branch.Properties.EnvironmentVariables ?? []).some((variable: any) => variable.Name === "_BUILD_TIMEOUT"), "a branch variable would override the app's");
  }
});

test("the timeout defaults to 120 and is the only variable added to the app", () => {
  const variables = appVariables(synth(example()));
  assert.equal(variables._BUILD_TIMEOUT, "120");
  assert.deepEqual(Object.keys(variables), ["_BUILD_TIMEOUT"]);
});

test("every example site gets _BUILD_TIMEOUT 120 unless it sets its own", () => {
  const dir = path.join(repo, "infra/amplify-app-shell/examples");
  for (const file of fs.readdirSync(dir).filter((name) => name.endsWith(".site.json"))) {
    const config = JSON.parse(fs.readFileSync(path.join(dir, file), "utf8"));
    if (!config.cms) continue;
    assert.equal(appVariables(synth(config))._BUILD_TIMEOUT, String(config.cms.buildTimeoutMinutes ?? 120), file);
  }
});

test("a value outside Amplify's range, or not a whole number, is refused naming the range", () => {
  for (const bad of [121, 4, 0, -5, 90.5, "90", null]) {
    assert.throws(() => parseSiteConfig(example((c) => (c.cms.buildTimeoutMinutes = bad))), /cms\.buildTimeoutMinutes must be a whole number of minutes from 5 to 120/, String(bad));
  }
  for (const good of [5, 30, 120]) assert.equal(parseSiteConfig(example((c) => (c.cms.buildTimeoutMinutes = good))).cms?.buildTimeoutMinutes, good);
});

test("the deploy workflow waits, and its job runs, longer than the longest build", () => {
  const workflow = parse(fs.readFileSync(path.join(repo, ".github/workflows/amplify-deploy.yml"), "utf8"));
  const wait = workflow.on.workflow_call.inputs["timeout-minutes"].default;
  assert.ok(wait > MAX_BUILD_TIMEOUT_MINUTES, `the wait is ${wait}`);
  // The job timeout is the wait plus a positive margin, so any wait a caller passes stays inside it: it is always above the build timeout too.
  const match = /^\$\{\{ inputs\.timeout-minutes \+ (\d+) \}\}$/.exec(workflow.jobs.deploy["timeout-minutes"]);
  assert.ok(match && Number(match[1]) > 0, `the job timeout is ${workflow.jobs.deploy["timeout-minutes"]}`);
  assert.ok(wait + Number(match![1]) > MAX_BUILD_TIMEOUT_MINUTES);
});
