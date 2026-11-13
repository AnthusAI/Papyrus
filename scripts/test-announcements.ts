/**
 * Announcements: the schema, the wiring and the page's plain-words helpers. The function's rules are in
 * features_backend/x-account-connection.feature and announcement-settings.feature; the page is in features/newsroom-announcements.feature.
 */
import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import { AttributeType, Table } from "aws-cdk-lib/aws-dynamodb";
import { Architecture, Code, Function, Runtime } from "aws-cdk-lib/aws-lambda";
import { schema } from "../amplify/data/schema";
import { ANNOUNCEMENT_MUTATION_OPERATIONS, ANNOUNCEMENT_QUERY_OPERATIONS } from "../amplify/functions/announcements/operations";
import { announcementsParameterPrefix, wireAnnouncements, X_ENDPOINTS } from "../amplify/functions/announcements/wire";
import { announcementOperationDocument } from "../lib/announcements-client";
import {
  callbackUrl, connectionWords, failureText, formatDate, formatMoney, modeBlockers, pauseText, setupSteps, toggled, STAR_CHOICES, QUALITY_FLOOR_STARS, type XStatus,
} from "../lib/announcements-model";

// The schema: every operation is group-only and handled by the one function; the models are admin read only.
const base = schema.transform().schema;
for (const name of [...ANNOUNCEMENT_QUERY_OPERATIONS, ...ANNOUNCEMENT_MUTATION_OPERATIONS]) {
  const operation = base.split("\n").find((line) => line.trim().startsWith(`${name}(`)) ?? "";
  assert.ok(operation, `${name} is in the schema`);
  assert.match(operation, /@function/);
  assert.match(operation, (ANNOUNCEMENT_QUERY_OPERATIONS as readonly string[]).includes(name) ? /groups: \["editor", "admin"\]/ : /groups: \["admin"\]\}/, `${name} admits the right groups: ${operation}`);
  assert.equal(/provider: (apiKey|iam|identityPool)|allow: (public|private)|guest/.test(operation), false, `${name} is open to groups only`);
}
for (const model of ["AnnouncementSettings", "XConnection"]) {
  const start = base.indexOf(`type ${model} @model`);
  assert.ok(start >= 0, `${model} is a model`);
  const declaration = base.slice(start, base.indexOf("{\n", start));
  assert.match(declaration, /groups: \["admin"\]/);
  assert.equal(/groups: \["editor"\]/.test(declaration), false, `${model} is not read by editors directly`);
}
assert.equal(announcementOperationDocument("announcementsXStatus"), "query AnnouncementsXStatus($input: AWSJSON) { announcementsXStatus(input: $input) }");
assert.equal(announcementOperationDocument("announcementsXDisconnect"), "mutation AnnouncementsXDisconnect($input: AWSJSON) { announcementsXDisconnect(input: $input) }");

// The wiring: two tables, the endpoints, and parameters under the site's announcements path only.
const app = new App();
const stack = new Stack(app, "Data", { env: { account: "123456789012", region: "us-east-1" } });
const lambda = new Function(stack, "Announcements", { runtime: Runtime.PYTHON_3_12, architecture: Architecture.ARM_64, handler: "handler.handler", code: Code.fromInline("x") });
const table = (id: string) => new Table(stack, id, { partitionKey: { name: "id", type: AttributeType.STRING } });
wireAnnouncements({ announcements: { resources: { lambda } }, data: { resources: { tables: { AnnouncementSettings: table("S"), XConnection: table("C"), Item: table("I") } } } }, "mom");
const template = Template.fromStack(stack);
const variables = Object.values(template.findResources("AWS::Lambda::Function")).map((r) => (r as { Properties: { Environment: { Variables: Record<string, unknown> } } }).Properties.Environment.Variables)[0];
for (const name of ["SITE_ID", "ANNOUNCEMENT_SETTINGS_TABLE", "X_CONNECTION_TABLE", "X_REFRESH_LEASE_SECONDS", ...Object.keys(X_ENDPOINTS)]) assert.ok(name in variables, `${name} is set`);
assert.equal(variables.X_TOKEN_URL, "https://api.x.com/2/oauth2/token");
const policy = JSON.stringify(template.findResources("AWS::IAM::Policy"));
assert.ok(policy.includes("ssm:PutParameter") && policy.includes(`parameter${announcementsParameterPrefix("mom")}/*`), "parameters are limited to the site's announcements path");
assert.equal(/"Fn::GetAtt":\["I"/.test(policy), false, "no other table");

// The page's words.
assert.equal(callbackUrl("https://mom.example/", "/newsroom"), "https://mom.example/newsroom/settings/announcements/x/callback");
assert.equal(callbackUrl("https://news.example", ""), "https://news.example/settings/announcements/x/callback");
assert.deepEqual([...STAR_CHOICES], [3, 4, 5]);
assert.equal(QUALITY_FLOOR_STARS, 3);
assert.equal(setupSteps("https://x/cb").length, 6);
assert.equal(setupSteps("https://x/cb").filter((step) => step.copy).length, 1);
assert.equal(formatMoney(0.2), "$0.20");
assert.equal(formatMoney(0.015), "$0.015");
assert.equal(formatDate("2026-11-12"), "12 Nov 2026");
assert.deepEqual(toggled(["a"], "b"), ["a", "b"]);
assert.deepEqual(toggled(["a", "b"], "a"), ["b"]);
const notPaused = { paused: false, reason: null, detail: null, by: null, at: null } as const;
assert.equal(pauseText(notPaused), "Posts follow the mode below.");
assert.equal(pauseText({ paused: true, reason: "manual", detail: "Paused by hand.", by: "Ryan", at: "2026-11-13T10:02:00Z" }), "Paused by Ryan, 13 Nov 10:02 UTC: paused by hand.");
assert.match(pauseText({ paused: true, reason: "budget", detail: null, by: "system", at: "2026-11-13T10:02:00Z" }), /budget for this X billing cycle was reached/);
assert.match(pauseText({ paused: true, reason: "disconnected", detail: "X refused.", by: "system", at: null }), /the X account is not connected\. X refused\./);
const status = (connection: XStatus["connection"]): XStatus => ({ clientId: "c", secretSaved: true, secretSavedAt: null, connection, handle: "mom_test", accountId: "1", scopes: [], connectedAt: null, lastRefreshAt: null, refreshHealth: { healthy: connection === "connected", error: null } });
assert.equal(connectionWords(status("connected")), "Connected: @mom_test");
assert.equal(connectionWords(status("needs_reconnecting")), "Needs reconnecting (@mom_test)");
assert.deepEqual(modeBlockers("off", { budget: null, labelConfirmed: false }, status("not_connected")), []);
assert.deepEqual(modeBlockers("dry_run", { budget: null, labelConfirmed: false }, status("not_connected")), ["Connect an X account first."]);
assert.equal(modeBlockers("on", { budget: null, labelConfirmed: false }, status("connected")).length, 2);
assert.deepEqual(modeBlockers("on", { budget: 10, labelConfirmed: true }, status("connected")), []);
assert.equal(failureText({ ok: false, error: "forbidden" }), "Your role cannot do this.");
assert.equal(failureText({ ok: false, error: "x", message: "Plain words." }), "Plain words.");

console.log("announcements ok");
