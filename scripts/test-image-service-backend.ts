import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { schema } from "../amplify/data/schema";
import { IMAGE_SERVICE_TIMEOUT_SECONDS } from "../amplify/functions/image-service/resource";
import { IMAGE_SERVICE_FUNCTION_FIELDS } from "../amplify/functions/image-service/wire";

const text = schema.transform().schema;

// One query and one mutation, admitted for editors and admins only.
const query = /imageRead\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(query, "the base schema defines imageRead");
assert.match(query, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(query), "no public, API-key or guest access");
assert.match(query, /op: String!/, "the operation is required");

const mutation = /imageWrite\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(mutation, "the base schema defines imageWrite");
assert.match(mutation, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(mutation), "no public, API-key or guest access");
assert.match(mutation, /requestId: ID!/, "a write carries a request id so it is safe to repeat");
assert.ok(IMAGE_SERVICE_TIMEOUT_SECONDS < 30, "the resolver finishes inside AppSync's 30 seconds");

// The function writes only Item versions in this step: no other model is created or updated.
const mutations = IMAGE_SERVICE_FUNCTION_FIELDS.filter((field) => field.startsWith("Mutation/"));
assert.deepEqual(mutations.sort(), ["Mutation/fields/createItem", "Mutation/fields/updateItem"]);

// The section style is one optional JSON field on the section.
const section = /type NewsroomSection @model[\s\S]*?\n}\n/.exec(text)?.[0] ?? "";
assert.match(section, /visualStyle: AWSJSON\n/, "NewsroomSection has an optional visualStyle");

// The Python function keeps the door closed to anyone outside the staff groups and reads the field the schema declares.
const python = readFileSync(join(process.cwd(), "src/papyrus_content/image_service.py"), "utf8");
assert.match(python, /has_editor_rights/, "the function repeats the group check");
assert.match(readFileSync(join(process.cwd(), "src/papyrus_content/images/profile_handlers.py"), "utf8"), /SECTION_STYLE_FIELD = "visualStyle"/);

console.log("image service backend: ok");
