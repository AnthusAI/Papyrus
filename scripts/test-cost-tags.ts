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
import { costTagWave, planCostTagWaves, STACK_OPERATION_RESOURCE_LIMIT, WAVE_RESOURCE_BUDGET } from "../amplify/cost-tag-waves";
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

// Scenario: the backend tags itself only when backend-deploy asks for a wave, and takes its site ID from site.json.
{
  const noSite = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-no-site-"));
  const withSite = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-site-"));
  try {
    fs.mkdirSync(path.join(withSite, "infra"));
    fs.writeFileSync(path.join(withSite, "infra", "site.json"), JSON.stringify({ siteId: "dataparade" }));
    assert.equal(siteCostAttribution({}, withSite), null, "no wave, no cost accounting");
    assert.equal(siteCostAttribution({ PAPYRUS_SITE_ID: "dataparade" }, noSite), null, "a site ID alone does not tag");
    assert.equal(siteCostAttribution({ PAPYRUS_COST_TAGS: "on", PAPYRUS_SITE_ID: "dataparade" }, noSite), null, "the old switch does nothing");
    assert.deepEqual(siteCostAttribution({ PAPYRUS_COST_TAG_WAVE: "1" }, withSite), { account: "owner", app: "papyrus", deployment: "dataparade", wave: 1 });
    assert.deepEqual(siteCostAttribution({ PAPYRUS_COST_TAG_WAVE: "all", PAPYRUS_SITE_ID: "dataparade" }, withSite), { account: "owner", app: "papyrus", deployment: "dataparade", wave: Infinity });
    assert.deepEqual(siteCostAttribution({ PAPYRUS_COST_TAG_WAVE: "2", PAPYRUS_SITE_ID: "sandbox-site" }, noSite), { account: "owner", app: "papyrus", deployment: "sandbox-site", wave: 2 });
    assert.throws(() => siteCostAttribution({ PAPYRUS_COST_TAG_WAVE: "1", PAPYRUS_SITE_ID: "shipped" }, withSite), /PAPYRUS_SITE_ID is shipped but infra\/site.json says dataparade/);
    assert.throws(() => siteCostAttribution({ PAPYRUS_COST_TAG_WAVE: "1" }, noSite), /needs its site ID .*Refusing to synthesize an untagged backend/);
    for (const value of ["0", "on", "-1", "1.5", "ALL"]) assert.throws(() => costTagWave({ PAPYRUS_COST_TAG_WAVE: value }), /wave number from 1 or "all"/, value);
  } finally {
    fs.rmSync(noSite, { recursive: true, force: true });
    fs.rmSync(withSite, { recursive: true, force: true });
  }
}

