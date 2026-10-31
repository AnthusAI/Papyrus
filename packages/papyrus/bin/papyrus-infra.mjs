#!/usr/bin/env node
/**
 * papyrus-infra synth --site infra/site.json [--out cdk.out] [--account A] [--region R]
 * papyrus-infra synth --account-stack github-oidc [--out cdk.out] [--account A] [--region R]
 * papyrus-infra print-buildspec --site infra/site.json --app cms-production|cms-staging|reader
 * papyrus-infra synth --site infra/site.json --part chat [--chat-lambdas DIR] [--out cdk.out]   (the private chat data stack)
 * papyrus-infra cost amplify [--months 3] [--through YYYY-MM] [--no-apps] [--plan-budget]   (read-only: Cost Explorer for AWS Amplify by usage type and account, per-app build minutes, a budget threshold learned from history; --plan-budget prints, and never runs, the budget commands)
 * papyrus-infra amplify job-log --app-id ID [--branch main] [--job ID | --latest-failed] [--region R]   (read-only: a job's step statuses, log tail, first error and stack failures)
 * papyrus-infra deploy --site infra/site.json [--only-branch main] [--only-app-id ID] [--out cdk.out] [--account A] [--region R]
 * Synthesizes the app-shell stack for a publication from its own site.json,
 * prints one of the generated Amplify build specs, or deploys the stack from
 * inside the Amplify build of the one branch that owns it.
 */
import fs from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { createRequire } from "node:module";
import { resolveCdkEnvironment } from "../src/cdk-environment.mjs";

const USAGE = [
  "Usage: papyrus-infra synth --site infra/site.json [--out cdk.out] [--account A] [--region R]",
  "       papyrus-infra synth --site infra/site.json --part chat [--chat-lambdas DIR] [--out cdk.out] [--account A] [--region R]",
  "       papyrus-infra synth --account-stack github-oidc [--out cdk.out] [--account A] [--region R]",
  "       papyrus-infra print-buildspec --site infra/site.json --app cms-production|cms-staging|reader",
  "       papyrus-infra deploy-edge --stack NAME --template FILE [--adoption-template FILE --adopt-resources FILE] [--parameter KEY=VALUE]... [--delete-function NAME] [--only-branch main] [--only-app-id ID] [--region R]",
  "       papyrus-infra cost amplify [--months 3] [--through YYYY-MM] [--no-apps] [--plan-budget] [--region R]",
  "       papyrus-infra amplify job-log --app-id ID [--branch main] [--job ID | --latest-failed] [--region R]",
  "       papyrus-infra compile-edge-function --static-dir web [--out FILE]",
  "       papyrus-infra deploy --site infra/site.json [--only-branch main] [--only-app-id ID] [--out cdk.out] [--account A] [--region R]",
].join("\n");

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};
const resolveEnvironmentOrExit = () => {
  try {
    return resolveCdkEnvironment({ explicitAccount: opt("account"), explicitRegion: opt("region") });
  } catch (error) {
    console.error(`papyrus-infra: ${error instanceof Error ? error.message : error}`);
    process.exit(1);
  }
};
const command = args[0];
if (command !== "synth" && command !== "print-buildspec" && command !== "deploy" && command !== "deploy-edge" && command !== "compile-edge-function" && command !== "cost" && command !== "amplify") {
  console.error(USAGE);
  process.exit(command ? 1 : 0);
}

if (command === "cost") {
  if (args[1] !== "amplify") {
    console.error(USAGE);
    process.exit(1);
  }
  try {
    const { runAmplifyCostCommand } = await import("../src/amplify-cost-check.mjs");
    runAmplifyCostCommand(opt, (name) => args.includes(`--${name}`));
  } catch (error) {
    console.error(`papyrus-infra cost amplify: ${error instanceof Error ? error.message : error}`);
    process.exit(1);
  }
  process.exit(0);
}

