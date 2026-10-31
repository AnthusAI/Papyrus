/**
 * The public handle (PPY-ffcf98): the rules, the schema, and the three setPublicHandle resolvers run against a recording stand-in
 * for the AppSync runtime. Nothing is deployed and nothing touches AWS.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { schema } from "../amplify/data/schema";
import { checkPublicHandle, publicHandleRefusalMessage } from "../lib/public-handle";

const root = join(import.meta.dirname, "..");
const read = (file: string) => readFileSync(join(root, file), "utf8");
const vectors = JSON.parse(read("scripts/fixtures/public-handle-vectors.json")) as {
  reserved: string[];
  vectors: Array<{ input: string; valid: boolean; handle?: string; reason?: string }>;
};

type Transformed = { schema: string; jsFunctions: Array<{ typeName: string; fieldName: string; handlers: Array<{ dataSource: string; entry: string | { relativePath: string } }> }> };
const transformed = (schema as unknown as { transform: () => Transformed }).transform();

class AppSyncError extends Error { constructor(message: string, public type: string) { super(message); } }
type Context = { identity?: { sub?: string; groups?: string[] } | null; args: Record<string, unknown>; stash: Record<string, unknown>; result?: unknown; error?: { message: string; type: string } };
type Resolver = { request: (ctx: Context) => Record<string, any>; response: (ctx: Context) => any };

function loadResolver(file: string): Resolver {
  const source = read(`amplify/data/resolvers/${file}`).replace(/^import .*$/gm, "").replace(/^export /gm, "");
  const util = {
    error: (message: string, type: string) => { throw new AppSyncError(message, type); },
    time: { nowISO8601: () => "2026-10-31T12:00:00.000Z" },
  };
  const ddb = {
    query: (o: object) => ({ op: "query", ...o }),
    get: (o: object) => ({ op: "get", ...o }),
    update: (o: object) => ({ op: "update", ...o }),
    operations: { replace: (value: unknown) => ({ replace: value }), remove: () => ({ remove: true }) },
  };
  return new Function("util", "ddb", `${source}\nreturn { request, response };`)(util, ddb) as Resolver;
}
const refused = (run: () => unknown, pattern: RegExp) => assert.throws(run, (error) => error instanceof AppSyncError && pattern.test(error.message));
const context = (args: Record<string, unknown>, stash: Record<string, unknown> = {}, identity: Context["identity"] = { sub: "sub-alice", groups: ["editor"] }): Context => ({ identity, args, stash });

test("the rules accept and refuse the shared vectors", () => {
  for (const vector of vectors.vectors) {
    const result = checkPublicHandle(vector.input);
    assert.equal(result.valid, vector.valid, JSON.stringify(vector.input));
    if (result.valid) assert.equal(result.handle, vector.handle, JSON.stringify(vector.input));
    else assert.equal(result.reason, vector.reason, JSON.stringify(vector.input));
  }
});

test("a refusal says what to fix in words", () => {
  assert.equal(publicHandleRefusalMessage("length"), "3 to 24 letters, digits and hyphens");
  assert.equal(publicHandleRefusalMessage("at-sign"), "3 to 24 letters, digits and hyphens");
  assert.match(publicHandleRefusalMessage("reserved"), /reserved/);
});

test("the resolver applies the same rules as the library to every shared vector", () => {
  const { request } = loadResolver("set-public-handle-check.js");
  for (const vector of vectors.vectors.filter((entry) => entry.input.trim() !== "")) {
    const ctx = context({ handle: vector.input }, { profileId: "p1" });
    if (vector.valid) {
      const op = request(ctx);
      assert.equal(op.op, "query", vector.input);
      assert.equal(ctx.stash.handle, vector.handle, "the handle is stored lowercase");
    } else {
      refused(() => request(ctx), vector.reason === "reserved" ? /reserved/ : /3 to 24 letters, digits and hyphens/);
    }
  }
});

test("the identity step finds the caller's own profile from the sub, and nothing else", () => {
  const { request, response } = loadResolver("set-public-handle-find-profile.js");
  refused(() => request(context({ handle: "ryan" }, {}, null)), /Sign in/);
  const op = request(context({ handle: "ryan", profileId: "profile-of-someone-else" }));
  assert.deepEqual(op.query, { cognitoSub: { eq: "sub-alice" } }, "the lookup is by the signed-in sub; a profile id argument is never read");
  assert.equal(op.index, "userIdentitiesByCognitoSub");
  const ctx = context({}, {});
  ctx.result = { items: [{ status: "revoked", userProfileId: "old" }, { status: "active", userProfileId: "profile-alice" }] };
  response(ctx);
  assert.equal(ctx.stash.profileId, "profile-alice");
  const none = context({}, {});
  none.result = { items: [] };
  refused(() => response(none), /Open Settings once/);
});

test("a handle another profile already uses is refused, and the caller's own is not", () => {
  const { request, response } = loadResolver("set-public-handle-check.js");
  const ctx = context({ handle: "Ryan" }, { profileId: "profile-alice" });
  const op = request(ctx);
  assert.equal(op.index, "userProfilesByPublicHandle");
  assert.deepEqual(op.query, { publicHandle: { eq: "ryan" } });
  ctx.result = { items: [{ id: "profile-bob" }] };
  refused(() => response(ctx), /That handle is taken/);
  ctx.result = { items: [{ id: "profile-alice" }] };
  assert.doesNotThrow(() => response(ctx));
  ctx.result = { items: [] };
  assert.doesNotThrow(() => response(ctx));
});

test("clearing the handle skips the checks and removes the attribute", () => {
  const check = loadResolver("set-public-handle-check.js");
  for (const handle of [null, "", "   "]) {
    const ctx = context({ handle }, { profileId: "profile-alice" });
    assert.equal(check.request(ctx).op, "get");
    assert.equal(ctx.stash.handle, null);
    ctx.result = { id: "profile-alice" };
    assert.doesNotThrow(() => check.response(ctx));
  }
  const write = loadResolver("set-public-handle-write.js");
  const op = write.request(context({}, { profileId: "profile-alice", handle: null }));
  assert.deepEqual(op.update.publicHandle, { remove: true }, "the attribute goes, so the unique index holds only handles that are set");
  assert.deepEqual(op.update.updatedAt, { replace: "2026-10-31T12:00:00.000Z" });
});

test("the write names the caller's profile, sets handle and time, and never creates a profile", () => {
  const write = loadResolver("set-public-handle-write.js");
  const op = write.request(context({ handle: "ignored", profileId: "profile-other" }, { profileId: "profile-alice", handle: "ryan" }));
  assert.deepEqual(op.key, { id: "profile-alice" });
  assert.deepEqual(op.update.publicHandle, { replace: "ryan" });
  assert.deepEqual(op.condition, { id: { attributeExists: true } });
  refused(() => write.response({ ...context({}), error: { message: "x", type: "DynamoDB:ConditionalCheckFailedException" } }), /profile was not found/);
});

test("the schema carries the field, the unique index and a self-only mutation open to editors and admins", () => {
  const start = transformed.schema.indexOf("type UserProfile @model");
  const block = transformed.schema.slice(start, transformed.schema.indexOf("\n}\n", start));
  assert.match(block, /publicHandle: String/);
  assert.match(block, /@index\(name: "userProfilesByPublicHandle", queryField: "userProfileByPublicHandle"\)/);
  assert.match(transformed.schema, /setPublicHandle\(handle: String\): UserProfile/);
  const mutationLine = transformed.schema.split("\n").find((line) => line.includes("setPublicHandle(")) ?? "";
  assert.doesNotMatch(mutationLine, /profileId|id:/i, "the mutation has no way to name a profile");
  assert.match(mutationLine, /cognito_groups|@aws_cognito_user_pools/, "the mutation is limited to signed-in groups");
  const pipeline = transformed.jsFunctions.filter((entry) => entry.fieldName === "setPublicHandle").flatMap((entry) => entry.handlers);
  assert.deepEqual(pipeline.map((handler) => handler.dataSource), ["UserIdentityTable", "UserProfileTable", "UserProfileTable"]);
  for (const handler of pipeline) {
    const entry = typeof handler.entry === "string" ? handler.entry : handler.entry.relativePath;
    assert.ok(entry.startsWith("/"), `${entry} is an absolute path`);
  }
});