// Scenario: no wave's operation goes over the budget, counting the parent stacks each wave updates.
{
  const units = [
    { id: "root", parentId: null, resources: 40 },
    { id: "root/data", parentId: "root", resources: 160 },
    ...Array.from({ length: 30 }, (_, i) => ({ id: `root/data/model${String(i).padStart(2, "0")}`, parentId: "root/data", resources: 90 })),
    { id: "root/function", parentId: "root", resources: 300, first: true },
  ];
  const plan = planCostTagWaves(units);
  assert.deepEqual(plan.waves.flat().sort(), units.map((unit) => unit.id).sort(), "every stack is in exactly one wave");
  assert.equal(plan.waves[0][0], "root/function", "the usage senders' stack goes first");
  for (const cost of plan.costs) assert.ok(cost <= WAVE_RESOURCE_BUDGET, `wave cost ${cost}`);
  // A later wave of models also pays for the data stack and the root above them: 40 + 160 + 90 per model.
  const last = plan.waves[plan.waves.length - 1];
  assert.ok(!last.includes("root") && !last.includes("root/data"));
  assert.equal(plan.costs[plan.costs.length - 1], 40 + 160 + 90 * last.length);
  assert.ok(plan.waves.length >= 2, `${plan.waves.length} waves`);
  // A stack bigger than the budget gets a wave of its own; one past CloudFormation's limit cannot be planned.
  const big = planCostTagWaves([{ id: "root", parentId: null, resources: 10 }, { id: "root/huge", parentId: "root", resources: 2000 }, { id: "root/small", parentId: "root", resources: 5 }]);
  assert.deepEqual(big.waves, [["root"], ["root/huge"], ["root/small"]]);
  assert.throws(() => planCostTagWaves([{ id: "root", parentId: null, resources: STACK_OPERATION_RESOURCE_LIMIT + 1 }]), /over CloudFormation's 2500/);
}

const synthBackend = (out: string, extra: Record<string, string>) => {
  const environment: NodeJS.ProcessEnv = { ...process.env, ...extra };
  for (const key of ["PAPYRUS_COST_TAGS", "PAPYRUS_SITE_ID", "PAPYRUS_COST_TAG_WAVE", "PAPYRUS_COST_TAG_PLAN_FILE"]) if (!(key in extra)) delete environment[key];
  const run = spawnSync(process.execPath, ["--import", "tsx", path.join(repo, "scripts/synth-site-backend.mts"), out], { cwd: repo, encoding: "utf8", env: environment });
  assert.equal(run.status, 0, run.stderr || run.stdout);
  const files = fs.readdirSync(out).filter((file) => file.endsWith(".template.json"));
  assert.ok(files.length > 5, `expected the backend's nested stacks, got ${files.join(", ")}`);
  return Object.fromEntries(files.map((file) => [file, JSON.parse(fs.readFileSync(path.join(out, file), "utf8"))]));
};
const waveOutput = (templates: Record<string, any>) =>
  Object.values<any>(templates).flatMap((template) => Object.entries<any>(template.Outputs ?? {})).find(([key]) => key === "PapyrusCostTagWave")?.[1]?.Value;
const scratch = fs.mkdtempSync(path.join(os.tmpdir(), "papyrus-cost-"));
process.on("exit", () => fs.rmSync(scratch, { recursive: true, force: true }));

// Scenario: a build that does not ask for a wave (a plain ampx pipeline-deploy) synthesizes the backend it had before.
const offTemplates = synthBackend(path.join(scratch, "off"), {});
{
  assert.equal(waveOutput(offTemplates), undefined, "no wave output without a wave");
  for (const [file, template] of Object.entries<any>(offTemplates)) {
    const text = JSON.stringify(template);
    assert.ok(!text.includes("anthus:"), `${file} has an anthus: tag`);
    assert.ok(!text.includes("SendUsageToOwnProspectusQueue"), `${file} grants usage sends`);
    for (const resource of Object.values<any>(template.Resources ?? {})) {
      const variables = resource.Properties?.Environment?.Variables ?? {};
      assert.equal(variables.PAPYRUS_SITE_ID, undefined, file);
      assert.equal(variables.PROSPECTUS_USAGE_QUEUE_URL, undefined, file);
    }
  }
}

// Scenario: the first wave's operation is under CloudFormation's limit, and the plan counts it as the templates do.
{
  const planFile = path.join(scratch, "plan-1.json");
  const waveOne = synthBackend(path.join(scratch, "wave-1"), { PAPYRUS_COST_TAG_WAVE: "1", PAPYRUS_SITE_ID: "dataparade", PAPYRUS_COST_TAG_PLAN_FILE: planFile });
  const plan = JSON.parse(fs.readFileSync(planFile, "utf8"));
  assert.ok(plan.waves.length > 1, "a whole backend takes more than one wave");
  assert.equal(waveOutput(waveOne), `1/${plan.waves.length}`);
  const changed = Object.keys(waveOne).filter((file) => JSON.stringify(waveOne[file]) !== JSON.stringify(offTemplates[file]));
  // Wave 1 changes only its own stacks and their parents: the stacks the plan counted.
  const parents = (id: string): string[] => { const parts = id.split("/"); return parts.map((_, i) => parts.slice(0, i + 1).join("/")); };
  const counted = new Set<string>(plan.waves[0].flatMap((id: string) => parents(id)).map((id: string) => plan.templates[id]).filter(Boolean));
  const outside = changed.filter((file) => !counted.has(file));
  assert.deepEqual(outside, [], "wave 1 changes stacks the plan did not count");
  const changedResources = changed.reduce((sum, file) => sum + Object.keys(waveOne[file].Resources ?? {}).length + 1, 0);
  assert.ok(changedResources <= STACK_OPERATION_RESOURCE_LIMIT, `wave 1 updates ${changedResources} resources`);
  assert.ok(changedResources <= plan.costs[0], `wave 1 updates ${changedResources} resources but the plan counted ${plan.costs[0]}`);
  assert.ok(changed.length < Object.keys(waveOne).length, "wave 1 leaves some stacks alone");
  for (const cost of plan.costs) assert.ok(cost <= WAVE_RESOURCE_BUDGET, `a wave costs ${cost}`);
  // The usage senders are wired in the first pass, so their roles carry the site's tags from the start.
  assert.ok(JSON.stringify(waveOne).includes("SendUsageToOwnProspectusQueue"));
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

// Scenario: once every wave is deployed, every stack of the site backend is tagged, and the model-calling functions may
// send only to their own queue.
{
  const out = path.join(scratch, "all");
  {
    const all = synthBackend(out, { PAPYRUS_COST_TAG_WAVE: "all", PAPYRUS_SITE_ID: "dataparade" });
    assert.equal(waveOutput(all), "complete");
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
