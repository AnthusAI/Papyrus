import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { schema } from "../amplify/data/schema";
import { AUTOMATION_VIEW_TIMEOUT_SECONDS } from "../amplify/functions/automation-view/resource";
import { AUTOMATION_VIEW_FUNCTION_FIELDS } from "../amplify/functions/automation-view/wire";

const text = schema.transform().schema;

// One query, admitted for editors and admins only.
const query = /automationOverview\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(query, "the base schema defines automationOverview");
assert.match(query, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(query), "no public, API-key or guest access");
assert.ok(AUTOMATION_VIEW_TIMEOUT_SECONDS < 30, "the resolver finishes inside AppSync's 30 seconds");

// The function reads two fields of its own API and writes nothing.
assert.deepEqual([...AUTOMATION_VIEW_FUNCTION_FIELDS].sort(), ["Query/fields/getProcedureRun", "Query/fields/listAutomations"]);
assert.ok(AUTOMATION_VIEW_FUNCTION_FIELDS.every((field) => field.startsWith("Query/")), "no mutation is granted");

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
