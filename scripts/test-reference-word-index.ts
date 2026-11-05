/**
 * The References search word index (docs/reference-search.md#word-index): the table, its stream consumer and the search function's read access,
 * synthesized with a stand-in backend. A cross-stack dependency cycle between the data API and the new stacks fails the synth.
 */
import assert from "node:assert/strict";
import { App, Stack } from "aws-cdk-lib";
import { Match, Template } from "aws-cdk-lib/assertions";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Code, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import {
  CONSUMER_WORD_TABLE_ACTIONS,
  SEARCH_REFERENCE_TABLE_ACTIONS,
  SEARCH_WORD_TABLE_ACTIONS,
  wireReferenceWordIndex,
} from "../amplify/functions/reference-word-index/wire";

const app = new App();
const env = { account: "123456789012", region: "us-east-1" };
const dataStack = new Stack(app, "data", { env });
const referenceTable = new dynamodb.Table(dataStack, "ReferenceTable", {
  partitionKey: { name: "id", type: dynamodb.AttributeType.STRING },
});
const functionStack = new Stack(app, "functions", { env });
const knowledgeQuery = new LambdaFunction(functionStack, "KnowledgeQuery", {
  runtime: Runtime.PYTHON_3_12,
  handler: "handler.handler",
  code: Code.fromInline("def handler(event, context): return {}"),
});
const backend = {
  data: { resources: { tables: { Reference: referenceTable }, cfnResources: { cfnTables: { Reference: referenceTable.node.defaultChild } } } },
  createStack: (name: string) => new Stack(app, name, { env }),
};

const index = wireReferenceWordIndex(backend, knowledgeQuery);
const assembly = app.synth();   // throws on a dependency cycle between stacks

assert.ok(index.tableName);

function stack(name: string): Template {
  return Template.fromJSON(assembly.getStackByName(name).template);
}

// The Reference table streams old and new images.
stack("data").hasResourceProperties("AWS::DynamoDB::Table", { StreamSpecification: { StreamViewType: "NEW_AND_OLD_IMAGES" } });

// The word table: partition `shard`, sort `entry`, on demand, derived data.
stack("reference-word-table").hasResourceProperties("AWS::DynamoDB::Table", {
  KeySchema: [{ AttributeName: "shard", KeyType: "HASH" }, { AttributeName: "entry", KeyType: "RANGE" }],
  BillingMode: "PAY_PER_REQUEST",
});
assert.equal(Object.keys(stack("reference-word-table").findResources("AWS::DynamoDB::Table")).length, 1);
assert.equal(
  Object.values(stack("reference-word-table").findResources("AWS::DynamoDB::Table"))[0].Properties.GlobalSecondaryIndexes,
  undefined,
  "the word table has no index of its own",
);

// The consumer reads the stream in batches, reporting the records that failed, and may only put and delete rows by key.
const consumerStack = stack("reference-word-stream");
consumerStack.hasResourceProperties("AWS::Lambda::EventSourceMapping", {
  FunctionResponseTypes: ["ReportBatchItemFailures"],
  StartingPosition: "LATEST",
  BatchSize: 100,
});
consumerStack.hasResourceProperties("AWS::IAM::Policy", {
  PolicyDocument: { Statement: Match.arrayWith([Match.objectLike({ Action: CONSUMER_WORD_TABLE_ACTIONS, Effect: "Allow" })]) },
});

// The search function holds read access only, and the actions it holds are the ones the search uses.
const searchPolicies = JSON.stringify(stack("functions").findResources("AWS::IAM::Policy"));
for (const action of [...SEARCH_WORD_TABLE_ACTIONS, ...SEARCH_REFERENCE_TABLE_ACTIONS]) assert.ok(searchPolicies.includes(action), action);
for (const forbidden of ["dynamodb:Scan", "dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:UpdateItem", "dynamodb:*"]) {
  assert.ok(!searchPolicies.includes(forbidden), `the search function must not hold ${forbidden}`);
}
for (const forbidden of ["dynamodb:Scan", "dynamodb:Query", "dynamodb:*"]) {
  assert.ok(!JSON.stringify(consumerStack.findResources("AWS::IAM::Policy")).includes(forbidden), `the consumer must not hold ${forbidden}`);
}
stack("functions").hasResourceProperties("AWS::Lambda::Function", {
  Environment: { Variables: { PAPYRUS_REFERENCE_WORD_TABLE: Match.anyValue(), PAPYRUS_REFERENCE_TABLE_NAME: Match.anyValue() } },
});

console.log("reference word index: ok");
