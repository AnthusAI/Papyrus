/**
 * Translate on publish (docs/story-translation-procedure.md): the stream consumer on the LocalizationRequest table, synthesized with a stand-in backend.
 * A cross-stack dependency cycle between the data API, the content-actions function and the new stack fails the synth.
 */
import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { CfnGraphQLApi } from "aws-cdk-lib/aws-appsync";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { CONTENT_ACTIONS_ENV, DISPATCH_API_FIELDS, wireLocalizationDispatch } from "../amplify/functions/localization-dispatch/wire";

const app = new App();
const env = { account: "123456789012", region: "us-east-1" };
const dataStack = new Stack(app, "data", { env });
const table = new dynamodb.Table(dataStack, "LocalizationRequestTable", { partitionKey: { name: "id", type: dynamodb.AttributeType.STRING } });
const api = new CfnGraphQLApi(dataStack, "Api", { name: "site", authenticationType: "AWS_IAM" });
const functionStack = new Stack(app, "functions", { env });
const contentActions = new LambdaFunction(functionStack, "ContentActions", {
  runtime: Runtime.PYTHON_3_12,
  handler: "handler.handler",
  code: Code.fromInline("def handler(event, context): return {}"),
});
const backend = {
  data: {
    resources: {
      tables: { LocalizationRequest: table },
      cfnResources: { cfnTables: { LocalizationRequest: table.node.defaultChild }, cfnGraphqlApi: api },
      graphqlApi: { apiId: api.attrApiId },
    },
  },
  createStack: (name: string) => new Stack(app, name, { env }),
};

wireLocalizationDispatch(backend, contentActions, "sample-site");
const assembly = app.synth();   // throws on a dependency cycle between stacks
const stack = (name: string): Template => Template.fromJSON(assembly.getStackByName(name).template);

// The table streams old and new images: the dispatcher compares them to tell a fresh request from its own put-back.
stack("data").hasResourceProperties("AWS::DynamoDB::Table", { StreamSpecification: { StreamViewType: "NEW_AND_OLD_IMAGES" } });

// The consumer reads the stream in small batches and reports the records that failed, so Lambda retries only those.
const dispatcher = stack("localization-dispatch");
dispatcher.hasResourceProperties("AWS::Lambda::EventSourceMapping", { FunctionResponseTypes: ["ReportBatchItemFailures"], StartingPosition: "LATEST", BatchSize: 10 });
dispatcher.hasResourceProperties("AWS::Lambda::Function", {
  Environment: { Variables: Match.objectLike({ PAPYRUS_GRAPHQL_AUTH: "iam", PAPYRUS_MONITORING_TABLE_PARAMETER: Match.anyValue(), [CONTENT_ACTIONS_ENV]: Match.anyValue() }) },
});

// Its rights are the ones the dispatcher uses and no more: a few fields of its own site's API, the monitoring table (read, and one Run now row in a
// monitor's partition), the site's own wake queue (look it up and send to it, nothing more) and the content-actions function.
const policies = JSON.stringify(dispatcher.findResources("AWS::IAM::Policy"));
for (const field of DISPATCH_API_FIELDS) assert.ok(policies.includes(`types/${field}`), field);
assert.ok(policies.includes("papyrus-sample-site-agent-wakes.fifo") && policies.includes("sqs:SendMessage") && policies.includes("sqs:GetQueueUrl"), "it puts wakes on its site's queue");
assert.ok(!policies.includes("papyrus-procedure-runner"), "it no longer starts the runner itself");
assert.ok(!policies.includes("sqs:ReceiveMessage") && !policies.includes("sqs:DeleteMessage") && !policies.includes("sqs:*"), "it may not read or delete wakes");
assert.ok(policies.includes("dynamodb:PutItem") && policies.includes("MONITOR#*"), "it writes Run now's row in a monitor's partition");
for (const forbidden of ["dynamodb:Scan", "dynamodb:DeleteItem", "dynamodb:UpdateItem", "dynamodb:*", "lambda:*", "Query/fields/*", "Mutation/fields/*"]) {
  assert.ok(!policies.includes(forbidden), `the dispatcher must not hold ${forbidden}`);
}

console.log("localization dispatch: ok");
