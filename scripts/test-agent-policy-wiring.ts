/**
 * The agent-policy function's IAM (amplify/functions/agent-policy/wire.ts): it reads a policy document's versions through the site document tables' indexes,
 * so its role must allow Query on `<table>/index/*`; a table grant alone left Machines on Machines' console unable to save a review (AccessDenied on
 * siteDocumentVersionsByDocumentIdAndVersion).
 */
import assert from "node:assert/strict";
import { wireAgentPolicy } from "../amplify/functions/agent-policy/wire";

const statements: Array<{ actions: string[]; resources: string[] }> = [];
const environment: Record<string, string> = {};
const lambda = {
  addToRolePolicy: (statement: { toStatementJson(): { Action: string | string[]; Resource: string | string[] } }) => {
    const json = statement.toStatementJson();
    statements.push({ actions: ([] as string[]).concat(json.Action), resources: ([] as string[]).concat(json.Resource) });
  },
  addEnvironment: (name: string, value: string) => { environment[name] = value; },
};
const table = (name: string) => ({ tableArn: `arn:aws:dynamodb:us-east-1:111122223333:table/${name}`, tableName: name, grantReadWriteData: () => undefined });
const backend = {
  agentPolicy: { resources: { lambda } },
  data: { resources: { tables: { SiteDocument: table("SiteDocument-x"), SiteDocumentVersion: table("SiteDocumentVersion-x") } } },
};

wireAgentPolicy(backend, "media-bucket", "arn:aws:s3:::media-bucket", ["client-1"]);

const query = statements.find((statement) => statement.actions.includes("dynamodb:Query"));
assert.ok(query, "the function may query");
assert.deepEqual(query.resources.sort(), [
  "arn:aws:dynamodb:us-east-1:111122223333:table/SiteDocument-x/index/*",
  "arn:aws:dynamodb:us-east-1:111122223333:table/SiteDocumentVersion-x/index/*",
]);
assert.equal(environment.SITE_DOCUMENT_VERSION_TABLE, "SiteDocumentVersion-x");
console.log("agent policy wiring ok");
