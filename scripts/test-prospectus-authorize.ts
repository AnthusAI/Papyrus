/**
 * Fail-closed Prospectus authorization, TypeScript side: the Lambda helper twin (lib/prospectus-authorize.ts), the AppSync
 * pipeline function (amplify/data/resolvers/prospectus-authorize.js, run here against a stand-in for `@aws-appsync/utils`),
 * and the wiring that is only present when a site turns the flag on. Recorded answers use made-up ids. Nothing touches AWS.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { test } from "node:test";
import { a } from "@aws-amplify/backend";
import { baseModelNames, schemaWithPlugins } from "../amplify/data/schema";
import { planProspectusAuthorize, prospectusAuthorizeSchemaDefinitions } from "../amplify/data/prospectus-authorize-backend";
import {
  AccountRequired,
  AuthorizationDenied,
  authorize,
  isSiteFunctionCaller,
  operationFor,
  ReenrollmentRequired,
  requireAuthorized,
  type ProspectusTransport,
} from "../lib/prospectus-authorize";

const root = join(import.meta.dirname, "..");
const ACCOUNT = "acct-0001";
const OTHER_ACCOUNT = "acct-0002";
const ENDPOINT = "https://abc123defg.execute-api.us-east-1.amazonaws.com/api/";
const ENABLED = { PAPYRUS_PROSPECTUS_AUTHORIZE: "true", PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: ENDPOINT };
const ALLOWED = { allowed: true, accountId: ACCOUNT, personId: "person-0001", product: "papyrus-example", role: "owner", operation: "console:write", revision: 3 };
const PERSON_EVENT = {
  identity: { sub: "sub-0001", claims: { sub: "sub-0001" } },
  request: { headers: { "X-Prospectus-Account": ACCOUNT, "X-Prospectus-Human-Token": "token-0001" } },
};

function recorder(status: number, body: unknown) {
  const calls: Array<{ url: string; headers: Record<string, string>; body: unknown }> = [];
  const transport: ProspectusTransport = async (url, headers, text) => {
    calls.push({ url, headers, body: JSON.parse(text) });
    return { status, body };
  };
  return { calls, transport };
}

test("an allowed decision for the requested account lets the operation proceed", async () => {
  const { calls, transport } = recorder(200, ALLOWED);
  const decision = await authorize(ACCOUNT, "console:write", "token-0001", { endpoint: ENDPOINT, transport });
  assert.equal(decision.allowed, true);
  assert.equal(calls[0].url, `${ENDPOINT}v1/accounts/${ACCOUNT}/authorize`);
  assert.equal(calls[0].headers["x-prospectus-human-token"], "token-0001");
  assert.deepEqual(calls[0].body, { operation: "console:write" });
});

test("a decision for a different account is treated as denied", async () => {
  const { transport } = recorder(200, { ...ALLOWED, accountId: OTHER_ACCOUNT });
  const decision = await authorize(ACCOUNT, "console:write", "token-0001", { endpoint: ENDPOINT, transport });
  assert.equal(decision.allowed, false);
  assert.equal(decision.reason, "account_mismatch");
});

test("reenrollment_required is raised for 401 and 403 and nothing else is swallowed into it", async () => {
  for (const status of [401, 403]) {
    const { transport } = recorder(status, { error: "reenrollment_required" });
    await assert.rejects(authorize(ACCOUNT, "console:read", "t", { endpoint: ENDPOINT, transport }), ReenrollmentRequired);
  }
  assert.equal((await authorize(ACCOUNT, "console:read", "t", { endpoint: ENDPOINT, transport: recorder(403, { error: "forbidden" }).transport })).reason, "forbidden");
});

test("Prospectus unreachable, failing or unconfigured denies the operation", async () => {
  const unreachable: ProspectusTransport = async () => { throw new Error("unreachable"); };
  assert.equal((await authorize(ACCOUNT, "console:read", "t", { endpoint: ENDPOINT, transport: unreachable })).reason, "prospectus_unavailable");
  assert.equal((await authorize(ACCOUNT, "console:read", "t", { endpoint: ENDPOINT, transport: recorder(503, {}).transport })).reason, "prospectus_unavailable");
  const untouched = recorder(200, ALLOWED);
  assert.equal((await authorize(ACCOUNT, "console:read", "t", { endpoint: "", environment: {}, transport: untouched.transport })).reason, "prospectus_unavailable");
  assert.equal((await authorize(ACCOUNT, "console:read", "", { endpoint: ENDPOINT, transport: untouched.transport })).reason, "human_token_required");
  assert.equal((await authorize("../other", "console:read", "t", { endpoint: ENDPOINT, transport: untouched.transport })).reason, "account_invalid");
  assert.equal(untouched.calls.length, 0, "no request went out for any of those");
});

test("a request without X-Prospectus-Account is refused as account_required", async () => {
  const event = { ...PERSON_EVENT, request: { headers: { "X-Prospectus-Human-Token": "token-0001" } } };
  await assert.rejects(requireAuthorized(event, "publishItem", { environment: ENABLED, transport: recorder(200, ALLOWED).transport }), AccountRequired);
});

test("a person is allowed or refused by the decision, and with the flag off nothing is asked", async () => {
  assert.equal((await requireAuthorized(PERSON_EVENT, "publishItem", { environment: ENABLED, transport: recorder(200, ALLOWED).transport }))?.allowed, true);
  await assert.rejects(requireAuthorized(PERSON_EVENT, "publishItem", { environment: ENABLED, transport: recorder(403, {}).transport }), AuthorizationDenied);
  const untouched = recorder(403, {});
  assert.equal(await requireAuthorized(PERSON_EVENT, "publishItem", { environment: {}, transport: untouched.transport }), null);
  assert.equal(untouched.calls.length, 0);
});

test("the site's own IAM functions are not subject to the human authorize check", async () => {
  const machine = { userArn: "arn:aws:sts::123456789012:assumed-role/site-function/session", accountId: "123456789012" };
  const untouched = recorder(403, {});
  assert.equal(isSiteFunctionCaller(machine), true);
  assert.equal(await requireAuthorized({ identity: machine, request: { headers: {} } }, "publishItem", { environment: ENABLED, transport: untouched.transport }), null);
  assert.equal(untouched.calls.length, 0);
  assert.equal(isSiteFunctionCaller({ ...machine, cognitoIdentityId: "identity-0001" }), false);
  assert.equal(isSiteFunctionCaller({ ...machine, sub: "sub-0001" }), false);
  assert.equal(isSiteFunctionCaller({ ...machine, accountId: "999999999999" }), false);
});

test("operations follow the field name", () => {
  assert.equal(operationFor("saveItemDraft"), "console:write");
  assert.equal(operationFor("listNewsroomProcedureDefinitions"), "console:read");
  assert.equal(operationFor("getAccountMembers"), "members:read");
});

class AppSyncError extends Error { constructor(message: string, public type: string) { super(message); } }
class EarlyReturn extends Error { constructor(public value: unknown) { super("early return"); } }

function loadPipelineFunction() {
  const source = readFileSync(join(root, "amplify/data/resolvers/prospectus-authorize.js"), "utf8").replace(/^import .*$/gm, "").replace(/^export /gm, "");
  const util = {
    error: (message: string, type: string) => { throw new AppSyncError(message, type); },
    unauthorized: () => { throw new AppSyncError("Unauthorized", "UnauthorizedException"); },
  };
  const runtime = { earlyReturn: (value: unknown) => { throw new EarlyReturn(value); } };
  return new Function("util", "runtime", `${source}\nreturn { request, response };`)(util, runtime) as {
    request: (ctx: unknown) => { method: string; resourcePath: string; params: { headers: Record<string, string>; body: string } };
    response: (ctx: unknown) => unknown;
  };
}
const requestContext = (headers: Record<string, string>, identity: unknown = { sub: "sub-0001", claims: {} }) => ({ identity, request: { headers }, stash: {} as Record<string, unknown> });
const HEADERS = { "x-prospectus-account": ACCOUNT, "x-prospectus-human-token": "token-0001" };
const answer = (ctx: { stash: Record<string, unknown> }, statusCode: number, body: unknown) => ({ ...ctx, stash: ctx.stash, result: { statusCode, body: JSON.stringify(body) } });

test("the pipeline function asks Prospectus for console:write on the named account and lets an allowed answer through", () => {
  const { request, response } = loadPipelineFunction();
  const ctx = requestContext(HEADERS);
  const call = request(ctx);
  assert.equal(call.method, "POST");
  assert.equal(call.resourcePath, `/api/v1/accounts/${ACCOUNT}/authorize`);
  assert.equal(call.params.headers["x-prospectus-human-token"], "token-0001");
  assert.deepEqual(JSON.parse(call.params.body), { operation: "console:write" });
  assert.deepEqual(response(answer(ctx, 200, ALLOWED)), {});
});

test("the pipeline function refuses a missing account, a missing token, another account's answer and anything but a 200 allow", () => {
  const { request, response } = loadPipelineFunction();
  assert.throws(() => request(requestContext({ "x-prospectus-human-token": "t" })), (error) => error instanceof AppSyncError && error.type === "AccountRequired" && error.message === "account_required");
  assert.throws(() => request(requestContext({ "x-prospectus-account": ACCOUNT })), (error) => error instanceof AppSyncError && error.type === "UnauthorizedException");
  assert.throws(() => request(requestContext({ ...HEADERS, "x-prospectus-account": "../x" })), (error) => error instanceof AppSyncError && error.type === "UnauthorizedException");
  const ctx = requestContext(HEADERS);
  request(ctx);
  for (const [status, body] of [[200, { ...ALLOWED, accountId: OTHER_ACCOUNT }], [200, { ...ALLOWED, allowed: false }], [403, { error: "forbidden" }], [500, {}]] as const) {
    assert.throws(() => response(answer(ctx, status, body)), (error) => error instanceof AppSyncError && error.type === "UnauthorizedException", `${status}`);
  }
  assert.throws(() => response({ ...ctx, error: { message: "unreachable", type: "x" }, result: null }), (error) => error instanceof AppSyncError && error.type === "UnauthorizedException");
});

test("reenrollment_required reaches the client as the ReenrollmentRequired error type", () => {
  const { request, response } = loadPipelineFunction();
  const ctx = requestContext(HEADERS);
  request(ctx);
  for (const status of [401, 403]) {
    assert.throws(() => response(answer(ctx, status, { error: "reenrollment_required" })), (error) => error instanceof AppSyncError && error.type === "ReenrollmentRequired" && error.message === "reenrollment_required");
  }
});

test("the site's own IAM functions skip the pipeline function", () => {
  const { request } = loadPipelineFunction();
  const machine = { userArn: "arn:aws:sts::123456789012:assumed-role/site-function/session", accountId: "123456789012" };
  assert.throws(() => request(requestContext({}, machine)), (error) => error instanceof EarlyReturn);
});

type Transformed = { jsFunctions: Array<{ typeName: string; fieldName: string; handlers: Array<{ dataSource: string }> }> };
const pipelineOf = (schemaToCheck: unknown, fieldName: string) =>
  (schemaToCheck as { transform: () => Transformed }).transform().jsFunctions.find((entry) => entry.fieldName === fieldName)!.handlers.map((handler) => handler.dataSource);
const GUARDED_MUTATIONS = ["postMessage", "editMessage", "deleteOwnMessage", "moderateMessage", "renameThread", "setPublicHandle"];

test("with the flag off no account-scoped mutation has the Prospectus step", () => {
  const lean = schemaWithPlugins({});
  for (const field of GUARDED_MUTATIONS) assert.equal(pipelineOf(lean, field).includes("ProspectusAccounts"), false, field);
});

test("with the flag on the Prospectus step is first in each account-scoped mutation's pipeline", () => {
  const guarded = schemaWithPlugins(prospectusAuthorizeSchemaDefinitions());
  for (const field of GUARDED_MUTATIONS) assert.equal(pipelineOf(guarded, field)[0], "ProspectusAccounts", field);
  assert.deepEqual(pipelineOf(guarded, "setPublicHandle").length, 4);
  assert.ok(baseModelNames().length > 0 && a);
});

test("the backend plan is empty when off and strict when on", () => {
  assert.equal(planProspectusAuthorize(false, { PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: "nonsense" }), undefined);
  const plan = planProspectusAuthorize(true, { PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: ENDPOINT })!;
  assert.equal(plan.origin, "https://abc123defg.execute-api.us-east-1.amazonaws.com");
  assert.equal(plan.region, "us-east-1");
  assert.equal(plan.invokeArn, "arn:aws:execute-api:us-east-1:*:abc123defg/api/POST/v1/accounts/*/authorize");
  assert.throws(() => planProspectusAuthorize(true, {}), /PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT/);
  assert.throws(() => planProspectusAuthorize(true, { PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: "https://example.test/api/" }), /execute-api/);
  assert.throws(() => planProspectusAuthorize(true, { PAPYRUS_PROSPECTUS_ACCOUNTS_ENDPOINT: "https://abc123defg.execute-api.us-east-1.amazonaws.com/prod/" }), /\/api\//);
});
