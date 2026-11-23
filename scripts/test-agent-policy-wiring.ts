/**
 * The agent-policy function's IAM (amplify/functions/agent-policy/wire.ts). It reads a policy document's versions through the site document tables' indexes,
 * so its role must allow Query on `<table>/index/*`; a table grant alone left Machines on Machines' console unable to save a review (AccessDenied on
 * siteDocumentVersionsByDocumentIdAndVersion). Besides the policy itself, a resume sends again the wakes a pause stopped
 * (src/papyrus_content/agent_poke_in.py), so the function reads the listener index, reads one agent's runs through the run index by automation on its own site's
 * API, and puts wakes on its own site's wake queue: nothing wider.
 */
import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AttributeType, Table } from "aws-cdk-lib/aws-dynamodb";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { AGENT_POLICY_FUNCTION_FIELDS, LISTENER_INDEX_KEY_PATTERN, wireAgentPolicy } from "../amplify/functions/agent-policy/wire";
import { wakeQueueNames } from "../amplify/agents/wake-queue";

const BUCKET_ARN = "arn:aws:s3:::example-media-bucket";
const app = new App();
const stack = new Stack(app, "data", { env: { account: "123456789012", region: "us-east-1" } });
const lambda = new LambdaFunction(stack, "AgentPolicy", { runtime: Runtime.PYTHON_3_12, handler: "handler.handler", code: Code.fromInline("def handler(e, c): pass") });
const table = (name: string) => new Table(stack, name, { partitionKey: { name: "id", type: AttributeType.STRING } });
const backend = {
  agentPolicy: { resources: { lambda } },
  data: {
    resources: {
      tables: { SiteDocument: table("SiteDocument"), SiteDocumentVersion: table("SiteDocumentVersion") },
      graphqlApi: { apiId: "api123" },
      cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://example.test/graphql" } },
    },
  },
};
wireAgentPolicy(backend, "example-media-bucket", BUCKET_ARN, ["console-client"], "mom");

const template = Template.fromStack(stack);
const policies = Object.values(template.findResources("AWS::IAM::Policy"));
const statements = policies.flatMap((policy) => policy.Properties.PolicyDocument.Statement as { Action: string | string[]; Resource: unknown }[]);
const allowing = (action: string) => statements.filter((statement) => ([] as string[]).concat(statement.Action).includes(action));

assert.deepEqual(AGENT_POLICY_FUNCTION_FIELDS, ["Query/fields/listProcedureRunsByAutomationAndRequestedAt"], "one read of the site's API: the run index by automation");
const appsync = allowing("appsync:GraphQL");
assert.equal(appsync.length, 1, "one appsync statement");
assert.match(JSON.stringify(appsync[0].Resource), /apis\/api123\/types\/Query\/fields\/listProcedureRunsByAutomationAndRequestedAt/);

const sqs = allowing("sqs:SendMessage");
assert.equal(sqs.length, 1, "one statement puts wakes on a queue");
assert.match(JSON.stringify(sqs[0].Resource), new RegExp(wakeQueueNames("mom").queue.replace(/\./g, "\\.")), "the site's own wake queue and no other");

const reads = allowing("s3:GetObject").map((statement) => JSON.stringify(statement.Resource));
assert.ok(reads.some((resource) => resource.includes(`${BUCKET_ARN}/${LISTENER_INDEX_KEY_PATTERN}`)), "the listener index is read");
assert.ok(!allowing("s3:PutObject").some((statement) => JSON.stringify(statement.Resource).includes("listeners")), "the listener index is never written here");
assert.ok(!allowing("s3:DeleteObject").length, "nothing is deleted");

const environment = template.findResources("AWS::Lambda::Function");
const variables = (Object.values(environment)[0] as { Properties: { Environment: { Variables: Record<string, string> } } }).Properties.Environment.Variables;
assert.equal(variables.PAPYRUS_GRAPHQL_ENDPOINT, "https://example.test/graphql");
assert.equal(variables.PAPYRUS_GRAPHQL_AUTH, "iam", "the function signs its own reads: the operator lane");
assert.equal(variables.PERSON_ONLY_CLIENT_IDS, "console-client");
const query = allowing("dynamodb:Query").filter((statement) => JSON.stringify(statement.Resource).includes("/index/*"));
assert.equal(query.length, 1, "the function may query the site document tables' indexes");
const queried = JSON.stringify(query[0].Resource);
assert.ok(queried.includes("SiteDocument") && queried.includes("SiteDocumentVersion"), queried);
assert.equal(variables.SITE_DOCUMENT_VERSION_TABLE !== undefined, true);
console.log("agent policy wiring ok");