if (command === "amplify") {
  if (args[1] !== "job-log") {
    console.error(USAGE);
    process.exit(1);
  }
  try {
    const { runAmplifyJobLogCommand } = await import("../src/amplify-job-log.mjs");
    await runAmplifyJobLogCommand(opt, (name) => args.includes(`--${name}`));
  } catch (error) {
    console.error(`papyrus-infra amplify job-log: ${error instanceof Error ? error.message : error}`);
    process.exit(1);
  }
  process.exit(0);
}

if (command === "compile-edge-function") {
  // The viewer-request CloudFront Function with the site's projection.json rules compiled in: for an edge stack that is
  // not deployed by the CMS backend, so that no site writes its own redirect function.
  const staticDir = opt("static-dir");
  if (!staticDir) {
    console.error(USAGE);
    process.exit(1);
  }
  const { compileRedirectFunctionSource, readEdgeConfig } = await import("../amplify/publication/redirect-rules.js");
  const functionSource = fs.readFileSync(new URL("../amplify/publication/redirect-and-index.js", import.meta.url), "utf8");
  const config = readEdgeConfig(staticDir);
  const compiled = compileRedirectFunctionSource(functionSource, config.rules, { negotiateMarkdown: config.negotiateMarkdown, directoryTwins: config.directoryTwins });
  const out = opt("out");
  if (out) fs.writeFileSync(path.resolve(out), compiled);
  else process.stdout.write(compiled);
  process.exit(0);
}

if (command === "deploy-edge") {
  const buildAppId = process.env.AWS_APP_ID;
  const buildBranch = process.env.AWS_BRANCH;
  const owningAppId = opt("only-app-id");
  if (!buildAppId || !buildBranch) {
    console.log("papyrus-infra deploy-edge: not running inside an Amplify build, skipping");
    process.exit(0);
  }
  if (buildBranch !== opt("only-branch", "main") || (owningAppId && buildAppId !== owningAppId)) {
    console.log(`papyrus-infra deploy-edge: ${buildAppId}/${buildBranch} does not own the stack, skipping`);
    process.exit(0);
  }
  const parameterValues = {};
  args.forEach((argument, index) => {
    if (argument !== "--parameter") return;
    const [name, ...valueParts] = args[index + 1].split("=");
    parameterValues[name] = valueParts.join("=");
  });
  const adoptResourcesFile = opt("adopt-resources");
  try {
    const { deployEdgeStack } = await import("../src/edge-stack-deploy.mjs");
    deployEdgeStack({
      stackName: opt("stack"),
      region: opt("region", process.env.AWS_REGION ?? "us-east-1"),
      templateFile: opt("template"),
      parameterValues,
      adoptionTemplateFile: opt("adoption-template"),
      adoptionResources: adoptResourcesFile ? JSON.parse(fs.readFileSync(adoptResourcesFile, "utf8")) : [],
      orphanedFunctionName: opt("delete-function"),
    });
  } catch (error) {
    console.error(`papyrus-infra deploy-edge: ${error instanceof Error ? error.message : error}`);
    process.exit(1);
  }
  process.exit(0);
}

const accountStack = opt("account-stack");
if (accountStack !== undefined) {
  if (command !== "synth" || accountStack !== "github-oidc") {
    console.error(USAGE);
    process.exit(1);
  }
  let GithubOidcProviderStack;
  try {
    ({ GithubOidcProviderStack } = await import("../infra/index.js"));
  } catch (error) {
    console.error(`papyrus-infra: ${error instanceof Error ? error.message : error}`);
    process.exit(1);
  }
  const { App } = createRequire(path.join(process.cwd(), "noop.js"))("aws-cdk-lib");
  const app = new App({ outdir: path.resolve(opt("out", "cdk.out")) });
  new GithubOidcProviderStack(app, "GithubOidcProviderStack", {
    env: resolveEnvironmentOrExit(),
    stackName: "github-oidc-provider",
  });
  app.synth();
  console.log(`synthesized github-oidc-provider -> ${path.resolve(opt("out", "cdk.out"))}`);
  process.exit(0);
}

