#!/usr/bin/env node
import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { AmplifyAppShellStack } from "../lib/amplify-app-shell";
import { parseSiteConfig, resolveStackName } from "../lib/site-config";

const app = new cdk.App();

const sitePath = (app.node.tryGetContext("site") as string | undefined)?.trim();
if (!sitePath) {
  throw new Error("Pass the site config path: cdk synth -c site=<path-to-site.json>");
}
const config = parseSiteConfig(JSON.parse(fs.readFileSync(path.resolve(sitePath), "utf8")));

const env = process.env.CDK_DEFAULT_ENV
  ? { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION }
  : { account: "335163751677", region: "us-east-1" };

new AmplifyAppShellStack(app, `AmplifyAppShell-${config.siteId}`, config, {
  env,
  stackName: resolveStackName(config),
  description: `Amplify app shell for ${config.siteId} (Papyrus CMS and reader). Backend deploys via ampx pipeline-deploy.`,
});

app.synth();
