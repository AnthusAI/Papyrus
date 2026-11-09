/**
 * Every site's app-shell and private chat stacks carry the Prospectus cost tags: account "owner", app papyrus and the
 * site ID (infra/amplify-app-shell/features/cost-tags.feature). Run by scripts/test-cost-tags.ts.
 */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { App } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AmplifyAppShellStack } from "./amplify-app-shell";
import { PapyrusChatStack } from "./chat-stack";
import { assertCostTags, COSTED_RESOURCE_TYPES } from "./cost-accounting-tags";
import { parseSiteConfig } from "./site-config";

const env = { account: "111122223333", region: "us-east-1" };
const examples = path.resolve(__dirname, "../examples");
const readSite = (name: string, costAccounting?: boolean) =>
  parseSiteConfig({ ...JSON.parse(fs.readFileSync(path.join(examples, `${name}.site.json`), "utf8")), ...(costAccounting === undefined ? {} : { costAccounting }) });
const branchVariables = (template: any) => {
  const branch = Object.values<any>(template.Resources).find((resource) => resource.Type === "AWS::Amplify::Branch" && resource.Properties.BranchName === "main");
  return branch ? Object.fromEntries(branch.Properties.EnvironmentVariables.map((variable: any) => [variable.Name, variable.Value])) : undefined;
};
const tagsOf = (resource: any): Record<string, unknown> =>
  Object.fromEntries((resource.Properties?.Tags ?? []).map((tag: any) => [tag.Key, tag.Value]));

const chatLambdas = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-cost-chat-"));
for (const file of ["run-worker.js", "probe-worker.js"]) fs.writeFileSync(path.join(chatLambdas, file), "exports.handler = async () => ({});\n");

const names = fs.readdirSync(examples).filter((file) => file.endsWith(".site.json")).map((file) => file.replace(".site.json", ""));
for (const name of names) {
  // A site that has not opted in (the default) gets no tags and no cost branch variables, so the deploy changes no resource.
  const defaultSite = readSite(name);
  assert.equal(defaultSite.costAccounting, false, name);
  const offTemplate = Template.fromStack(new AmplifyAppShellStack(new App(), `Off-${name}`, defaultSite, { env })).toJSON();
  assert.ok(!JSON.stringify(offTemplate).includes("anthus:"), `${name}: no anthus: tag without costAccounting`);
  const offVariables = branchVariables(offTemplate);
  if (offVariables) {
    assert.equal(offVariables.PAPYRUS_SITE_ID, undefined, name);
    assert.equal(offVariables.PAPYRUS_COST_TAGS, undefined, name);
  }
  if (defaultSite.chat?.enabled) {
    const offChat = Template.fromStack(new PapyrusChatStack(new App(), { config: defaultSite, env, lambdaAssetDirectory: chatLambdas })).toJSON();
    assert.ok(!JSON.stringify(offChat).includes("anthus:"), `${name}: no anthus: tag on the chat stack without costAccounting`);
  }

  const site = readSite(name, true);
  const template = Template.fromStack(new AmplifyAppShellStack(new App(), `Shell-${name}`, site, { env })).toJSON();
  assertCostTags(template);
  for (const [logicalId, resource] of Object.entries<any>(template.Resources)) {
    // The package's list includes IAM roles: a site's usage queue accepts roles tagged with its site (AnthusAI/Prospectus#150).
    if ((COSTED_RESOURCE_TYPES as readonly string[]).includes(resource.Type)) {
      assert.equal(tagsOf(resource)["anthus:cost-key"], `owner/papyrus/${site.siteId}`, `${name} ${logicalId}`);
      assert.equal(tagsOf(resource)["anthus:deployment"], site.siteId, `${name} ${logicalId}`);
      assert.equal(tagsOf(resource)["anthus:account"], "owner", `${name} ${logicalId}`);
    }
  }
  // The backend build reads its site ID from the production branch (amplify/cost-attribution.ts); no Account is configured.
  const branch = Object.values<any>(template.Resources).find((resource) => resource.Type === "AWS::Amplify::Branch" && resource.Properties.BranchName === "main");
  if (branch) {
    const variables = Object.fromEntries(branch.Properties.EnvironmentVariables.map((variable: any) => [variable.Name, variable.Value]));
    assert.equal(variables.PAPYRUS_COST_TAGS, "on", name);
    assert.equal(variables.PAPYRUS_SITE_ID, site.siteId, name);
    assert.equal(variables.PAPYRUS_COST_ACCOUNT, undefined, name);
  }
  if (site.chat?.enabled) {
    assertCostTags(Template.fromStack(new PapyrusChatStack(new App(), { config: site, env, lambdaAssetDirectory: chatLambdas })).toJSON());
  }
}
fs.rmSync(chatLambdas, { recursive: true, force: true });
console.log(`app-shell cost tags: ${names.length} sites tagged`);
