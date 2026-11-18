import { Duration, Stack } from "aws-cdk-lib";
import { Effect, PolicyStatement } from "aws-cdk-lib/aws-iam";
import { Architecture, CfnEventSourceMapping, Function as LambdaFunction, Runtime } from "aws-cdk-lib/aws-lambda";
import type { Construct } from "constructs";
import { pythonLambdaCode } from "../functions/shared/python-bundle";
import { connectToSiteApi } from "../site-api-access";
import { assertLiteralResourceName, sanitizeAwsName } from "../site-backend-names";
import { LISTENER_INDEX_KIND } from "./item-change-feed";
import { FEED_STREAM_VIEW, FEED_TABLES, tableStream, type FeedPlacement, type FeedTable, type StreamReaderId } from "./stream-readers";
import { allowWakeSending } from "./wake-queue";
import type { AgentPiece } from "./stack";

/**
 * The change feeds for Reference, ReviewRequest, Message, LocalizationRequest and Delivery (docs/design/always-on-agents-architecture.md, slice B3, PPY-9b9e64):
 * one function that turns each change to a row of those tables into one wake per listening agent on the site's wake queue. All the logic is
 * src/papyrus_content/change_feeds.py (the normalized change and the wake are the Item feed's, src/papyrus_content/item_change_feed.py); the handler is
 * amplify/functions/change-feed/handler.py. One function, not one per table: the feeds share every line of code and all they differ in is the table of the stream
 * a record came from, which the record's stream ARN names (`PAPYRUS_CHANGE_FEED_STREAMS`). That costs the function, its role and its policy once, and one mapping
 * for each stream the feed reads itself.
 *
 * Where a table's stream is read by the feed itself (`placements` says `own`) this piece holds a mapping with a filter. Where the table already has two readers
 * (`behind`) it holds no mapping: the reader that stays on the stream passes its batch to this function (`allowChangeFeedRelay`, src/papyrus_content/change_feed_relay.py),
 * so the stream never gets a third reader.
 *
 * What the function may do, and nothing else: read the streams it owns; read the site's `SiteDocument` rows (the live version of the listener index) and one
 * Message thread by id through its own site's API, and that index's objects in the site's bucket; look up and send to its own site's wake queue. It reads no table
 * by scan or list, receives and deletes no wake, and calls no model.
 */

export const CHANGE_FEED_API_FIELDS = ["Query/fields/getSiteDocument", "Query/fields/getMessageThread"];
export const CHANGE_FEED_STREAMS_ENV = "PAPYRUS_CHANGE_FEED_STREAMS";
export const CHANGE_FEED_FUNCTION_ENV = "PAPYRUS_CHANGE_FEED_FUNCTION";
export const CHANGE_FEED_RELAY_STREAMS_ENV = "PAPYRUS_CHANGE_FEED_RELAY_STREAMS";
const STREAM_READ_ACTIONS = ["dynamodb:DescribeStream", "dynamodb:GetRecords", "dynamodb:GetShardIterator", "dynamodb:ListStreams"];
export const CHANGE_FEED_NAME_SUFFIX = "-change-feed";
const SITE_ID_LENGTH = 40;

/** The feed function's name: literal, from the site's brand id, so a reader that relays to it names it without a reference into the `agents` stack. */
export function changeFeedFunctionName(brandId: string): string {
  const siteId = sanitizeAwsName(brandId, SITE_ID_LENGTH);
  if (siteId === "") throw new Error(`The change feed is named after the site's brand id, which must contain a letter or digit (got ${JSON.stringify(brandId)}).`);
  return assertLiteralResourceName("Change feed function name", `papyrus-${siteId}${CHANGE_FEED_NAME_SUFFIX}`);
}

/**
 * The mapping's filter for each table: the stream records the feed can act on, so a record that cannot be a change never starts the function. The feed's own
 * normalizer decides again (a relayed batch is not filtered), so a filter only saves invocations and never decides what a change is.
 */
export const CHANGE_FEED_FILTERS: Record<FeedTable, Record<string, unknown>> = {
  Reference: { eventName: ["INSERT", "MODIFY"] },
  ReviewRequest: { eventName: ["MODIFY"], dynamodb: { NewImage: { state: { S: ["answered"] } } } },
  Message: { eventName: ["INSERT"], dynamodb: { NewImage: { messageKind: { S: ["comment"] } } } },
  LocalizationRequest: { eventName: ["INSERT", "MODIFY"], dynamodb: { NewImage: { state: { S: ["wanted"] } } } },
  Delivery: { eventName: ["INSERT", "MODIFY"] },
};

/** The streams the stack switched on or found: a table's stream ARN, only for a table the site's schema has. */
export type FeedStreams = Partial<Record<FeedTable, string>>;

export type ChangeFeedsSource = {
  streams: FeedStreams;
  placements: Record<FeedTable, FeedPlacement>;
  graphqlUrl: string;
  apiId: string;
  tenantId: string;
  bucketName: string;
  bucketArn: string;
};

