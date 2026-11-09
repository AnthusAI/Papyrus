/**
 * Prospectus cost accounting: every Papyrus stack tags every costed resource (infra/amplify-app-shell/features/cost-tags.feature).
 *
 * Synthesizes every CDK stack (site backend, app shell, private chat, knowledge run, projection lease) and reads
 * every CloudFormation template under infra/, then runs the package's `checkCostTags` on each. The package's list
 * includes IAM roles: a site's usage queue accepts roles tagged anthus:app=papyrus and anthus:deployment=<site>
 * (AnthusAI/Prospectus#150). An untagged costed resource or role fails CI, naming it. A dedicated site's resources are tagged account "owner" (Prospectus finds
 * the owning Account from the papyrus-<site> entitlement); resources that serve every site are tagged "shared".
 */
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { createHash } from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { parse } from "yaml";
import { assertCostTags, checkCostTags } from "../amplify/vendor/anthus-cost-accounting/tags";
import { siteCostAttribution, usageQueueUrlFor } from "../amplify/cost-attribution";
import { parseSiteConfig } from "../infra/amplify-app-shell/lib/site-config";
import { KnowledgeRunStack } from "../infra/scheduled-jobs/lib/knowledge-pipeline";
import { resolveKnowledgeRunConfig } from "../infra/scheduled-jobs/lib/knowledge-run-config";
import { ProjectionLockStack } from "../infra/scheduled-jobs/lib/projection-lock-stack";

const repo = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const env = { account: "111122223333", region: "us-east-1" };
const examples = path.join(repo, "infra/amplify-app-shell/examples");

const assertNoViolations = (template: any, where = "") => assert.deepEqual(checkCostTags(template), [], where);

function tagsOf(template: any, logicalId: string): Record<string, unknown> {
  const tags = template.Resources[logicalId].Properties?.Tags ?? [];
  return Array.isArray(tags) ? Object.fromEntries(tags.map((tag: any) => [tag.Key, tag.Value])) : tags;
}

// Scenario: an untagged costed resource, or an untagged role, fails CI, naming it.
{
  const roleOnly = { Resources: { SenderRole: { Type: "AWS::IAM::Role", Properties: { Tags: [{ Key: "purpose", Value: "x" }] } } } };
  assert.deepEqual(checkCostTags(roleOnly), [{ logicalId: "SenderRole", type: "AWS::IAM::Role", missing: ["anthus:app", "anthus:account", "anthus:cost-key"] }]);
  const stack = new Stack(new App(), "Untagged");
  new dynamodb.Table(stack, "Ledger", { partitionKey: { name: "pk", type: dynamodb.AttributeType.STRING } });
  assert.throws(() => assertCostTags(Template.fromStack(stack).toJSON()), /Ledger[A-Z0-9]+ \(AWS::DynamoDB::Table\): anthus:app, anthus:account, anthus:cost-key/);
}

// Scenario: cost accounting is opt-in; on, the backend build needs its site ID and configures no Account.
{
  assert.equal(siteCostAttribution({}), null);
  assert.equal(siteCostAttribution({ PAPYRUS_SITE_ID: "dataparade" }), null, "a site ID alone does not opt in");
  for (const value of ["", "ON", "true", "1", "off", " on"]) assert.equal(siteCostAttribution({ PAPYRUS_COST_TAGS: value, PAPYRUS_SITE_ID: "dataparade" }), null, JSON.stringify(value));
  assert.throws(() => siteCostAttribution({ PAPYRUS_COST_TAGS: "on" }), /needs PAPYRUS_SITE_ID .*Refusing to synthesize an untagged backend/);
  assert.deepEqual(siteCostAttribution({ PAPYRUS_COST_TAGS: "on", PAPYRUS_SITE_ID: "dataparade" }), { account: "owner", app: "papyrus", deployment: "dataparade" });
}

