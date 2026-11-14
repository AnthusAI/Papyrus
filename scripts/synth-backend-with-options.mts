/**
 * Synthesizes a backend (all stacks) into a directory without deploying or bundling, like synth-site-backend.mts, and also takes the second argument
 * of `defineSiteBackend` and writes the facts the templates cannot show. Used by features_backend/shared-stack-bootstrap.feature.
 *
 *   tsx scripts/synth-backend-with-options.mts <out-dir> <backend-json> [options-json]
 *
 * `backend-json` is the site's `backend` config (nothing is merged into it), for example the shared stack's `sharedStackBackendConfig("staging")`.
 * `options-json` is the second argument of `defineSiteBackend`, for example '{"dedicatedSharedStackDeny":false}'.
 * It writes `<out-dir>/synth-facts.json`, which is not a template, so a reader of the templates skips it.
 */
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";

const [, , outputDirectory, backendJson, optionsJson] = process.argv;
if (!outputDirectory || !backendJson) throw new Error("usage: synth-backend-with-options.mts <out-dir> <backend-json> [options-json]");

process.env.CDK_CONTEXT_JSON = JSON.stringify({
  "amplify-backend-namespace": "papyrussynth",
  "amplify-backend-name": "synth",
  "amplify-backend-type": "branch",
  "aws:cdk:bundling-stacks": [],
});
process.env.CDK_OUTDIR = path.resolve(outputDirectory);
process.env.AWS_BRANCH = "synth";
process.env.AWS_APP_ID = "synth-app";
process.env.CDK_DEFAULT_ACCOUNT = "123456789012";
process.env.CDK_DEFAULT_REGION = "us-east-1";
rmSync(process.env.CDK_OUTDIR, { recursive: true, force: true });
mkdirSync(process.env.CDK_OUTDIR, { recursive: true });

const { defineSiteBackend } = await import("../amplify/site-backend");
const backendConfig = JSON.parse(backendJson);
const backend = defineSiteBackend({ defaultBrand: backendConfig.brandId, backend: backendConfig }, optionsJson ? JSON.parse(optionsJson) : {});
(backend.auth.stack.node.root as { synth: () => unknown }).synth();

const { siteFilesForContentActionsBundle } = await import("../amplify/functions/content-actions/resource");
const { OPTIONAL_MODEL_GROUPS } = await import("../amplify/data/schema");
const { sharedStackDenyPolicyDocument } = await import("../amplify/shared-stack/names");
const { RESOURCES_THAT_CANNOT_TAKE_THE_KEY } = await import("../amplify/shared-stack/isolation");
writeFileSync(
  path.join(process.env.CDK_OUTDIR, "synth-facts.json"),
  JSON.stringify({
    contentActionsSiteFiles: siteFilesForContentActionsBundle() ?? null,
    optionalModelGroups: OPTIONAL_MODEL_GROUPS,
    denyPolicyDocument: sharedStackDenyPolicyDocument(),
    resourcesThatCannotTakeTheKey: RESOURCES_THAT_CANNOT_TAKE_THE_KEY,
  }),
);
console.log(`synthesized to ${process.env.CDK_OUTDIR}`);
