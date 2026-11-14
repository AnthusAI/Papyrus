import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { App } from "aws-cdk-lib";
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { cmsProductionBuildSpec, readerBuildSpec } from "./build-specs";
import { parseSiteConfig, resolveStackName } from "./site-config";

// Executes infra/amplify-app-shell/features/ci-receipt-gate.feature (run through scripts/test-infra-ci-gate.ts).
const examples = path.resolve(__dirname, "../examples");
const example = (name: string, change: (config: any) => void = () => {}): any => {
  const config = JSON.parse(fs.readFileSync(path.join(examples, `${name}.site.json`), "utf8"));
  change(config);
  return config;
};
const siteNames = fs.readdirSync(examples).filter((name) => name.endsWith(".site.json")).map((name) => name.replace(/\.site\.json$/, ""));
const privateSite = (change: (config: any) => void = () => {}, base = "dataparade"): any =>
  example(base, (config) => {
    config.autoDeploy = false;
    config.ci = { gate: "leftblock-receipt" };
    change(config);
  });
const resourcesOf = (template: any, type: string): any[] => Object.values<any>(template.Resources).filter((resource) => resource.Type === type);
function shellTemplate(raw: unknown): any {
  const config = parseSiteConfig(raw);
  const stack = new AmplifyAppShellStack(new App(), "Shell", config, { env: { account: "712236451410", region: "us-east-1" }, stackName: resolveStackName(config) });
  return JSON.parse(JSON.stringify((App.of(stack) as App).synth().getStackByName(stack.stackName).template));
}
const backendCommands = (spec: string): string[] => {
  const lines = spec.split("\n");
  const start = lines.indexOf("    build:") + 2;
  return lines.slice(start, lines.indexOf("frontend:")).map((line) => line.trim());
};
const unquote = (line: string): string => {
  const item = line.replace(/^- /, "");
  return item.startsWith("'") ? item.slice(1, -1).replace(/''/g, "'") : item;
};

function runGate(commands: string[], options: { status: string; withJq: boolean; commitId?: string }): { code: number | null; output: string } {
  const directory = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-ci-gate-"));
  const bin = path.join(directory, "bin");
  fs.mkdirSync(bin);
  fs.writeFileSync(path.join(directory, "status.json"), options.status);
  fs.writeFileSync(path.join(bin, "aws"), "#!/bin/sh\necho fake-token\n", { mode: 0o755 });
  fs.writeFileSync(path.join(bin, "curl"), `#!/bin/sh\ncat "${directory}/status.json"\n`, { mode: 0o755 });
  if (options.withJq) {
    const real = spawnSync("sh", ["-c", "command -v jq"], { encoding: "utf8" }).stdout.trim();
    assert.ok(real, "jq must be installed to test the jq branch");
    fs.symlinkSync(real, path.join(bin, "jq"));
  }
  const script = [`PATH="${bin}:/usr/bin:/bin"`, ...(options.commitId === undefined ? [] : [`AWS_COMMIT_ID=${options.commitId}`]), ...commands, "echo gate-passed"].join("\n");
  const result = spawnSync("/bin/sh", ["-c", script], { encoding: "utf8" });
  return { code: result.status, output: `${result.stdout}${result.stderr}` };
}
const statusBody = (state: string) => JSON.stringify({
  state: "failure",
  statuses: [
    { url: "u", state: "success", description: "d", target_url: null, context: "other/check" },
    { url: "u", state, description: "d", target_url: null, context: "leftblock/ci" },
  ],
});

// Scenario: a site without ci keeps today's build specs and synthesizes no gate resources
for (const name of siteNames) {
  const template = shellTemplate(example(name));
  const text = JSON.stringify(template);
  assert.ok(!text.includes("github-status-token"), `${name} must not get the status token parameter`);
  assert.ok(!text.includes("api.github.com"), `${name} must not get the gate in a build spec`);
}
{
  const config = parseSiteConfig(example("dataparade"));
  assert.equal(config.ci, undefined);
  assert.equal(backendCommands(cmsProductionBuildSpec(config))[0], "- npm ci --cache .npm --prefer-offline");
}

