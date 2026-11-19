import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

/**
 * Who reads which DynamoDB stream, and where each change feed sits (docs/design/always-on-agents-architecture.md, section 8.1 and slice B3, PPY-9b9e64).
 *
 * A DynamoDB stream should have at most two readers [AWS guidance]. The Reference table has up to two before any feed (the word index, the home page) and the
 * Message table up to three (the console responder, Slack delivery, the home page). So the change feed for a table is placed by a rule, in one function that
 * the test calls with every combination of switches:
 *
 *  - a table with fewer than two readers gets the feed as a reader of its own (an event source mapping with a filter);
 *  - a table with two or more gets no new reader: the feed sits behind one that stays on the stream, which passes its batch to the feed function and reports what
 *    the feed could not do (src/papyrus_content/change_feed_relay.py). Only a reader whose handler is Python and whose mapping reads every change the feed needs
 *    can carry it; `RELAY_CARRIERS` lists them, in the order they are preferred.
 *
 * This is a finding about readers that exist today, not something this fixes for them: the readers are named here only so the rule and the test can count them.
 */

/** The tables the change feeds of slice B3 cover (the Item table's feed is its own function, amplify/agents/item-change-feed.ts). */
export const FEED_TABLES = ["Reference", "ReviewRequest", "Message", "LocalizationRequest", "Delivery"] as const;
export type FeedTable = (typeof FEED_TABLES)[number];

export const MAX_STREAM_READERS = 2;

export type StreamReaderId =
  | "reference-word-index"
  | "home-page-references"
  | "console-responder"
  | "slack-delivery"
  | "home-page-threads"
  | "localization-dispatch";

/** Every stream reader that is not a change feed: the table it reads. */
export const STREAM_READER_TABLES: Record<StreamReaderId, string> = {
  "reference-word-index": "Reference",
  "home-page-references": "Reference",
  "console-responder": "Message",
  "slack-delivery": "Message",
  "home-page-threads": "Message",
  "localization-dispatch": "LocalizationRequest",
};

/**
 * The readers whose handler can carry a feed, per table, best first. The word index reads every Reference change; Slack delivery reads every Message change; the
 * home page's thread reader reads comments, which is the only Message change the feed acts on. The home page's Reference reader sees only curated references, so it
 * cannot carry the Reference feed. The console responder is not Python.
 */
export const RELAY_CARRIERS: Partial<Record<FeedTable, readonly StreamReaderId[]>> = {
  Reference: ["reference-word-index"],
  Message: ["slack-delivery", "home-page-threads"],
};

export type FeedPlacement = { mode: "own" } | { mode: "behind"; reader: StreamReaderId };

/** The readers on `table` among the `active` ones. */
export function readersOn(table: string, active: readonly StreamReaderId[]): StreamReaderId[] {
  return active.filter((reader) => STREAM_READER_TABLES[reader] === table);
}

/** Where the feed for `table` sits, given the readers switched on. Throws when no reader can carry it: the feed is never added as a third reader. */
export function planFeed(table: FeedTable, active: readonly StreamReaderId[]): FeedPlacement {
  const readers = readersOn(table, active);
  if (readers.length < MAX_STREAM_READERS) return { mode: "own" };
  const carrier = (RELAY_CARRIERS[table] ?? []).find((candidate) => readers.includes(candidate));
  if (carrier === undefined) {
    throw new Error(`The ${table} stream already has ${readers.length} readers (${readers.join(", ")}) and none of them can carry the change feed; move one behind another first.`);
  }
  return { mode: "behind", reader: carrier };
}

export function planFeeds(active: readonly StreamReaderId[]): Record<FeedTable, FeedPlacement> {
  return Object.fromEntries(FEED_TABLES.map((table) => [table, planFeed(table, active)])) as Record<FeedTable, FeedPlacement>;
}

/** How many readers each table's stream has once the feeds are placed: the existing readers plus a feed that is a reader of its own. */
export function readerCounts(active: readonly StreamReaderId[], placements: Record<FeedTable, FeedPlacement>): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const reader of active) counts[STREAM_READER_TABLES[reader]] = (counts[STREAM_READER_TABLES[reader]] ?? 0) + 1;
  for (const table of FEED_TABLES) if (placements[table].mode === "own") counts[table] = (counts[table] ?? 0) + 1;
  return counts;
}

/** A stream view the feed needs: both images (it compares the old and new row to tell what changed). */
export const FEED_STREAM_VIEW = dynamodb.StreamViewType.NEW_AND_OLD_IMAGES;

/**
 * The stream of `table` (its ARN), switched on with `view` when nothing has switched it on yet, or undefined when the site's schema has no such table (an optional
 * model group left out). A stream another feature switched on keeps its own view type: the feed needs the new image of an inserted row and, for the tables it
 * enables itself, both.
 */
export function tableStream(backend: any, table: string, view: dynamodb.StreamViewType): string | undefined {
  const cfnResources = backend.data.resources.cfnResources;
  const wrapper = cfnResources.amplifyDynamoDbTables?.[table];
  if (wrapper !== undefined) {
    if (wrapper.streamSpecification?.streamViewType === undefined) wrapper.streamSpecification = { streamViewType: view };
    return wrapper.resource.getAtt("TableStreamArn").toString();
  }
  const cfnTables = cfnResources.cfnTables ?? {};
  const found =
    cfnTables[table] ??
    cfnTables[`${table}Table`] ??
    Object.entries(cfnTables).find(([key]) => key.toLowerCase().replace(/table$/, "") === table.toLowerCase())?.[1];
  if (!found) return undefined;
  if ((found as any).streamSpecification?.streamViewType === undefined) (found as any).streamSpecification = { streamViewType: view };
  return (found as any).attrStreamArn;
}

