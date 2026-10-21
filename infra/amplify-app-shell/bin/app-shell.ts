#!/usr/bin/env node
import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { AmplifyAppShellStack } from "../lib/amplify-app-shell";
import { parseSiteConfig, resolveDeployEnvironment, resolveStackName } from "../lib/site-config";

const app = new cdk.App();

const sitePath = (app.node.tryGetContext("site") as string | undefined)?.trim();
if (!sitePath) {
  throw new Error("Pass the site config path: cdk synth -c site=<path-to-site.json>");
}
const config = parseSiteConfig(JSON.parse(fs.readFileSync(path.resolve(sitePath), "utf8")));

// The account and region come from the site's own infra/site.json (`aws` block); there is no default.
const env = resolveDeployEnvironment(config);

new AmplifyAppShellStack(app, `AmplifyAppShell-${config.siteId}`, config, {
  env,
  stackName: resolveStackName(config),
  description: `Amplify app shell for ${config.siteId} (Papyrus CMS and reader). Backend deploys via ampx pipeline-deploy.`,
});

app.synth();