const { buildSpecFor } = await import("../infra/build-specs.js");
const { parseSiteConfig, resolveStackName } = await import("../infra/site-config.js");
let config;
try {
  config = parseSiteConfig(JSON.parse(fs.readFileSync(path.resolve(opt("site", "infra/site.json")), "utf8")));
} catch (error) {
  console.error(`papyrus-infra: ${error instanceof Error ? error.message : error}`);
  process.exit(1);
}

if (command === "print-buildspec") {
  const app = opt("app");
  if (!["cms-production", "cms-staging", "reader"].includes(app)) {
    console.error(USAGE);
    process.exit(1);
  }
  try {
    process.stdout.write(buildSpecFor(config, app));
  } catch (error) {
    console.error(`papyrus-infra: ${error instanceof Error ? error.message : error}`);
    process.exit(1);
  }
  process.exit(0);
}

if (command === "deploy") {
  const buildAppId = process.env.AWS_APP_ID;
  const buildBranch = process.env.AWS_BRANCH;
  const owningBranch = opt("only-branch", "main");
  const owningAppId = opt("only-app-id");
  if (!buildAppId || !buildBranch) {
    console.log("papyrus-infra deploy: not running inside an Amplify build, skipping");
    process.exit(0);
  }
  if (buildBranch !== owningBranch || (owningAppId && buildAppId !== owningAppId)) {
    console.log(`papyrus-infra deploy: ${buildAppId}/${buildBranch} does not own the stack, skipping`);
    process.exit(0);
  }
  const outputDirectory = path.resolve(opt("out", process.env.CDK_OUTDIR ?? "cdk.out"));
  const explicitAccount = opt("account");
  const explicitRegion = opt("region");
  const synthesis = spawnSync(
    process.execPath,
    [
      path.resolve(process.argv[1]),
      "synth",
      "--site",
      path.resolve(opt("site", "infra/site.json")),
      "--out",
      outputDirectory,
      ...(explicitAccount ? ["--account", explicitAccount] : []),
      ...(explicitRegion ? ["--region", explicitRegion] : []),
    ],
    { stdio: "inherit" },
  );
  if (synthesis.status !== 0) process.exit(synthesis.status ?? 1);
  const deployment = spawnSync(
    "npx",
    ["--yes", "aws-cdk@2", "deploy", "--app", outputDirectory, "--require-approval", "never", `AmplifyAppShell-${config.siteId}`],
    { stdio: "inherit" },
  );
  process.exit(deployment.status ?? 1);
}

let AmplifyAppShellStack;
let PapyrusChatStack;
try {
  ({ AmplifyAppShellStack, PapyrusChatStack } = await import("../infra/index.js"));
} catch (error) {
  console.error(`papyrus-infra: ${error instanceof Error ? error.message : error}`);
  process.exit(1);
}

const { App } = createRequire(path.join(process.cwd(), "noop.js"))("aws-cdk-lib");
const app = new App({ outdir: path.resolve(opt("out", "cdk.out")) });
if (opt("part", "shell") === "chat") {
  // The site's private newsroom chat data stack (docs/private-newsroom-chat-per-site.md); deployed before the app shell enables chat.
  if (!config.chat?.enabled) {
    console.error(`papyrus-infra: site ${config.siteId} has no enabled chat block`);
    process.exit(1);
  }
  const lambdaAssetDirectory = opt("chat-lambdas");
  const chatStack = new PapyrusChatStack(app, {
    config,
    env: resolveEnvironmentOrExit(),
    lambdaAssetDirectory: lambdaAssetDirectory ? path.resolve(lambdaAssetDirectory) : undefined,
    description: `Private Papyrus newsroom chat data plane for ${config.siteId}.`,
  });
  app.synth();
  console.log(`synthesized ${chatStack.stackName} -> ${path.resolve(opt("out", "cdk.out"))}`);
  process.exit(0);
}
new AmplifyAppShellStack(app, `AmplifyAppShell-${config.siteId}`, config, {
  env: resolveEnvironmentOrExit(),
  stackName: resolveStackName(config),
});
app.synth();
console.log(`synthesized ${resolveStackName(config)} -> ${path.resolve(opt("out", "cdk.out"))}`);
