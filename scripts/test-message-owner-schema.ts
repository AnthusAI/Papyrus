/**
 * Messages belong to their author. Reads the schema the data API is built from (the Amplify transform's own output, not a copy of the
 * source) and checks who may do what to a Message, and that the machine writers' grants are untouched.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { schema } from "../amplify/data/schema";

const root = join(import.meta.dirname, "..");
const transformed: string = (schema as unknown as { transform: () => { schema: string } }).transform().schema;

function modelBlock(source: string, model: string): string {
  const start = source.indexOf(`type ${model} @model`);
  assert.ok(start >= 0, `${model} is in the schema`);
  return source.slice(start, source.indexOf("\n}\n", start));
}
const authRules = (source: string, model: string) => modelBlock(source, model).split("{\n")[0];

test("a Message's author can read, update and delete their own, matched on the sub claim", () => {
  const rules = authRules(transformed, "Message");
  assert.match(rules, /allow: owner, operations: \[read, update, delete\], ownerField: "authorSub", identityClaim: "sub"/);
});

test("editors and admins read and create; only an admin deletes someone else's; nobody but the author updates", () => {
  const rules = authRules(transformed, "Message");
  assert.match(rules, /allow: groups, operations: \[read, create\], groups: \["editor", "admin"\]/);
  assert.match(rules, /allow: groups, operations: \[delete\], groups: \["admin"\]/);
  const groupRules = rules.split("\n").filter((line) => line.includes("allow: groups"));
  assert.equal(groupRules.some((line) => /update/.test(line)), false, "no group may update a Message");
  assert.equal(groupRules.filter((line) => /delete/.test(line)).every((line) => /groups: \["admin"\]/.test(line)), true, "editors cannot delete");
});

test("a Message can record that it was edited and deleted, and by whom", () => {
  const block = modelBlock(transformed, "Message");
  assert.match(block, /\n\s+editedAt: AWSDateTime\n/);
  assert.match(block, /\n\s+deletedAt: AWSDateTime\n/);
  assert.match(block, /\n\s+deletedBySub: String\n/);
});

test("the typed schema (resource.ts) carries the same rule and fields, and keeps its identity-pool access", () => {
  const source = readFileSync(join(root, "amplify/data/resource.ts"), "utf8");
  const start = source.indexOf("  Message: a");
  const block = source.slice(start, source.indexOf("  MessageThread: a", start));
  assert.match(block, /allow\.group\(adminGroup\)\.to\(\["delete"\]\)/);
  assert.match(block, /allow\.ownerDefinedIn\("authorSub"\)\.identityClaim\("sub"\)\.to\(\["read", "update", "delete"\]\)/);
  assert.match(block, /allow\.authenticated\("identityPool"\)\.to\(\["read", "create", "update"\]\)/);
  for (const field of ["editedAt: a.datetime()", "deletedAt: a.datetime()", "deletedBySub: a.string()"]) assert.ok(block.includes(field), field);
});

test("the owner rule is the only addition: the rules on every other model and the schema-level function grants are unchanged", () => {
  const messageThread = authRules(transformed, "MessageThread");
  assert.match(messageThread, /groups: \["editor", "admin"\]/);
  assert.doesNotMatch(messageThread, /owner/);
  const source = readFileSync(join(root, "amplify/data/schema.ts"), "utf8");
  const grants = source.slice(source.indexOf("function functionGrants"), source.indexOf("export const schema"));
  for (const fn of ["assignmentAction", "categoryAction", "contentActions", "manageUserRole", "modelAttachmentUpload", "newsroomSummary", "procedureAction", "publicForms"]) {
    assert.ok(grants.includes(`allow.resource(${fn})`), `${fn} keeps its grant`);
  }
  // The assignment function (the router and procedures write Messages through it) keeps create and update on Message.
  const access = readFileSync(join(root, "amplify/functions/assignment-action/data-access.ts"), "utf8");
  assert.ok(access.includes('"Mutation/fields/createMessage"') && access.includes('"Mutation/fields/updateMessage"'));
});

test("the web clients' creates stay inside the group rule: they set authorSub to the session sub or leave it empty", () => {
  const client = readFileSync(join(root, "components/news-desk-taxonomy-client.ts"), "utf8");
  assert.match(client, /authorSub: author\.sub,/, "conversation messages carry the session sub");
  const chat = readFileSync(join(root, "lib/console-chat-client.ts"), "utf8");
  assert.ok((chat.match(/authorSub: null,/g) ?? []).length >= 2, "console chat leaves it empty");
});
