import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { schema } from "../amplify/data/schema";
import { AUTOMATION_VIEW_TIMEOUT_SECONDS } from "../amplify/functions/automation-view/resource";
import {
  AUTOMATION_RUN_NOW_LEADING_KEYS,
  AUTOMATION_RUN_NOW_TABLE_ACTIONS,
  AUTOMATION_VIEW_FUNCTION_FIELDS,
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
  "Query/fields/getNewsroomProcedureDefinition",
  "Query/fields/getProcedureRun",
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

console.log("automation view backend: ok");
