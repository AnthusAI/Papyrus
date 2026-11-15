import { Duration } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, CfnEventSourceMapping, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import { pythonLambdaCode } from "../shared/python-bundle";
import { connectToSiteApi } from "../../site-api-access";

/**
 * The concept name writer (docs/multilingual-labels.md): a DynamoDB Streams consumer on the SemanticNode table. Every change of a concept, whoever made it,
 * brings that concept's primary-language EntityLabel rows (its name, other names and hashtag) to what its text says, and gives a concept with no language
 * the site's primary language. It calls no model.
 *
 * What it may do, and nothing else: read and write EntityLabel rows, read the label's concept and set its `language`, and read the editorial settings (the
 * primary language) through its own site's API. A shared stack is not wired: its rows carry a tenant this function does not act for.
 */
export const ENTITY_LABEL_SYNC_API_FIELDS = [
  "Query/fields/listEntityLabelsByConceptAndSortKey",
  "Query/fields/getEditorialCheckSettings",
  "Mutation/fields/createEntityLabel",
  "Mutation/fields/updateEntityLabel",
  "Mutation/fields/deleteEntityLabel",
  "Mutation/fields/updateSemanticNode",
];
const STREAM_READ_ACTIONS = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"];

/** The SemanticNode table's stream, with both images (the consumer compares them so that its own writes start no further work). */
function semanticNodeStream(backend: any): string {
  const cfnResources = backend.data.resources.cfnResources;
  const wrapper = cfnResources.amplifyDynamoDbTables?.SemanticNode;
  if (wrapper !== undefined) {
    wrapper.streamSpecification = { streamViewType: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES };
    return wrapper.resource.getAtt("TableStreamArn").toString();
  }
  const cfnTables = cfnResources.cfnTables ?? {};
  const found =
    cfnTables.SemanticNode ??
    cfnTables.SemanticNodeTable ??
    Object.entries(cfnTables).find(([key]) => key.toLowerCase().replace(/table$/, "") === "semanticnode")?.[1];
  if (!found) throw new Error(`The concept name writer needs the SemanticNode table. cfnTables=${Object.keys(cfnTables).join(",")}`);
  found.streamSpecification = { streamViewType: dynamodb.StreamViewType.NEW_AND_OLD_IMAGES };
  return found.attrStreamArn;
}

/** Wires the writer, or nothing when the site's schema leaves out the semantic models (`excludeModelGroups`: no table, no names). */
export function wireEntityLabelSync(backend: any): LambdaFunction | undefined {
  if (!backend.data.resources.tables.SemanticNode || !backend.data.resources.tables.EntityLabel) return undefined;
  const streamArn = semanticNodeStream(backend);
  const stack = backend.createStack("entity-label-sync");
  const writer = new LambdaFunction(stack, "EntityLabelSync", {
    runtime: Runtime.PYTHON_3_12,
    architecture: Architecture.ARM_64,
    handler: "handler.handler",
    timeout: Duration.seconds(60),
    memorySize: 256,
    code: pythonLambdaCode(
      { functionDir: "entity-label-sync", modules: ["papyrus_content"], noDeps: true },
      [
        "bash",
        "-c",
        [
          "set -euo pipefail",
          "mkdir -p /asset-output/papyrus_content",
          "cp amplify/functions/entity-label-sync/handler.py /asset-output/handler.py",
          "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
        ].join(" && "),
      ],
    ),
  });
  connectToSiteApi(writer, backend.data.resources.cfnResources.cfnGraphqlApi.attrGraphQlUrl as string);
  const apiId = backend.data.resources.graphqlApi.apiId as string;
  writer.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["appsync:GraphQL"],
      resources: ENTITY_LABEL_SYNC_API_FIELDS.map((field) => `arn:aws:appsync:${stack.region}:${stack.account}:apis/${apiId}/types/${field}`),
    }),
  );
  writer.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: STREAM_READ_ACTIONS, resources: [streamArn] }));
  new CfnEventSourceMapping(stack, "EntityLabelSyncStreamMapping", {
    eventSourceArn: streamArn,
    functionName: writer.functionArn,
    startingPosition: "LATEST",
    batchSize: 10,
    maximumBatchingWindowInSeconds: 2,
    maximumRetryAttempts: 5,
    functionResponseTypes: ["ReportBatchItemFailures"],
  });
  return writer;
}
