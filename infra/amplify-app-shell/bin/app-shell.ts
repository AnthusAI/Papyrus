#!/usr/bin/env node
import * as cdk from "aws-cdk-lib";
import { AmplifyAppShellStack } from "../lib/amplify-app-shell";
import { resolveSite } from "../sites/pilobol-us";

const app = new cdk.App();

const siteId = (app.node.tryGetContext("site") as string | undefined)?.trim();
const config = resolveSite(siteId);

const env = process.env.CDK_DEFAULT_ENV
  ? { account: process.env.CDK_DEFAULT_ACCOUNT, region: process.env.CDK_DEFAULT_REGION }
  : { account: "335163751677", region: "us-east-1" };

new AmplifyAppShellStack(app, `AmplifyAppShell-${config.siteId}`, config, {
  env,
  stackName: `amplify-app-shell-${config.siteId}`,
  description: `Amplify WEB_COMPUTE app shell for ${config.appName} (Papyrus CMS). Backend deploys via ampx pipeline-deploy.`,
});

app.synth();
