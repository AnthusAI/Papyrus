import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { addScheduledPublishing, MAXIMUM_SITE_ID_LENGTH, scheduleNamePrefix } from "../amplify/publication/scheduled-publishing";
import { isIanaTimeZone, validatePublicationConfig } from "../amplify/site-backend-config";

// The publication's time zone is a real IANA name or the config is refused.
assert.ok(isIanaTimeZone("America/New_York") && isIanaTimeZone("Europe/London") && isIanaTimeZone("America/Argentina/Buenos_Aires") && isIanaTimeZone("UTC"));
for (const bad of ["", "New York", "EST5EDT-ish", "Mars/Olympus_Mons", 5, undefined, "America/"]) assert.ok(!isIanaTimeZone(bad), `${String(bad)} is not a zone`);
assert.deepEqual(validatePublicationConfig({ kind: "s3-projection", timeZone: "America/New_York" }), []);
assert.deepEqual(validatePublicationConfig({ kind: "s3-projection", timeZone: "Mars/Olympus_Mons" }), ["publication.timeZone must be an IANA time zone name such as America/New_York"]);

// A schedule name is at most 64 characters, so the site id has a limit and is refused past it.
assert.equal(scheduleNamePrefix("mom"), "papyrus-pub-mom-");
assert.equal(MAXIMUM_SITE_ID_LENGTH, 35);
assert.throws(() => scheduleNamePrefix("x".repeat(36)), /site id/);
assert.throws(() => scheduleNamePrefix("Not Valid"), /site id/);

const stack = new Stack(new App(), "Site", { env: { account: "123456789012", region: "us-east-1" } });
const contentActions = new lambda.Function(stack, "ContentActions", {
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: "handler.handler",
  code: lambda.Code.fromInline("def handler(event, context): return {}"),
});
assert.throws(() => addScheduledPublishing(contentActions, { siteId: "mom", timeZone: "Nowhere/Land" }), /IANA/);
const wired = addScheduledPublishing(contentActions, { siteId: "mom", timeZone: "America/New_York" });
assert.equal(wired.namePrefix, "papyrus-pub-mom-");
const template = Template.fromStack(stack);

// The settings the function reads: the zone, the role, the dead letter queue and the name prefix.
const variables = Object.values(template.findResources("AWS::Lambda::Function"))[0].Properties.Environment.Variables as Record<string, unknown>;
assert.equal(variables.PAPYRUS_PUBLICATION_TIME_ZONE, "America/New_York");
assert.equal(variables.PAPYRUS_SCHEDULE_NAME_PREFIX, "papyrus-pub-mom-");
assert.ok(variables.PAPYRUS_SCHEDULER_ROLE_ARN && variables.PAPYRUS_SCHEDULER_DEAD_LETTER_ARN);

// Scheduler assumes one role, in this account only; it may invoke this function and send to the dead letter queue, and nothing else.
template.hasResourceProperties("AWS::IAM::Role", {
  AssumeRolePolicyDocument: { Statement: [Match.objectLike({ Principal: { Service: "scheduler.amazonaws.com" }, Condition: { StringEquals: { "aws:SourceAccount": "123456789012" } } })] },
});
const policies = Object.values(template.findResources("AWS::IAM::Policy")).map((policy) => policy.Properties.PolicyDocument.Statement as Array<{ Action: string | string[]; Resource: unknown; Condition?: unknown }>);
const statements = policies.flat();
const actions = (statement: { Action: string | string[] }) => [statement.Action].flat().sort();
const invoke = statements.filter((statement) => actions(statement).includes("lambda:InvokeFunction"));
assert.equal(invoke.length, 1);
const send = statements.filter((statement) => actions(statement).includes("sqs:SendMessage"));
assert.equal(send.length, 1);
const manage = statements.find((statement) => actions(statement).includes("scheduler:CreateSchedule"));
assert.deepEqual(actions(manage!), ["scheduler:CreateSchedule", "scheduler:DeleteSchedule", "scheduler:UpdateSchedule"]);
assert.equal(JSON.stringify(manage!.Resource), JSON.stringify({ "Fn::Join": ["", ["arn:", { Ref: "AWS::Partition" }, ":scheduler:us-east-1:123456789012:schedule/default/papyrus-pub-mom-*"]] }));
const passRole = statements.find((statement) => actions(statement).includes("iam:PassRole"));
assert.deepEqual(passRole!.Condition, { StringEquals: { "iam:PassedToService": "scheduler.amazonaws.com" } });
for (const statement of statements) {
  const text = JSON.stringify(statement.Resource);
  assert.ok(text !== '"*"', "no wildcard resource");
}

// The function names the role and the queue, and the role's policy names the function: CloudFormation must be able to order them (no cycle).
const resources = template.toJSON().Resources as Record<string, { DependsOn?: string | string[] }>;
const edges = new Map<string, Set<string>>();
for (const [id, resource] of Object.entries(resources)) {
  const found = new Set<string>([resource.DependsOn ?? []].flat());
  JSON.stringify(resource, (_key, value) => {
    if (value && typeof value === "object") {
      if (typeof value.Ref === "string" && value.Ref in resources) found.add(value.Ref);
      const attribute = value["Fn::GetAtt"];
      if (Array.isArray(attribute) && attribute[0] in resources) found.add(attribute[0]);
    }
    return value;
  });
  found.delete(id);
  edges.set(id, found);
}
const done = new Set<string>();
const visiting = new Set<string>();
const visit = (id: string): void => {
  assert.ok(!visiting.has(id), `circular dependency through ${id}`);
  if (done.has(id)) return;
  visiting.add(id);
  for (const next of edges.get(id) ?? []) visit(next);
  visiting.delete(id);
  done.add(id);
};
for (const id of edges.keys()) visit(id);

// An undeliverable event is kept two weeks and raises an alarm.
template.hasResourceProperties("AWS::SQS::Queue", { MessageRetentionPeriod: 14 * 24 * 60 * 60, SqsManagedSseEnabled: true });
template.hasResourceProperties("AWS::CloudWatch::Alarm", {
  MetricName: "ApproximateNumberOfMessagesVisible",
  Namespace: "AWS/SQS",
  Threshold: 1,
  ComparisonOperator: "GreaterThanOrEqualToThreshold",
  TreatMissingData: "notBreaching",
});
console.log("scheduled publishing wiring ok");
