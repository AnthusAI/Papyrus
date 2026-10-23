import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { schema } from "../amplify/data/schema";
import { AUTOMATION_VIEW_TIMEOUT_SECONDS } from "../amplify/functions/automation-view/resource";
import {
  AUTOMATION_RUN_NOW_LEADING_KEYS,
  AUTOMATION_RUN_NOW_TABLE_ACTIONS,
  AUTOMATION_VIEW_FUNCTION_FIELDS,
  PROCEDURE_RUNNER_FUNCTION_NAME,
} from "../amplify/functions/automation-view/wire";

const text = schema.transform().schema;

// One query, admitted for editors and admins only.
const query = /automationOverview\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(query, "the base schema defines automationOverview");
assert.match(query, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(query), "no public, API-key or guest access");
assert.ok(AUTOMATION_VIEW_TIMEOUT_SECONDS < 30, "the resolver finishes inside AppSync's 30 seconds");

// Run now is a mutation for editors and admins only; no IAM, guest or API-key rule is declared on it.
const mutation = /runAutomation\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(mutation, "the base schema defines runAutomation");
assert.match(mutation, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(mutation), "no public, API-key or guest access");
assert.match(mutation, /automationId: String!/, "the automation is required");

// The function only reads its own site's API (no Mutation field is granted there).
assert.deepEqual([...AUTOMATION_VIEW_FUNCTION_FIELDS].sort(), [
  "Query/fields/getAutomation",
  "Query/fields/getNewsroomProcedureDefinition",
  "Query/fields/getProcedureRun",
  "Query/fields/listAutomations",
  "Query/fields/listProcedureRunsByProcedureAndRequestedAt",
]);
assert.ok(AUTOMATION_VIEW_FUNCTION_FIELDS.every((field) => field.startsWith("Query/")), "no mutation is granted");

// Run now writes one monitoring row in a monitor's partition and starts the runner, and does nothing else.
assert.deepEqual(AUTOMATION_RUN_NOW_TABLE_ACTIONS, ["dynamodb:PutItem"]);
assert.deepEqual(AUTOMATION_RUN_NOW_LEADING_KEYS, ["MONITOR#*"]);
assert.equal(PROCEDURE_RUNNER_FUNCTION_NAME, "papyrus-procedure-runner");

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
