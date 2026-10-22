#!/usr/bin/env node
import * as fs from "node:fs";
import * as path from "node:path";
import * as cdk from "aws-cdk-lib";
import { parseSiteConfig, resolveDeployEnvironment } from "../../amplify-app-shell/lib/site-config";
import { KnowledgeRunStack } from "../lib/knowledge-pipeline";
import { resolveKnowledgeRunConfig } from "../lib/knowledge-run-config";
import { ProjectionLockStack } from "../lib/projection-lock-stack";

const app = new cdk.App();

const sitePath = (app.node.tryGetContext("site") as string | undefined)?.trim();
if (!sitePath) {
  throw new Error("Pass the site config path: cdk synth -c site=<path-to-site.json> -c imageTag=<tag>");
}
const site = parseSiteConfig(JSON.parse(fs.readFileSync(path.resolve(sitePath), "utf8")));
const env = resolveDeployEnvironment(site);
const config = resolveKnowledgeRunConfig(site);

// Synth works without an image tag so tests and `cdk diff` of everything but the image run; deploy with a real one.
const imageTag = (app.node.tryGetContext("imageTag") as string | undefined)?.trim() || "placeholder";

new ProjectionLockStack(app, "ProjectionLock", { env, description: "Shared Papyrus projection lease table (one per account)" });
new KnowledgeRunStack(app, `KnowledgeRun-${config.publication}`, config, {
  env,
  imageTag,
  description: `Scheduled cloud knowledge run for ${config.publication} (Step Functions, Fargate, alarms)`,
});

app.synth();
