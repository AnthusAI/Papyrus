/**
 * The Medium filter of the References feed (PPY-ec0d0a). The page address names it: `/newsroom/references?medium=video`. Any other value, or none, is "any".
 * The mediums are the ones the rule can name (`MEDIUMS` in src/papyrus_content/reference_medium.py): today only `video`. A Reference whose medium is unknown
 * has no `mediumFeedKey` and is in no medium partition, so it is listed under All and never under a medium.
 *
 * A medium reads the medium index (`<corpusId>#<medium>#<pending|accepted|rejected>`, sorted by arrival; docs/reference-feed-indexes.md), one partition per
 * vote state, never the whole table. The vote state is in the key, so Reviewed picks partitions: No is `pending`, Accepted is `accepted`, Yes is `accepted` and
 * `rejected`, Any is all three. The index is by arrival, so it cannot order by prediction; with stars (Quality, a minimum) the feed reads the small star
 * partitions instead and keeps the rows of the medium.
 */
import type { ReferenceRecord } from "./category-repository";
import { compareFeedRecords, type FeedStreamReader, type FeedStreamShow } from "./reference-feed-pages";
import { referenceMediumFeedKey } from "./reference-feed-keys";

export const FEED_MEDIUMS = ["any", "video"] as const;
export type FeedMedium = (typeof FEED_MEDIUMS)[number];
export const DEFAULT_FEED_MEDIUM: FeedMedium = "any";
/** The word on the button and in the sentences. */
export const MEDIUM_LABELS: Record<FeedMedium, string> = { any: "All", video: "Videos" };
/** The plural noun, for "No videos here". */
export const MEDIUM_NOUNS: Record<Exclude<FeedMedium, "any">, string> = { video: "videos" };

export function feedMediumFromSearch(search: string): FeedMedium {
  const value = new URLSearchParams(search).get("medium") ?? "";
  return (FEED_MEDIUMS as readonly string[]).includes(value) ? (value as FeedMedium) : DEFAULT_FEED_MEDIUM;
}

/** The address query with `medium` set (or removed for All), every other part kept. */
export function searchWithMedium(search: string, medium: FeedMedium): string {
  const params = new URLSearchParams(search);
  if (medium === "any") params.delete("medium"); else params.set("medium", medium);
  const text = params.toString();
  return text ? `?${text}` : "";
}

const STATUSES_FOR: Record<FeedStreamShow, readonly string[]> = {
  unrated: ["pending"],
  accepted: ["accepted"],
  rated: ["accepted", "rejected"],
  all: ["pending", "accepted", "rejected"],
};

/** The medium partitions a Reviewed choice reads, per corpus. */
export function mediumFeedKeys(corpusIds: readonly string[], medium: Exclude<FeedMedium, "any">, show: FeedStreamShow): string[] {
  return [...new Set(corpusIds)].flatMap((corpusId) => STATUSES_FOR[show].map((status) => `${corpusId}#${medium}#${status}`));
}

/** Keeps the rows of one medium: for pages read from the star partitions, which hold every medium. */
export function mediumRows(read: FeedStreamReader, medium: FeedMedium): FeedStreamReader {
  if (medium === "any") return read;
  return async (query) => {
    const page = await read(query);
    return { ...page, items: page.items.filter((reference) => reference.medium === medium) };
  };
}

/** The medium index served from records held in memory (the demo, the local preview and the test editor mock): the same keys, newest arrival first. */
export function mediumReaderFromRecords(records: readonly ReferenceRecord[]): FeedStreamReader {
  return async ({ feedStateKey, limit, nextToken }) => {
    const compare = compareFeedRecords("newest");
    const rows = records
      .map((record) => ({ ...record, mediumFeedKey: referenceMediumFeedKey(record) }) as ReferenceRecord)
      .filter((record) => record.mediumFeedKey === feedStateKey)
      .sort(compare);
    const start = nextToken ? Number(nextToken) || 0 : 0;
    const items = rows.slice(start, start + limit);
    const next = start + items.length;
    return { items, nextToken: next < rows.length ? String(next) : null };
  };
}
