/**
 * The Proposals queue is core: every site's data API has the Proposal model, the editor and operator operations, and the
 * proposal-actions function, with or without the reader-steering plugin. This pins the base schema, the wiring and the
 * boundary with the plugin.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AttributeType, Table } from "aws-cdk-lib/aws-dynamodb";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { schema, schemaWithPlugins } from "../amplify/data/schema";
import { proposalActionsSchemaDefinitions } from "../amplify/functions/proposal-actions/schema";
import { wireProposalActions } from "../amplify/functions/proposal-actions/wire";
import { readerSteeringSchemaDefinitions } from "../amplify/plugins/reader-steering/schema";

const OPERATIONS = ["fileProposal", "transitionProposal", "editProposal", "listStoryDrafts"];

// The base schema (a site with no plugins) defines the whole queue.
const base = schema.transform().schema;
assert.match(base, /type Proposal @model[^\n]*/, "Proposal is a model of the base schema");
const declarationStart = base.indexOf("type Proposal @model");
const declaration = base.slice(declarationStart, base.indexOf("{\n", declarationStart));
assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)|guest/.test(declaration), false, `Proposal is staff-only: ${declaration}`);
assert.match(declaration, /groups: \["editor"\]/);
assert.match(declaration, /groups: \["admin"\]/);
assert.match(base, /listProposalsByStateAndCreatedAt/, "editors can list proposals by state");
for (const name of OPERATIONS) {
  const start = base.indexOf(`${name}(`) >= 0 ? base.indexOf(`${name}(`) : base.indexOf(`${name}:`);
  assert.ok(start > 0, `${name} is in the base schema`);
  const operation = base.slice(start, start + 400).split("\n\n")[0];
  assert.match(operation, /@function/);
  assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)|guest/.test(operation), false, `${name} is open to groups only: ${operation}`);
  assert.match(operation, /groups: \["editor"\]/);
  assert.match(operation, /groups: \["admin"\]/);
}
const summaryStart = base.indexOf("type StoryDraftSummary");
const summaryFields = [...base.slice(summaryStart, base.indexOf("}", summaryStart)).matchAll(/^\s+(\w+):/gm)].map((match) => match[1]);
assert.deepEqual(summaryFields, ["id", "title", "summary", "targets", "state", "createdAt"], "an operator reads six fields of a draft and nothing else");

// No reader model comes with it.
for (const reader of ["ReaderVote", "ReaderProfile", "ReaderComment", "moderateReader"]) {
  assert.equal(base.includes(reader), false, `${reader} stays in the reader-steering plugin`);
}

// The plugin does not redefine any of it, and a site with the plugin still has each definition exactly once.
const pluginDefinitions = readerSteeringSchemaDefinitions() as Record<string, unknown>;
for (const name of Object.keys(proposalActionsSchemaDefinitions)) {
  assert.equal(name in pluginDefinitions, false, `${name} is core, not the plugin's`);
}
const withPlugin = schemaWithPlugins(pluginDefinitions).transform().schema;
assert.equal(withPlugin.match(/type Proposal @model/g)?.length, 1);
assert.match(withPlugin, /type ReaderVote @model/);

// Wiring: the function gets the Proposal table and nothing else.
const app = new App();
const stack = new Stack(app, "Data", { env: { account: "123456789012", region: "us-east-1" } });
const lambda = new Function(stack, "ProposalActions", { runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x") });
const tables = { Proposal: new Table(stack, "Proposal", { partitionKey: { name: "id", type: AttributeType.STRING } }), Item: new Table(stack, "Item", { partitionKey: { name: "id", type: AttributeType.STRING } }) };
wireProposalActions({ proposalActions: { resources: { lambda } }, data: { resources: { tables } } });
const template = Template.fromStack(stack);
const variables = Object.values(template.findResources("AWS::Lambda::Function")).map((resource) => (resource as { Properties: { Environment?: { Variables: Record<string, unknown> } } }).Properties.Environment?.Variables ?? {});
assert.ok(variables.some((entry) => "PAPYRUS_PROPOSAL_TABLE" in entry), "the function is told its table");
const policy = JSON.stringify(template.findResources("AWS::IAM::Policy"));
assert.ok(policy.includes("Proposal"), "the function may use the Proposal table");
assert.equal(policy.includes('"Item"') && /Fn::GetAtt":\["Item"/.test(policy), false, "the function may not touch any other table");

// The function is stdlib only and does not import the plugin.
const handler = readFileSync(join(process.cwd(), "amplify/functions/proposal-actions/handler.py"), "utf8");
assert.equal(/reader|moderation/i.test(handler.replace(/Reader votes on proposals and the public\s+files belong to the reader-steering plugin, which reads this same table\./, "")), false, "proposal-actions knows nothing of readers");

console.log("proposal actions ok");
