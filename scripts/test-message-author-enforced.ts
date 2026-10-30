/**
 * The backend stamps a Message's author and moderates deletes. Two layers are checked: the schema the data API is built from (the
 * Amplify transform's own output) and the AppSync resolvers, which are run here against a stand-in for `@aws-appsync/utils` that
 * records the DynamoDB operation each would send. Nothing is deployed and nothing touches AWS.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { schema } from "../amplify/data/schema";
import { postMessageArguments, postMessageMutation } from "../lib/post-message";

const root = join(import.meta.dirname, "..");
const read = (file: string) => readFileSync(join(root, file), "utf8");
const transformed = (schema as unknown as { transform: () => { schema: string; jsFunctions: Array<{ typeName: string; fieldName: string; handlers: Array<{ dataSource: string; entry: { relativePath: string } }> }> } }).transform();

function modelBlock(model: string): string {
  const start = transformed.schema.indexOf(`type ${model} @model`);
  assert.ok(start >= 0, `${model} is in the schema`);
  return transformed.schema.slice(start, transformed.schema.indexOf("\n}\n", start));
}
const modelRules = (model: string) => modelBlock(model).split("{\n")[0];

// ---- Resolvers, run against a recording stand-in for the AppSync runtime ----
type Op = { op: "put" | "update"; key: { id: string }; item?: Record<string, unknown>; update?: Record<string, { replace: unknown }>; condition: Record<string, unknown> };
type Identity = { sub?: string; groups?: string[]; claims?: Record<string, unknown> } | null;
class AppSyncError extends Error { constructor(message: string, public type: string) { super(message); } }

function loadResolver(file: string) {
  const source = read(`amplify/data/resolvers/${file}`).replace(/^import .*$/gm, "").replace(/^export /gm, "");
  const util = {
    error: (message: string, type: string) => { throw new AppSyncError(message, type); },
    time: { nowISO8601: () => "2026-10-29T12:00:00.000Z" },
  };
  const ddb = {
    put: (o: Omit<Op, "op">): Op => ({ op: "put", ...o }),
    update: (o: Omit<Op, "op">): Op => ({ op: "update", ...o }),
    operations: { replace: (value: unknown) => ({ replace: value }) },
  };
  return new Function("util", "ddb", `${source}\nreturn { request, response };`)(util, ddb) as { request: (ctx: unknown) => Op; response: (ctx: unknown) => unknown };
}
const ctxFor = (identity: Identity, args: Record<string, unknown>) => ({ identity, args });
const refused = (run: () => unknown, pattern: RegExp) => assert.throws(run, (error) => error instanceof AppSyncError && pattern.test(error.message));

const ALICE = { sub: "sub-alice", groups: ["editor"], claims: { email: "alice@example.test" } };
const ADMIN = { sub: "sub-root", groups: ["admin"] };

test("a post records the signed-in user as the author, whatever the client sends", () => {
  const { request } = loadResolver("post-message.js");
  const op = request(ctxFor(ALICE, {
    id: "m1", threadId: "t1", content: "  Hello  ", messageKind: "comment", messageDomain: "commentary", authorLabel: "Ada Lovelace",
    // Fields the mutation does not declare (a client cannot send them through GraphQL, and the resolver would ignore them anyway).
    authorSub: "sub-someone-else", authorUserProfileId: "profile-other", createdAt: "2001-01-01T00:00:00Z",
  }));
  assert.equal(op.op, "put");
  assert.equal(op.item!.authorSub, "sub-alice", "the author is the identity's sub");
  assert.equal(op.item!.authorLabel, "Ada Lovelace", "a label is only a label");
  assert.equal("authorUserProfileId" in op.item!, false);
  assert.equal(op.item!.createdAt, "2026-10-29T12:00:00.000Z", "the server sets the time");
  assert.equal(op.item!.updatedAt, "2026-10-29T12:00:00.000Z");
  assert.equal(op.item!.responseStatus, "COMPLETED");
  assert.equal(op.item!.status, "active");
  assert.equal(op.item!.content, "Hello");
  assert.equal(op.item!.__typename, "Message");
  assert.deepEqual(op.condition, { id: { attributeExists: false } }, "an existing message is never replaced");
});

test("a post with no label takes the signed-in email, and a sign-out cannot post", () => {
  const { request } = loadResolver("post-message.js");
  assert.equal(request(ctxFor(ALICE, { id: "m1", threadId: "t1", content: "x", messageKind: "k", messageDomain: "d" })).item!.authorLabel, "alice@example.test");
  refused(() => request(ctxFor(null, { id: "m1", threadId: "t1", content: "x", messageKind: "k", messageDomain: "d" })), /Sign in/);
  refused(() => request(ctxFor(ALICE, { id: "m1", threadId: "t1", content: "   ", messageKind: "k", messageDomain: "d" })), /cannot be empty/);
});

test("a console chat placeholder may start empty and wait for a responder", () => {
  const { request } = loadResolver("post-message.js");
  const op = request(ctxFor(ALICE, { id: "m1", threadId: "t1", content: "", messageKind: "console", messageDomain: "chat", responseStatus: "PENDING", responseTarget: "cloud" }));
  assert.equal(op.item!.responseStatus, "PENDING");
  assert.equal(op.item!.authorSub, "sub-alice");
});

test("a lost race for an id is reported as a conflict the caller retries", () => {
  const { response } = loadResolver("post-message.js");
  refused(() => response({ error: { type: "DynamoDB:ConditionalCheckFailedException", message: "x" } }), /already exists \(conditional check failed\)/);
});

test("nobody can edit another person's message: the write is conditional on the stored author, and a refusal says so", () => {
  const { request, response } = loadResolver("edit-message.js");
  const op = request(ctxFor(ALICE, { id: "m1", content: "Better" }));
  assert.equal(op.op, "update");
  assert.deepEqual(op.condition, { authorSub: { eq: "sub-alice" }, status: { ne: "deleted" } }, "the stored author must be the caller, and the message not deleted");
  assert.deepEqual(Object.keys(op.update!).sort(), ["content", "editedAt", "summary", "updatedAt"], "only the text and when it changed");
  assert.equal(op.update!.editedAt.replace, "2026-10-29T12:00:00.000Z");
  refused(() => response({ error: { type: "DynamoDB:ConditionalCheckFailedException", message: "x" } }), /Only the author can edit a message, and a deleted message cannot be edited\./);
  // An admin is not the author, so the same condition keeps an admin from editing.
  assert.deepEqual(request(ctxFor(ADMIN, { id: "m1", content: "Rewrite" })).condition, { authorSub: { eq: "sub-root" }, status: { ne: "deleted" } });
});

test("an author cannot reassign authorship: no resolver ever writes authorSub on an update", () => {
  for (const file of ["edit-message.js", "delete-own-message.js", "moderate-message.js"]) {
    const op = loadResolver(file).request(ctxFor(file === "moderate-message.js" ? ADMIN : ALICE, { id: "m1", content: "x" }));
    assert.equal("authorSub" in (op.update ?? {}), false, `${file} does not write authorSub`);
  }
  const fields = transformed.schema.split("\n").filter((line) => /^\s*(postMessage|editMessage|deleteOwnMessage|moderateMessage|renameThread)\(/.test(line)).join("\n");
  assert.ok(fields.length > 0);
  assert.doesNotMatch(fields, /authorSub|authorUserProfileId|createdAt|updatedAt/, "no mutation takes an author or a time");
  const model = modelRules("Message");
  assert.doesNotMatch(model, /update|owner/, "the model offers no update, and no owner rule");
});

test("an author deletes their own message softly: a marker with when and by whom, and nothing removed", () => {
  const { request, response } = loadResolver("delete-own-message.js");
  const op = request(ctxFor(ALICE, { id: "m1" }));
  assert.equal(op.op, "update");
  assert.equal(op.update!.status.replace, "deleted");
  assert.equal(op.update!.deletedBySub.replace, "sub-alice");
  assert.equal(op.update!.deletedAt.replace, "2026-10-29T12:00:00.000Z");
  assert.equal("content" in op.update!, false, "the stored text is not touched");
  assert.deepEqual(op.condition, { authorSub: { eq: "sub-alice" }, status: { ne: "deleted" } });
  refused(() => response({ error: { type: "DynamoDB:ConditionalCheckFailedException", message: "x" } }), /Only the author can delete their own message/);
});

test("an admin soft-deletes anyone's message with moderateMessage but cannot edit it; others cannot moderate", () => {
  const { request } = loadResolver("moderate-message.js");
  const op = request(ctxFor(ADMIN, { id: "m1" }));
  assert.equal(op.update!.status.replace, "deleted");
  assert.equal(op.update!.deletedBySub.replace, "sub-root", "recorded as the admin's doing");
  assert.deepEqual(Object.keys(op.update!).sort(), ["deletedAt", "deletedBySub", "status", "updatedAt"], "no content edit");
  assert.deepEqual(op.condition, { id: { attributeExists: true }, status: { ne: "deleted" } });
  refused(() => request(ctxFor(ALICE, { id: "m1" })), /Only an admin can delete someone else's message/);
  // And the mutation is offered to admins only, while editing is a different mutation an admin passes only for their own messages.
  assert.match(read("amplify/data/message-actions.ts"), /moderateMessage: a[\s\S]*?\.authorization\(adminsOnly\)/);
});

test("a thread is renamed by its creator or an admin only", () => {
  const { request, response } = loadResolver("rename-thread.js");
  assert.deepEqual(request(ctxFor(ALICE, { id: "t1", title: " New name " })).condition, { createdBySub: { eq: "sub-alice" } });
  assert.equal(request(ctxFor(ALICE, { id: "t1", title: " New name " })).update!.title.replace, "New name");
  assert.deepEqual(request(ctxFor(ADMIN, { id: "t1", title: "Moderated" })).condition, { id: { attributeExists: true } });
  refused(() => request(ctxFor(ALICE, { id: "t1", title: "  " })), /cannot be empty/);
  refused(() => response({ error: { type: "DynamoDB:ConditionalCheckFailedException", message: "x" } }), /Only the person who started this conversation, or an admin, can rename it\./);
  const thread = modelBlock("MessageThread");
  assert.match(thread, /title: String! @auth\(rules: \[\{allow: groups, operations: \[read, create\], groups: \["editor"\]\}/, "the title cannot be updated through the model");
  assert.match(thread, /createdBySub: String @index[^\n]*@auth\(rules: \[\{allow: groups, operations: \[read, create\]|createdBySub: String @auth/, "the creator cannot be changed through the model");
});

test("the schema offers the five mutations to the right groups, on the right tables, and the model is read-only for people", () => {
  const rules = modelRules("Message");
  assert.match(rules, /allow: groups, operations: \[read\], groups: \["editor"\]/);
  assert.match(rules, /allow: groups, operations: \[read\], groups: \["admin"\]/);
  assert.doesNotMatch(rules, /create|update|delete/, "people cannot write a Message through the model");
  const byField = Object.fromEntries(transformed.jsFunctions.map((fn) => [fn.fieldName, fn.handlers[0]]));
  assert.deepEqual(Object.keys(byField).sort(), ["deleteOwnMessage", "editMessage", "moderateMessage", "postMessage", "renameThread"]);
  for (const name of ["postMessage", "editMessage", "deleteOwnMessage", "moderateMessage"]) assert.equal(byField[name].dataSource, "MessageTable", name);
  assert.equal(byField.renameThread.dataSource, "MessageThreadTable");
  for (const name of ["postMessage", "editMessage", "deleteOwnMessage", "moderateMessage", "renameThread"]) {
    const line = transformed.schema.split("\n").find((entry) => entry.includes(`${name}(`));
    assert.ok(line, `${name} is a field`);
  }
  // The typed schema carries the same Message rules.
  const typed = read("amplify/data/resource.ts");
  const block = typed.slice(typed.indexOf("  Message: a"), typed.indexOf("  MessageThread: a"));
  assert.ok(block.includes('allow.group("editor").to(["read"])') && block.includes('allow.group(adminGroup).to(["read"])'));
  assert.doesNotMatch(block, /ownerDefinedIn/);
});

test("machine writers still work: function grants, IAM and the model's write operations for them are untouched", () => {
  const source = read("amplify/data/schema.ts");
  const grants = source.slice(source.indexOf("function functionGrants"), source.indexOf("export const schema"));
  for (const fn of ["assignmentAction", "categoryAction", "contentActions", "manageUserRole", "modelAttachmentUpload", "newsroomSummary", "procedureAction", "publicForms"]) {
    assert.ok(grants.includes(`allow.resource(${fn})`), `${fn} keeps its grant`);
  }
  const access = read("amplify/functions/assignment-action/data-access.ts");
  assert.ok(access.includes('"Mutation/fields/createMessage"') && access.includes('"Mutation/fields/updateMessage"'), "the router and procedures still create and update Messages directly");
  // The model is still a model with create and update operations; only the groups lost them (IAM callers are not group-gated).
  assert.doesNotMatch(modelRules("Message"), /disableOperations/);
});

test("the browser writes only through postMessage: no author, no timestamps, on every path", () => {
  const args = postMessageArguments({
    id: "m1", threadId: "t1", content: "Hi", messageKind: "comment", messageDomain: "commentary", metadata: { a: 1 },
    authorSub: "sub-forged", authorUserProfileId: "p", createdAt: "x", updatedAt: "y", status: "deleted",
  });
  assert.deepEqual(Object.keys(args).sort(), ["content", "id", "messageDomain", "messageKind", "metadata", "threadId"]);
  assert.equal(args.metadata, '{"a":1}');
  const query = postMessageMutation(args, "id authorSub");
  assert.match(query, /^mutation PostMessage\(\$id: ID!, \$threadId: ID!, \$content: String, /);
  assert.match(query, /postMessage\(id: \$id, threadId: \$threadId, content: \$content/);
  assert.doesNotMatch(query, /authorSub: \$|createdAt: \$/);
  const forum = read("components/news-desk-taxonomy-client.ts");
  assert.match(forum, /postMessageMutation\(args, POST_MESSAGE_SELECTION\)/, "conversation and forum posts");
  assert.doesNotMatch(forum, /createMessage\(input/, "no createMessage from the news desk client");
  assert.doesNotMatch(forum, /authorSub: author\.sub/, "and no author named");
  const chat = read("lib/console-chat-client.ts");
  assert.match(chat, /postMessageMutation\(args, selectionSet\)/, "console chat user turns");
  assert.doesNotMatch(chat, /createMessage\(input/, "no createMessage from the console chat client");
  assert.doesNotMatch(chat, /authorSub:/, "and no author named");
});
