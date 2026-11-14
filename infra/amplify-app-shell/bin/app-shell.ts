#!/usr/bin/env node
import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { AmplifyAppShellStack } from "../lib/amplify-app-shell";
import { PapyrusChatStack } from "../lib/chat-stack";
import { parseSiteConfig, resolveDeployEnvironment, resolveStackName } from "../lib/site-config";

const app = new cdk.App();

const sitePath = (app.node.tryGetContext("site") as string | undefined)?.trim();
if (!sitePath) {
  throw new Error("Pass the site config path: cdk synth -c site=<path-to-site.json>");
}
const config = parseSiteConfig(JSON.parse(fs.readFileSync(path.resolve(sitePath), "utf8")));

// The account and region come from the site's own infra/site.json (`aws` block); there is no default.
const env = resolveDeployEnvironment(config);

// `-c part=chat` synthesizes the site's private chat data stack instead of the app shell. They are separate
// stacks deployed in order (docs/private-newsroom-chat-per-site.md): neither references the other directly.
const part = (app.node.tryGetContext("part") as string | undefined)?.trim() ?? "shell";
if (part === "chat") {
  if (!config.chat?.enabled) throw new Error(`site ${config.siteId} has no enabled chat block`);
  new PapyrusChatStack(app, {
    config,
    env,
    lambdaAssetDirectory: (app.node.tryGetContext("chatLambdas") as string | undefined)?.trim() || undefined,
    description: `Private Papyrus newsroom chat data plane for ${config.siteId}.`,
  });
} else if (part === "shell") {
  new AmplifyAppShellStack(app, `AmplifyAppShell-${config.siteId}`, config, {
    env,
    stackName: resolveStackName(config),
    description: `Amplify app shell for ${config.siteId} (Papyrus CMS and reader). Backend deploys via ampx pipeline-deploy.`,
  });
} else {
  throw new Error(`-c part must be "shell" or "chat", got ${JSON.stringify(part)}`);
}

app.synth();