/** The streams of every feed table the schema has. The Reference, Message and LocalizationRequest streams are the readers' own where they exist; ReviewRequest and Delivery had none. */
export function enableFeedStreams(backend: any): FeedStreams {
  const streams: FeedStreams = {};
  for (const table of FEED_TABLES) {
    const arn = tableStream(backend, table, FEED_STREAM_VIEW);
    if (arn !== undefined) streams[table] = arn;
  }
  return streams;
}

/**
 * Lets a stream reader pass its batches to this site's change feed: it may invoke that one function, by its literal name, and the function's name and the streams it
 * hands over are its settings. Adds no resource. A function that reads two streams (the home page's) hands over only the ones whose feed sits behind it.
 */
export function allowChangeFeedRelay(carrier: LambdaFunction, brandId: string, streamArns: readonly string[]): void {
  const stack = Stack.of(carrier);
  carrier.addEnvironment(CHANGE_FEED_FUNCTION_ENV, changeFeedFunctionName(brandId));
  carrier.addEnvironment(CHANGE_FEED_RELAY_STREAMS_ENV, stack.toJsonString([...streamArns]));
  carrier.addToRolePolicy(
    new PolicyStatement({
      effect: Effect.ALLOW,
      actions: ["lambda:InvokeFunction"],
      resources: [`arn:${stack.partition}:lambda:${stack.region}:${stack.account}:function:${changeFeedFunctionName(brandId)}`],
    }),
  );
}

export type RelayCarrier = { reader: StreamReaderId; lambda: LambdaFunction };

export function changeFeedsPiece(brandId: string, source: ChangeFeedsSource): AgentPiece {
  return {
    id: "change-feeds",
    add(scope: Construct) {
      const stack = Stack.of(scope);
      const tables = FEED_TABLES.filter((table) => source.streams[table] !== undefined);
      const feed = new LambdaFunction(scope, "ChangeFeed", {
        functionName: changeFeedFunctionName(brandId),
        runtime: Runtime.PYTHON_3_12,
        architecture: Architecture.ARM_64,
        handler: "handler.handler",
        timeout: Duration.seconds(60),
        memorySize: 256,
        description: "Puts a wake on the site's agent wake queue for each agent that listens for a change to a Reference, review request, Message, translation request or Delivery (PPY-9b9e64).",
        code: pythonLambdaCode(
          { functionDir: "change-feed", modules: ["papyrus_content"], noDeps: true },
          [
            "bash",
            "-c",
            [
              "set -euo pipefail",
              "mkdir -p /asset-output/papyrus_content",
              "cp amplify/functions/change-feed/handler.py /asset-output/handler.py",
              "cp -R src/papyrus_content/. /asset-output/papyrus_content/",
            ].join(" && "),
          ],
        ),
      });
      connectToSiteApi(feed, source.graphqlUrl);
      feed.addEnvironment("PAPYRUS_AGENT_PUBLICATION_ID", brandId);
      feed.addEnvironment("PAPYRUS_TENANT_ID", source.tenantId);
      feed.addEnvironment("PAPYRUS_SITE_BUCKET", source.bucketName);
      feed.addEnvironment(CHANGE_FEED_STREAMS_ENV, stack.toJsonString(tables.map((table) => ({ stream: source.streams[table], table }))));
      feed.addToRolePolicy(
        new PolicyStatement({
          effect: Effect.ALLOW,
          actions: ["appsync:GraphQL"],
          resources: CHANGE_FEED_API_FIELDS.map((field) => `arn:${stack.partition}:appsync:${stack.region}:${stack.account}:apis/${source.apiId}/types/${field}`),
        }),
      );
      feed.addToRolePolicy(
        new PolicyStatement({ effect: Effect.ALLOW, actions: ["s3:GetObject"], resources: [`${source.bucketArn}/tenants/${source.tenantId}/site/${LISTENER_INDEX_KIND}/*`] }),
      );
      allowWakeSending(feed, brandId);
      for (const table of tables.filter((candidate) => source.placements[candidate].mode === "own")) {
        const streamArn = source.streams[table]!;
        feed.addToRolePolicy(new PolicyStatement({ effect: Effect.ALLOW, actions: STREAM_READ_ACTIONS, resources: [streamArn] }));
        new CfnEventSourceMapping(scope, `${table}StreamMapping`, {
          eventSourceArn: streamArn,
          functionName: feed.functionArn,
          startingPosition: "LATEST",
          batchSize: 10,
          maximumBatchingWindowInSeconds: 2,
          maximumRetryAttempts: 5,
          functionResponseTypes: ["ReportBatchItemFailures"],
          filterCriteria: { filters: [{ pattern: JSON.stringify(CHANGE_FEED_FILTERS[table]) }] },
        });
      }
    },
  };
}
