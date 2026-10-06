#!/usr/bin/env node
/**
 * papyrus-infra synth --site infra/site.json [--out cdk.out] [--account A] [--region R]
 * papyrus-infra synth --account-stack github-oidc [--out cdk.out] [--account A] [--region R]
 * papyrus-infra print-buildspec --site infra/site.json --app cms-production|cms-staging|reader
 * Synthesizes the app-shell stack for a publication from its own site.json, or
 * prints one of the generated Amplify build specs. Synth only: deploying is a
 * separate, reviewed step.
 */
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { buildSpecFor } from "../infra/build-specs.js";
import { parseSiteConfig } from "../infra/site-config.js";

const USAGE = [
  "Usage: papyrus-infra synth --site infra/site.json [--out cdk.out] [--account A] [--region R]",
  "       papyrus-infra synth --account-stack github-oidc [--out cdk.out] [--account A] [--region R]",
  "       papyrus-infra print-buildspec --site infra/site.json --app cms-production|cms-staging|reader",
].join("\n");

const args = process.argv.slice(2);
const opt = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 ? args[i + 1] : fallback;
};
const command = args[0];
if (command !== "synth" && command !== "print-buildspec") {
  console.error(USAGE);
  process.exit(command ? 1 : 0);
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
    env: { account: opt("account", "335163751677"), region: opt("region", "us-east-1") },
    stackName: "github-oidc-provider",
  });
  app.synth();
  console.log(`synthesized github-oidc-provider -> ${path.resolve(opt("out", "cdk.out"))}`);
  process.exit(0);
}

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
  env: { account: opt("account", "335163751677"), region: opt("region", "us-east-1") },
  stackName: `amplify-app-shell-${config.siteId}`,
});
app.synth();
console.log(`synthesized amplify-app-shell-${config.siteId} -> ${path.resolve(opt("out", "cdk.out"))}`);
