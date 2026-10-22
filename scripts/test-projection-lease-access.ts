import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Template } from "aws-cdk-lib/assertions";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { addProjectionLeaseAccess } from "../amplify/publication/projection-lease";

const stack = new Stack(new App(), "Site", { env: { account: "123456789012", region: "us-east-1" } });
const contentActions = new lambda.Function(stack, "ContentActions", {
  runtime: lambda.Runtime.PYTHON_3_12,
  handler: "handler.handler",
  code: lambda.Code.fromInline("def handler(event, context): return {}"),
});
addProjectionLeaseAccess(contentActions);

const policies = Object.values(Template.fromStack(stack).findResources("AWS::IAM::Policy"));
assert.equal(policies.length, 1);
const statements = policies[0].Properties.PolicyDocument.Statement as Array<{ Effect: string; Action: string | string[]; Resource: string | string[] }>;
const normalized = statements.map((statement) => ({
  effect: statement.Effect,
  actions: [statement.Action].flat().sort(),
  resources: [statement.Resource].flat(),
}));

assert.deepEqual(normalized, [
  {
    effect: "Allow",
    actions: ["ssm:GetParameter"],
    resources: ["arn:aws:ssm:us-east-1:123456789012:parameter/papyrus/projection-lock/table-name"],
  },
  {
    effect: "Allow",
    actions: ["dynamodb:DeleteItem", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:UpdateItem"],
    resources: ["arn:aws:dynamodb:us-east-1:123456789012:table/papyrus-projection-locks*"],
  },
]);
for (const statement of normalized) {
  assert.ok(!statement.resources.includes("*"), "no wildcard resource");
}
