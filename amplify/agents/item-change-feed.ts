import { Duration, Stack } from "aws-cdk-lib";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, CfnEventSourceMapping, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { pythonLambdaCode } from "../functions/shared/python-bundle";
import { connectToSiteApi } from "../site-api-access";
import { tableStream } from "./stream-readers";
import { setModelKeyParameter } from "./model-key";
import { allowWakeSending } from "./wake-queue";
import type { AgentPiece } from "./stack";

/**
 * The Item change feed (docs/design/always-on-agents-architecture.md, slice B2, PPY-8a374e): a DynamoDB stream consumer on the Item table that turns each
 * change to a Story or its checklist into one wake per listening agent on the site's wake queue. All the logic is src/papyrus_content/item_change_feed.py;
 * the handler is amplify/functions/item-change-feed/handler.py.
 *
 * This piece holds four resources: the function, its role and its policy, and the mapping from the stream. It creates no queue and no alarm: the queue is the
 * wake-queue piece, and the alarm on feed lag is the observability slice's (PPY-45ef76). The stream itself is a property of the Item table, switched on by
 * `enableItemStream` (the Item table had no stream and no reader before this; it holds one reader now, the feed).
 *
 * What the function may do, and nothing else: read the Item stream; read the site's `SiteDocument` rows through its own site's API (`getSiteDocument`: the live
 * version of the listener index) and that one document's objects in the site's bucket (`tenants/<tenant>/site/listeners/`); look up and send to its own
 * site's wake queue. It reads no table, receives and deletes no wake, and calls no model.
 */

export const ITEM_STREAM_VIEW = dynamodb.StreamViewType.NEW_AND_OLD_IMAGES;
export const ITEM_FEED_API_FIELDS = ["Query/fields/getSiteDocument"];
export const LISTENER_INDEX_KIND = "listeners";
const STREAM_READ_ACTIONS = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"];

/** What the feed needs from the rest of the site's backend. Absent for a backend that cannot run it (a shared stack, which acts for no one tenant). */
export type ItemChangeFeedSource = {
  /** The Item table's stream ARN (`enableItemStream`). */
  streamArn: string;
  graphqlUrl: string;
  apiId: string;
  tenantId: string;
  bucketName: string;
  bucketArn: string;
  /** The NAME of the SSM parameter the runs this feed wakes read their model key from (`agents.openAiKeyParameter`; see `model-key.ts`). Unset: the wakes carry none. */
  openAiKeyParameter?: string;
};

/**
 * Switches on the Item table's stream, with both images (the feed compares them to tell a board move from any other update), and returns its ARN.
 * The Item table had no stream before. Returns undefined when the site's schema has no Item table.
 */
export function enableItemStream(backend: any): string | undefined {
  return tableStream(backend, "Item", ITEM_STREAM_VIEW);
}

export function itemChangeFeedPiece(brandId: string, source: ItemChangeFeedSource): AgentPiece {
  return {
    id: "item-change-feed",
    add(scope: Construct) {
      const stack = Stack.of(scope);
      const feed = new LambdaFunction(scope, "ItemChangeFeed", {
        runtime: Runtime.PYTHON_3_12,
        architecture: Architecture.ARM_64,
        handler: "handler.handler",
        timeout: Duration.seconds(60),
        memorySize: 256,
        description: "Puts a wake on the site's agent wake queue for each agent that listens for a change to a Story or its checklist (PPY-8a374e).",
        code: pythonLambdaCode(
          { functionDir: "item-change-feed", modules: ["papyrus_content"], noDeps: true },
          [
            "bash",
            "-c",
            [
              "set -euo pipefail",
              "mkdir -p /asset-output/papyrus_content",
              "cp amplify/functions/item-change-feed/handler.py /asset-output/handler.py",
              "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
            ].join(" && "),
          ],
        ),
      });
      connectToSiteApi(feed, source.graphqlUrl);
      feed.addEnvironment("PAPYRUS_AGENT_PUBLICATION_ID", brandId);
      feed.addEnvironment("PAPYRUS_TENANT_ID", source.tenantId);
      feed.addEnvironment("PAPYRUS_SITE_BUCKET", source.bucketName);
      setModelKeyParameter(feed, source.openAiKeyParameter);
      feed.addToRolePolicy(
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ["appsync:GraphQL"],
          resources: ITEM_FEED_API_FIELDS.map((field) => `arn:${stack.partition}:appsync:${stack.region}:${stack.account}:apis/${source.apiId}/types/${field}`),
        }),
      );
      feed.addToRolePolicy(
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ["s3:GetObject"],
          resources: [`${source.bucketArn}/tenants/${source.tenantId}/site/${LISTENER_INDEX_KIND}/*`],
        }),
      );
      allowWakeSending(feed, brandId);
      feed.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: STREAM_READ_ACTIONS, resources: [source.streamArn] }));
      new CfnEventSourceMapping(scope, "ItemStreamMapping", {
        eventSourceArn: source.streamArn,
        functionName: feed.functionArn,
        startingPosition: "LATEST",
        batchSize: 10,
        maximumBatchingWindowInSeconds: 2,
        maximumRetryAttempts: 5,
        functionResponseTypes: ["ReportBatchItemFailures"],
        // A removed row is never a change the feed acts on: it does not start the function.
        filterCriteria: { filters: [{ pattern: JSON.stringify({ eventName: ["INSERT", "MODIFY"] }) }] },
      });
    },
  };
}
