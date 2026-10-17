/**
 * Synthesizes a site's full Amplify backend (all stacks) into a directory without deploying or bundling,
 * so two configurations can be compared byte for byte.
 *
 *   tsx scripts/synth-site-backend.mts <out-dir> [backend-json]
 *
 * `backend-json` is merged into the site's `backend` config, for example '{"plugins":["signup"]}'.
 */
import { mkdirSync, rmSync } from "node:fs";
import path from "node:path";

const [, , outputDirectory, backendJson] = process.argv;
if (!outputDirectory) throw new Error("usage: synth-site-backend.mts <out-dir> [backend-json]");

process.env.CDK_CONTEXT_JSON = JSON.stringify({
  "amplify-backend-namespace": "papyrussynth",
  "amplify-backend-name": "synth",
  "amplify-backend-type": "branch",
  "aws:cdk:bundling-stacks": [],
});
process.env.CDK_OUTDIR = path.resolve(outputDirectory);
process.env.AWS_BRANCH = "synth";
process.env.AWS_APP_ID = "dsynthapp0001";
process.env.CDK_DEFAULT_ACCOUNT = "123456789012";
process.env.CDK_DEFAULT_REGION = "us-east-1";
rmSync(process.env.CDK_OUTDIR, { recursive: true, force: true });
mkdirSync(process.env.CDK_OUTDIR, { recursive: true });

const { defineSiteBackend } = await import("../amplify/site-backend");
const extraBackend = backendJson ? JSON.parse(backendJson) : {};
const backend = defineSiteBackend({ defaultBrand: extraBackend.brandId, backend: { productionAppId: "dbsyytcm9drqa", ...extraBackend } });
(backend.auth.stack.node.root as { synth: () => unknown }).synth();
console.log(`synthesized to ${process.env.CDK_OUTDIR}`);
