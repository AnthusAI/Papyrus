#!/usr/bin/env node
/**
 * papyrus-infra synth --site infra/site.json [--out cdk.out] [--account A] [--region R]
 * papyrus-infra synth --account-stack github-oidc [--out cdk.out] [--account A] [--region R]
 * papyrus-infra print-buildspec --site infra/site.json --app cms-production|cms-staging|reader
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
  "       papyrus-infra synth --account-stack github-oidc [--out cdk.out] [--account A] [--region R]",
  "       papyrus-infra print-buildspec --site infra/site.json --app cms-production|cms-staging|reader",
  "       papyrus-infra deploy-edge --stack NAME --template FILE [--adoption-template FILE --adopt-resources FILE] [--parameter KEY=VALUE]... [--delete-function NAME] [--only-branch main] [--only-app-id ID] [--region R]",
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
if (command !== "synth" && command !== "print-buildspec" && command !== "deploy" && command !== "deploy-edge") {
  console.error(USAGE);
  process.exit(command ? 1 : 0);
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
try {
  ({ AmplifyAppShellStack } = await import("../infra/index.js"));
} catch (error) {
  console.error(`papyrus-infra: ${error instanceof Error ? error.message : error}`);
  process.exit(1);
}

const { App } = createRequire(path.join(process.cwd(), "noop.js"))("aws-cdk-lib");
const app = new App({ outdir: path.resolve(opt("out", "cdk.out")) });
new AmplifyAppShellStack(app, `AmplifyAppShell-${config.siteId}`, config, {
  env: resolveEnvironmentOrExit(),
  stackName: resolveStackName(config),
});
app.synth();
console.log(`synthesized ${resolveStackName(config)} -> ${path.resolve(opt("out", "cdk.out"))}`);