// Scenario: a private site with the receipt gate verifies the status before npm ci
{
  const config = parseSiteConfig(privateSite());
  assert.deepEqual(config.ci, { gate: "leftblock-receipt", statusContext: "leftblock/ci", requireSignature: false });
  const commands = backendCommands(cmsProductionBuildSpec(config));
  const install = commands.findIndex((line) => line.startsWith("- npm ci"));
  const gateRead = commands.findIndex((line) => line.includes("api.github.com/repos/AnthusAI/DataParade-newsroom/commits/$AWS_COMMIT_ID/status"));
  assert.ok(gateRead >= 0 && gateRead < install, "the status read comes before npm ci");
  assert.ok(commands[0].includes("AWS_COMMIT_ID"), "the gate is the first backend command");
  assert.ok(commands.some((line) => line.includes("ssm get-parameter --name /papyrus/dataparade/github-status-token --with-decryption")));
  assert.ok(commands.some((line) => line.includes("No LeftBlock CI receipt for $AWS_COMMIT_ID")));
  const template = shellTemplate(privateSite());
  const parameters = resourcesOf(template, "Custom::SecureStringParameter").filter((resource) => resource.Properties.ParameterName === "/papyrus/dataparade/github-status-token");
  assert.equal(parameters.length, 1);
  const serviceRole = resourcesOf(template, "AWS::IAM::Role").find((role) => /Backend deploy and staging build service role/.test(role.Properties.Description));
  assert.ok(serviceRole, "the CMS service role exists");
  const policies = resourcesOf(template, "AWS::IAM::Policy");
  const statement = policies.flatMap((policy) => policy.Properties.PolicyDocument.Statement).find((entry: any) => entry.Sid === "ReadGithubStatusToken");
  assert.deepEqual(statement.Action, "ssm:GetParameter");
  const gatedApps = resourcesOf(template, "AWS::Amplify::App").filter((app) => app.Properties.BuildSpec.includes("api.github.com"));
  assert.equal(gatedApps.length, 1);
}

// Scenario: a reader app of a private site also stops before its first install, sharing the one token parameter
{
  const raw = privateSite(() => {}, "pilobol-us");
  const config = parseSiteConfig(raw);
  const spec = readerBuildSpec(config);
  assert.ok(spec.indexOf("api.github.com") >= 0 && spec.indexOf("api.github.com") < spec.indexOf("curl -LsSf https://astral.sh/uv/install.sh"));
  const template = shellTemplate(raw);
  assert.equal(resourcesOf(template, "Custom::SecureStringParameter").filter((resource) => resource.Properties.ParameterName.endsWith("github-status-token")).length, 1);
  const grants = resourcesOf(template, "AWS::IAM::Policy").flatMap((policy) => policy.Properties.PolicyDocument.Statement).filter((entry: any) => entry.Sid === "ReadGithubStatusToken");
  assert.equal(grants.length, 2);
}

// Scenario: the generated gate stops without a success status and passes with one
{
  const commands = backendCommands(cmsProductionBuildSpec(parseSiteConfig(privateSite()))).filter((line) => !line.startsWith("- npm ci") && !line.includes("ampx") && !line.includes("PAPYRUS_CONSOLE") && !line.includes("alexa")).map(unquote);
  for (const withJq of [true, false]) {
    const branch = withJq ? "with jq" : "without jq";
    const missing = runGate(commands, { status: JSON.stringify({ state: "success", statuses: [{ state: "success", context: "other/check" }] }), withJq, commitId: "abc123" });
    assert.equal(missing.code, 1, `no receipt fails ${branch}`);
    assert.match(missing.output, /No LeftBlock CI receipt for abc123: run `leftblock ci` and push again/);
    assert.ok(!missing.output.includes("gate-passed"));
    const failing = runGate(commands, { status: statusBody("failure"), withJq, commitId: "abc123" });
    assert.equal(failing.code, 1, `a failure receipt fails ${branch}`);
    const unreachable = runGate(commands, { status: "", withJq, commitId: "abc123" });
    assert.equal(unreachable.code, 1, `an unreadable response fails ${branch}`);
    const noCommit = runGate(commands, { status: statusBody("success"), withJq });
    assert.equal(noCommit.code, 1, `a build without a commit id fails ${branch}`);
    const passing = runGate(commands, { status: statusBody("success"), withJq, commitId: "abc123" });
    assert.equal(passing.code, 0, `a success receipt passes ${branch}: ${passing.output}`);
    assert.match(passing.output, /gate-passed/);
  }
}

// Scenario: the gate configuration is validated against how the site deploys
{
  assert.throws(() => parseSiteConfig(example("dataparade", (config) => { config.ci = { gate: "leftblock-receipt" }; })), /ci\.gate must be "actions" when autoDeploy is true/);
  assert.throws(() => parseSiteConfig(example("dataparade", (config) => { config.autoDeploy = false; config.ci = { gate: "actions" }; })), /ci\.gate must be "leftblock-receipt" when autoDeploy is false/);
  assert.throws(() => parseSiteConfig(privateSite((config) => { config.ci.gate = "nope"; })), /ci\.gate must be/);
  assert.throws(() => parseSiteConfig(privateSite((config) => { config.ci.extra = 1; })), /ci/);
  assert.throws(() => parseSiteConfig(privateSite((config) => { config.ci.requireSignature = true; })), /requireSignature/);
  const custom = parseSiteConfig(privateSite((config) => { config.ci.statusContext = "ci/local"; }));
  assert.equal(custom.ci?.statusContext, "ci/local");
  const actions = parseSiteConfig(example("dataparade", (config) => { config.ci = { gate: "actions" }; }));
  assert.ok(!cmsProductionBuildSpec(actions).includes("api.github.com"));
}

console.log("ci receipt gate tests passed");
