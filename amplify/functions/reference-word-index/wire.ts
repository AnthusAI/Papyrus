import { Duration, RemovalPolicy } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, CfnEventSourceMapping, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { pythonLambdaCode } from "../shared/python-bundle";

/**
 * The References search word index (docs/reference-search.md#word-index): a small DynamoDB table of one row per word per Reference, kept current by a
 * DynamoDB Streams consumer on the Reference table, and read by the `knowledgeQuery` function's `searchReferences` query.
 *
 * Two stacks, because CloudFormation dependencies run between whole stacks: the table stack depends on nothing, so `knowledgeQuery` (which lives with the
 * data API) can name the table; the consumer stack depends on the data API (it needs the Reference table's stream) and on the table.
 *
 * The table is not an Amplify model: it has no GraphQL type, no resolver and no subscription, so no signed-in user, editor or guest can reach it through
 * AppSync. Only the two functions below hold IAM access: the consumer writes it, `knowledgeQuery` queries it. It is derived data (the backfill command
 * rebuilds it), so it carries no point-in-time recovery.
 */
export const WORD_TABLE_ENV = "PAPYRUS_REFERENCE_WORD_TABLE";
export const REFERENCE_TABLE_ENV = "PAPYRUS_REFERENCE_TABLE_NAME";

/** Reads only: a Query of the word table, BatchGetItem of word pointers and Reference rows, and the Reference table's item count. No Scan, no writes. */
export const SEARCH_WORD_TABLE_ACTIONS = ["dynamodb:Query", "dynamodb:BatchGetItem"];
export const SEARCH_REFERENCE_TABLE_ACTIONS = ["dynamodb:BatchGetItem", "dynamodb:DescribeTable"];
/** Writes single rows by key. No Scan, no Query, no batch. */
export const CONSUMER_WORD_TABLE_ACTIONS = ["dynamodb:PutItem", "dynamodb:DeleteItem"];
export const STREAM_READ_ACTIONS = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"];

export type ReferenceWordIndex = {
  tableName: string;
  consumer: LambdaFunction;
};

/**
 * The Reference table's stream, with both images (the consumer writes only the difference between them, so a vote or a star writes nothing).
 * The Amplify table manager's tables (the default here) are a custom resource wrapped in an `AmplifyDynamoDbTableWrapper`; a plain CloudFormation
 * table is found the way the home-page plugin finds it. Both switch the stream on with the same view type the home-page plugin uses, so enabling
 * both features sets one stream, once.
 */
function referenceReadStream(backend: any): string {
  const cfnResources = backend.data.resources.cfnResources;
  const wrapper = cfnResources.amplifyDynamoDbTables?.Reference;
  if (wrapper !== undefined) {
    wrapper.streamSpecification = { streamViewType: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES };
    return wrapper.resource.getAtt("TableStreamArn").toString();
  }
  const cfnTables = cfnResources.cfnTables ?? {};
  const found =
    cfnTables.Reference ??
    cfnTables.ReferenceTable ??
    Object.entries(cfnTables).find(([key]) => key.toLowerCase().replace(/table$/, "") === "reference")?.[1];
  if (!found) throw new Error(`The word index needs the Reference table. cfnTables=${Object.keys(cfnTables).join(",")}`);
  found.streamSpecification = { streamViewType: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES };
  return found.attrStreamArn;
}

export function wireReferenceWordIndex(backend: any, knowledgeQueryLambda: LambdaFunction): ReferenceWordIndex {
  const referenceTable = backend.data.resources.tables.Reference;
  if (!referenceTable) throw new Error("The word index needs the Reference table.");
  const streamArn = referenceReadStream(backend);

  const tableStack = backend.createStack("reference-word-table");
  const wordTable = new dynamodb.Table(tableStack, "ReferenceWordTable", {
    partitionKey: { name: "shard", type: dynamodb.AttributeType.STRING },
    sortKey: { name: "entry", type: dynamodb.AttributeType.STRING },
    billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
    removalPolicy: RemovalPolicy.DESTROY,
  });

  const consumerStack = backend.createStack("reference-word-stream");
  const consumer = new LambdaFunction(consumerStack, "ReferenceWordIndexConsumer", {
    runtime: Runtime.PYTHON_3_12,
    architecture: Architecture.ARM_64,
    handler: "handler.handler",
    timeout: Duration.seconds(60),
    memorySize: 256,
    environment: { [WORD_TABLE_ENV]: wordTable.tableName },
    code: pythonLambdaCode(
      { functionDir: "reference-word-index", modules: ["papyrus_knowledge_query"] },
      [
        "bash",
        "-c",
        [
          "set -euo pipefail",
          "mkdir -p /asset-output/papyrus_knowledge_query",
          "cp amplify/functions/reference-word-index/handler.py /asset-output/handler.py",
          "cp -R src/papyrus_knowledge_query/. /asset-output/papyrus_knowledge_query/",
        ].join(" && "),
      ],
    ),
  });
  consumer.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: CONSUMER_WORD_TABLE_ACTIONS, resources: [wordTable.tableArn] }));
  consumer.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: STREAM_READ_ACTIONS, resources: [streamArn] }));
  new CfnEventSourceMapping(consumerStack, "ReferenceWordIndexStreamMapping", {
    eventSourceArn: streamArn,
    functionName: consumer.functionArn,
    startingPosition: "LATEST",
    batchSize: 100,
    maximumBatchingWindowInSeconds: 5,
    maximumRetryAttempts: 5,
    functionResponseTypes: ["ReportBatchItemFailures"],
  });

  knowledgeQueryLambda.addEnvironment(WORD_TABLE_ENV, wordTable.tableName);
  knowledgeQueryLambda.addEnvironment(REFERENCE_TABLE_ENV, referenceTable.tableName);
  knowledgeQueryLambda.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: SEARCH_WORD_TABLE_ACTIONS, resources: [wordTable.tableArn] }));
  knowledgeQueryLambda.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: SEARCH_REFERENCE_TABLE_ACTIONS, resources: [referenceTable.tableArn] }));

  return { tableName: wordTable.tableName, consumer };
}