// Scenario: a site that has not opted in synthesizes a backend with no cost tags and no usage environment.
{
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-cost-off-"));
  try {
    const environment = { ...process.env };
    delete environment.PAPYRUS_COST_TAGS;
    delete environment.PAPYRUS_SITE_ID;
    const run = spawnSync(process.execPath, ["--import", "tsx", path.join(repo, "scripts/synth-site-backend.mts"), out], { cwd: repo, encoding: "utf8", env: environment });
    assert.equal(run.status, 0, run.stderr || run.stdout);
    const templates = fs.readdirSync(out).filter((file) => file.endsWith(".template.json"));
    assert.ok(templates.length > 5, `expected the backend's nested stacks, got ${templates.join(", ")}`);
    for (const file of templates) {
      const text = fs.readFileSync(path.join(out, file), "utf8");
      assert.ok(!text.includes("anthus:"), `${file} has an anthus: tag`);
      assert.ok(!text.includes("SendUsageToOwnProspectusQueue"), `${file} grants usage sends`);
      for (const resource of Object.values<any>(JSON.parse(text).Resources ?? {})) {
        // Tags on a table are what made 5.99.0 update every table at once: a site that has not opted in has none.
        // (Amplify's own tags, such as amplify:app-id and created-by, are the pre-cost-accounting ones and stay.)
        if (resource.Type === "AWS::DynamoDB::Table") {
          const keys = (resource.Properties?.Tags ?? []).map((tag: any) => tag.Key);
          assert.deepEqual(keys.filter((key: string) => key.startsWith("anthus:")), [], `${file} has a table with an anthus: tag`);
        }
        const variables = resource.Properties?.Environment?.Variables ?? {};
        assert.equal(variables.PAPYRUS_SITE_ID, undefined, file);
        assert.equal(variables.PROSPECTUS_USAGE_QUEUE_URL, undefined, file);
      }
    }
  } finally {
    fs.rmSync(out, { recursive: true, force: true });
  }
}

// Scenario: each site's app shell and private chat stack are tagged with its site ID. The harness lives in the
// app-shell package so it synthesizes with that package's own aws-cdk-lib (same reason as test-infra-chat.ts).
{
  const harness = path.join(repo, "infra/amplify-app-shell/lib/cost-tags.test.ts");
  const result = spawnSync(process.execPath, ["--import", "tsx", harness], { stdio: "inherit" });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, "the app-shell cost tag harness failed");
}

// Scenario: the knowledge run is its site's; the projection lease table is shared.
{
  const site = parseSiteConfig(JSON.parse(fs.readFileSync(path.join(examples, "shipped.site.json"), "utf8")));
  const knowledge = Template.fromStack(new KnowledgeRunStack(new App(), "Knowledge", resolveKnowledgeRunConfig(site, process.env, examples), { env, imageTag: "test" })).toJSON();
  assertNoViolations(knowledge, "knowledge run");
  const machine = Object.keys(knowledge.Resources).find((id) => knowledge.Resources[id].Type === "AWS::StepFunctions::StateMachine")!;
  assert.equal(tagsOf(knowledge, machine)["anthus:cost-key"], "owner/papyrus/shipped");
  const lease = Template.fromStack(new ProjectionLockStack(new App(), "Lease", { env })).toJSON();
  assertNoViolations(lease, "projection lease");
  const table = Object.keys(lease.Resources).find((id) => lease.Resources[id].Type === "AWS::DynamoDB::Table")!;
  assert.equal(tagsOf(lease, table)["anthus:account"], "shared");
  assert.equal(tagsOf(lease, table)["anthus:cost-key"], "shared/papyrus/");
}

