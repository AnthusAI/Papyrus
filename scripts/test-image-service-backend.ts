import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { schema } from "../amplify/data/schema";
import { IMAGE_SERVICE_TIMEOUT_SECONDS } from "../amplify/functions/image-service/resource";
import { IMAGE_SERVICE_BUCKET_ACTIONS, IMAGE_SERVICE_BUCKET_PREFIX, IMAGE_SERVICE_FUNCTION_FIELDS } from "../amplify/functions/image-service/wire";

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

// The guidelines door is the same shape: editors and admins at the door, a request id on every write, the same function.
const guidelinesQuery = /guidelinesRead\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(guidelinesQuery, "the base schema defines guidelinesRead");
assert.match(guidelinesQuery, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(guidelinesQuery), "no public, API-key or guest access");
assert.match(guidelinesQuery, /op: String!/, "the operation is required");
assert.match(guidelinesQuery, /actorKind: String/, "a caller may declare itself an agent");
const guidelinesMutation = /guidelinesWrite\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(guidelinesMutation, "the base schema defines guidelinesWrite");
assert.match(guidelinesMutation, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(guidelinesMutation), "no public, API-key or guest access");
assert.match(guidelinesMutation, /requestId: ID!/, "a guideline write carries a request id so it is safe to repeat");
assert.match(guidelinesMutation, /actorKind: String/, "a caller may declare itself an agent");

// The function writes Item versions and the attachment rows of guideline documents: no other model is created or updated.
const mutations = IMAGE_SERVICE_FUNCTION_FIELDS.filter((field) => field.startsWith("Mutation/"));
assert.deepEqual(mutations.sort(), ["Mutation/fields/createItem", "Mutation/fields/createModelAttachment", "Mutation/fields/updateItem"]);

// Its role reaches only the payloads of Item versions in the bucket, to read and write, never delete or list.
assert.equal(IMAGE_SERVICE_BUCKET_PREFIX, "newsroom/payloads/item/");
assert.deepEqual([...IMAGE_SERVICE_BUCKET_ACTIONS].sort(), ["s3:GetObject", "s3:PutObject"]);

// The section style is one optional JSON field on the section.
const section = /type NewsroomSection @model[\s\S]*?\n}\n/.exec(text)?.[0] ?? "";
assert.match(section, /visualStyle: AWSJSON\n/, "NewsroomSection has an optional visualStyle");

// The Python function keeps the door closed to anyone outside the staff groups and reads the field the schema declares.
const python = readFileSync(join(process.cwd(), "src/papyrus_content/image_service.py"), "utf8");
assert.match(python, /has_editor_rights/, "the function repeats the group check");
assert.match(readFileSync(join(process.cwd(), "src/papyrus_content/images/profile_handlers.py"), "utf8"), /SECTION_STYLE_FIELD = "visualStyle"/);
assert.match(python, /guidelinesRead/, "the function serves the guidelines doors");
assert.match(readFileSync(join(process.cwd(), "src/papyrus_content/guidelines/s3_files.py"), "utf8"), /PAYLOAD_PREFIX = "newsroom\/payloads\/item\/"/, "the Python files stay under the prefix the role allows");

console.log("image service backend: ok");
