import assert from "node:assert/strict";
import { schema } from "../amplify/data/schema";
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

console.log("monitoring view backend: ok");