// Scenario: every stack of the site backend is tagged, and the model-calling functions may send only to their own queue.
{
  const out = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-cost-tags-"));
  try {
    const run = spawnSync(process.execPath, ["--import", "tsx", path.join(repo, "scripts/synth-site-backend.mts"), out], {
      cwd: repo,
      encoding: "utf8",
      env: { ...process.env, PAPYRUS_COST_TAGS: "on", PAPYRUS_SITE_ID: "dataparade" },
    });
    assert.equal(run.status, 0, run.stderr || run.stdout);
    const templates = fs.readdirSync(out).filter((file) => file.endsWith(".template.json"));
    assert.ok(templates.length > 5, `expected the backend's nested stacks, got ${templates.join(", ")}`);
    const senders: string[] = [];
    let sendStatements = 0;
    for (const file of templates) {
      const template = JSON.parse(fs.readFileSync(path.join(out, file), "utf8"));
      assertNoViolations(template, file);
      for (const [logicalId, resource] of Object.entries<any>(template.Resources ?? {})) {
        if (resource.Type === "AWS::Lambda::Function") {
          assert.equal(tagsOf(template, logicalId)["anthus:cost-key"], "owner/papyrus/dataparade", `${file} ${logicalId}`);
          const variables = resource.Properties.Environment?.Variables ?? {};
          if (variables.PROSPECTUS_USAGE_QUEUE_URL) {
            senders.push(logicalId);
            // Prospectus accepts the send because the function's own role carries the site's tags (AnthusAI/Prospectus#150).
            const roleId = resource.Properties.Role["Fn::GetAtt"][0];
            assert.equal(template.Resources[roleId].Type, "AWS::IAM::Role", `${file} ${logicalId} role`);
            assert.equal(tagsOf(template, roleId)["anthus:app"], "papyrus", `${file} ${roleId}`);
            assert.equal(tagsOf(template, roleId)["anthus:deployment"], "dataparade", `${file} ${roleId}`);
            assert.deepEqual(variables.PROSPECTUS_USAGE_QUEUE_URL, { "Fn::Join": ["", ["https://sqs.us-east-1.amazonaws.com/", { Ref: "AWS::AccountId" }, "/prospectus-usage-papyrus-dataparade"]] });
            assert.equal(variables.PAPYRUS_SITE_ID, "dataparade");
          }
        }
        if (resource.Type === "AWS::IAM::Policy") {
          for (const statement of resource.Properties.PolicyDocument.Statement) {
            if (statement.Sid !== "SendUsageToOwnProspectusQueue") continue;
            sendStatements += 1;
            assert.equal(statement.Action, "sqs:SendMessage");
            assert.deepEqual(statement.Resource, { "Fn::Join": ["", ["arn:", { Ref: "AWS::Partition" }, ":sqs:us-east-1:", { Ref: "AWS::AccountId" }, ":prospectus-usage-papyrus-dataparade"]] });
          }
        }
      }
    }
    assert.equal(senders.length, 2, `the editorial-checks and knowledge-query functions send usage; found ${senders.join(", ")}`);
    assert.equal(sendStatements, 2, "each sender's role may send to its own site's queue only");
  } finally {
    fs.rmSync(out, { recursive: true, force: true });
  }
}

// The queue URL is the package's format, with the stack's own account.
{
  const stack = new Stack(new App(), "Concrete", { env });
  assert.equal(usageQueueUrlFor(stack, "papyrus-dataparade"), "https://sqs.us-east-1.amazonaws.com/111122223333/prospectus-usage-papyrus-dataparade");
}

// Scenario: every CloudFormation template under infra/ tags its costed resources.
// Anth.us's edge templates are left as they are: Anth.us is never touched without an explicit instruction.
{
  const NOT_PAPYRUS = new Set(["infra/edge/anth-us.yaml", "infra/edge/anth-us-s3.yaml"]);
  // The pipeline's deploy roles (its only resources, nothing costed) change only through their own reviewed approval
  // flow and never send usage, so their templates are not checked.
  const PIPELINE = "infra/pipeline/";
  const files = spawnSync("git", ["ls-files", "infra/*.yaml", "infra/**/*.yaml"], { cwd: repo, encoding: "utf8" }).stdout
    .split("\n").filter((file) => file && !file.includes("/node_modules/") && !NOT_PAPYRUS.has(file) && !file.startsWith(PIPELINE));
  let templates = 0;
  for (const file of [...new Set(files)]) {
    const document = parse(fs.readFileSync(path.join(repo, file), "utf8"), { logLevel: "silent" });
    if (!document?.Resources) continue;
    templates += 1;
    assertNoViolations(document, file);
  }
  assert.ok(templates >= 12, `expected the Papyrus CloudFormation templates, read ${templates}`);
}

// The vendored package is the one recorded in vendor/README.md (sha256 of the packed tarball).
{
  const readme = fs.readFileSync(path.join(repo, "vendor/README.md"), "utf8");
  const tarball = fs.readFileSync(path.join(repo, "vendor/anthus-cost-accounting-0.1.0.tgz"));
  assert.ok(readme.includes(createHash("sha256").update(tarball).digest("hex")), "vendor/README.md records the tarball's sha256");
  const amplifyTags = fs.readFileSync(path.join(repo, "amplify/vendor/anthus-cost-accounting/tags.ts"), "utf8");
  const shellTags = fs.readFileSync(path.join(repo, "infra/amplify-app-shell/lib/cost-accounting-tags.ts"), "utf8");
  assert.equal(shellTags, amplifyTags, "the two vendored copies of tags.ts are identical");
  const amplifyCdk = fs.readFileSync(path.join(repo, "amplify/vendor/anthus-cost-accounting/cdk.ts"), "utf8");
  const shellCdk = fs.readFileSync(path.join(repo, "infra/amplify-app-shell/lib/cost-accounting-cdk.ts"), "utf8");
  assert.equal(shellCdk.replaceAll("./cost-accounting-tags", "./tags"), amplifyCdk, "the two vendored copies of cdk.ts differ only in the import path");
}

console.log("cost tag tests passed");
