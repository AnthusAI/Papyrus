import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { schema } from "../amplify/data/schema";
import { AUTOMATION_VIEW_TIMEOUT_SECONDS } from "../amplify/functions/automation-view/resource";
import {
  AUTOMATION_RUN_NOW_LEADING_KEYS,
  AUTOMATION_RUN_NOW_TABLE_ACTIONS,
  AUTOMATION_VIEW_FUNCTION_FIELDS,
  wireAutomationView,
  type AutomationViewFollowUps,
} from "../amplify/functions/automation-view/wire";

const text = schema.transform().schema;

// One query, admitted for editors and admins only.
const query = /automationOverview\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(query, "the base schema defines automationOverview");
assert.match(query, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(query), "no public, API-key or guest access");
assert.ok(AUTOMATION_VIEW_TIMEOUT_SECONDS < 30, "the resolver finishes inside AppSync's 30 seconds");

// Today is a query for editors and admins only, served by the same function as automationOverview (a shared function costs one resolver).
const today = /todayOverview\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(today, "the base schema defines todayOverview");
assert.match(today, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(today), "no public, API-key or guest access");

// Run now is a mutation for editors and admins only; no IAM, guest or API-key rule is declared on it.
const mutation = /runAutomation\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(mutation, "the base schema defines runAutomation");
assert.match(mutation, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(mutation), "no public, API-key or guest access");
assert.match(mutation, /automationId: String!/, "the automation is required");

// Acknowledging a run (Today's Acknowledge and Settle) is a mutation for editors and admins only; the run is required.
const acknowledge = /acknowledgeRun\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(acknowledge, "the base schema defines acknowledgeRun");
assert.match(acknowledge, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(acknowledge), "no public, API-key or guest access");
assert.match(acknowledge, /runId: String!/, "the run is required");

// The function reads its own site's API; its one write there is the acknowledgement of a run.
assert.deepEqual([...AUTOMATION_VIEW_FUNCTION_FIELDS].sort(), [
  "Mutation/fields/updateProcedureRun",
  "Query/fields/getAutomation",
  "Query/fields/getDelivery",
  "Query/fields/getNewsroomProcedureDefinition",
  "Query/fields/getProcedureRun",
  "Query/fields/getReviewRequest",
  "Query/fields/listAnnouncementDecisionsByStateAndReleaseAt",
  "Query/fields/listAutomations",
  "Query/fields/listAutomationsByTenant",
  "Query/fields/listDeliveriesByAnnouncementAndCreatedAt",
  "Query/fields/listDeliveriesByDueKeyAndDueAt",
  "Query/fields/listItemsByScheduleStateAndScheduledPublishAt",
  "Query/fields/listProcedureRunsByAttentionKeyAndDueAt",
  "Query/fields/listProcedureRunsByAutomationAndRequestedAt",
  "Query/fields/listProcedureRunsByProcedureAndRequestedAt",
  "Query/fields/listProcedureRunsByStatusAndRequestedAt",
  "Query/fields/listReviewRequestsByReviewStateKeyAndUpdatedAt",
  "Query/fields/listSemanticRelationsBySubjectState",
]);
assert.deepEqual(AUTOMATION_VIEW_FUNCTION_FIELDS.filter((field) => !field.startsWith("Query/")), ["Mutation/fields/updateProcedureRun"], "the one write is acknowledging a run");

// Run now writes one monitoring row in a monitor's partition and puts a wake on its site's queue (wake-queue.ts allowWakeSending), and does nothing else.
assert.deepEqual(AUTOMATION_RUN_NOW_TABLE_ACTIONS, ["dynamodb:PutItem"]);
assert.deepEqual(AUTOMATION_RUN_NOW_LEADING_KEYS, ["MONITOR#*"]);

// The Automation model: editors read, create and update; only admins delete; no guest, public or identity-pool access.
const model = /type Automation @model[\s\S]*?\n}\n/.exec(text)?.[0] ?? "";
assert.ok(model, "the base schema defines the Automation model");
for (const field of ["title", "enabled", "trigger", "procedureKey", "inputTemplate", "limits", "createdAt", "updatedAt"]) {
  assert.match(model, new RegExp(`\\b${field}:`), `Automation has ${field}`);
}
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(model), "no public, API-key or guest access");
assert.match(model, /allow: groups, operations: \[read, create, update\], groups: \["editor"\]/, "editors read, create and update");
assert.match(model, /allow: groups, operations: \[read, create, update, delete\], groups: \["admin"\]/, "admins also delete");
assert.equal((model.match(/allow:/g) ?? []).length, 2, "only those two rules");

// The Python client reads the same field list the model declares.
const client = readFileSync(join(process.cwd(), "src/papyrus_content/graphql_authoring.py"), "utf8");
const fields = /AUTOMATION_FIELDS = \(\s*"([^"]+)"/.exec(client)?.[1].split(" ") ?? [];
assert.ok(fields.length > 0, "the Python client lists the Automation fields");
for (const field of fields) assert.match(model, new RegExp(`\\b${field}:`), `the model declares ${field}`);

// A dedicated site whose records carry a tenant (its build sets PAPYRUS_TENANT_ID) gives the function that tenant, so Today reads its agents through the
// Automation tenant index as the site's tenant instead of answering "unavailable" (Machines on Machines, 2026-11-23). A shared stack and a site with no
// tenant give it none, and read as they always have.
function automationViewEnvironment(followUps: AutomationViewFollowUps | undefined): Record<string, string> {
  const stack = new Stack(new App(), "data", { env: { account: "123456789012", region: "us-east-1" } });
  const lambda = new LambdaFunction(stack, "AutomationView", { runtime: Runtime.PYTHON_3_12, handler: "handler.handler", code: Code.fromInline("def handler(e, c): pass") });
  const backend = {
    automationView: { resources: { lambda } },
    data: { resources: { graphqlApi: { apiId: "api123" }, cfnResources: { cfnGraphqlApi: { attrGraphQlUrl: "https://example.test/graphql" } } } },
    storage: { resources: { bucket: { bucketName: "example-site-bucket" } } },
  };
  wireAutomationView(backend, "mom", "America/New_York", followUps);
  const functions = Object.values(Template.fromStack(stack).findResources("AWS::Lambda::Function"));
  return (functions[0] as { Properties: { Environment: { Variables: Record<string, string> } } }).Properties.Environment.Variables;
}

const tenantSite = automationViewEnvironment({ tenantId: "machines-on-machines" });
assert.equal(tenantSite.PAPYRUS_TENANT_ID, "machines-on-machines", "a tenant site's function reads as the site's tenant");
assert.equal(tenantSite.PAPYRUS_AGENT_TENANT_ID, undefined, "the tenant is named once, as the function's own");
assert.equal(tenantSite.PAPYRUS_AGENT_PUBLICATION_ID, "mom", "Wake now on an Overdue record names the site its timers belong to");
assert.equal(tenantSite.PAPYRUS_SITE_BUCKET, "example-site-bucket");
assert.equal(automationViewEnvironment({ tenantId: "" }).PAPYRUS_TENANT_ID, undefined, "a dedicated site with no tenant reads as it always has");
assert.equal(automationViewEnvironment(undefined).PAPYRUS_TENANT_ID, undefined, "a shared stack takes no fixed tenant");

console.log("automation view backend: ok");
