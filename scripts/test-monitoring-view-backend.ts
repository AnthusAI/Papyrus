import assert from "node:assert/strict";
import { schema } from "../amplify/data/schema";
import { firstPipRequirements } from "../amplify/functions/shared/python-bundle";
import { MONITORING_VIEW_TIMEOUT_SECONDS } from "../amplify/functions/monitoring-view/resource";
import {
  MONITORING_TABLE_PARAMETER,
  MONITORING_VIEW_TABLE_ACTIONS,
  monitoringViewParameterArn,
  monitoringViewTableArns,
} from "../amplify/functions/monitoring-view/wire";

// One query, admitted for editors and admins only: a reader or guest never reaches the function.
const text = schema.transform().schema;
const query = /monitoringOverview\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(query, "the base schema defines monitoringOverview");
assert.match(query, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/, "editors and admins only");
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(query), "no public, API-key or guest access");
const emailQuery = /monitoringEmailSubmission\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(emailQuery, "the base schema defines the private email detail query");
assert.match(emailQuery, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/,
  "email details are limited to editors and admins");

const handoffMutation = /monitoringQueueEmailReference\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(handoffMutation, "the base schema defines the selected Reference handoff");
assert.match(handoffMutation, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/);
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(handoffMutation));

// Accept/Reject of a held email submission is an editor/admin mutation, never public.
const decideMutation = /monitoringDecideEmailSubmission\([^)]*\): AWSJSON[^\n]*/.exec(text)?.[0] ?? "";
assert.ok(decideMutation, "the base schema defines the held-message decision");
assert.match(decideMutation, /groups: \["editor", "admin"\]|groups: \["editor","admin"\]/);
assert.ok(!/allow: public|allow: private|provider: apiKey|identityPool/.test(decideMutation));
assert.match(decideMutation, /receiptId: String!/);

// The resolver finishes inside AppSync's 30 second limit.
assert.ok(MONITORING_VIEW_TIMEOUT_SECONDS < 30);

// The IAM grant can read one item or one key range of the monitoring table, and nothing else.
assert.deepEqual([...MONITORING_VIEW_TABLE_ACTIONS].sort(), ["dynamodb:GetItem", "dynamodb:Query"]);
const arns = monitoringViewTableArns("us-east-1", "712236451410");
assert.deepEqual(arns, [
  "arn:aws:dynamodb:us-east-1:712236451410:table/papyrus-monitoring-MonitoringTable-*",
  "arn:aws:dynamodb:us-east-1:712236451410:table/papyrus-monitoring-MonitoringTable-*/index/routing",
]);
assert.ok(arns.every((arn) => arn.includes("papyrus-monitoring-MonitoringTable-")), "scoped to the monitoring stack's table");
assert.equal(MONITORING_TABLE_PARAMETER, "/papyrus/monitoring/table-name");
assert.equal(monitoringViewParameterArn("us-east-1", "712236451410"), "arn:aws:ssm:us-east-1:712236451410:parameter/papyrus/monitoring/table-name");

// A function with no dependencies of its own (this one) must not hand pip an empty requirement list; that failed the first site build.
assert.deepEqual(firstPipRequirements({ noDeps: true }), []);
assert.deepEqual(firstPipRequirements({ noDeps: true, requirements: ["humanus[jev]>=0.33,<0.34"] }), ["humanus[jev]>=0.33,<0.34"]);
assert.equal(firstPipRequirements({}).length, 1, "with dependencies, papyrus-newsroom itself is the requirement");

console.log("monitoring view backend: ok");
