/**
 * Pages of the References feed, read from the feed-state indexes (docs/reference-feed-indexes.md).
 *
 * A site can have several corpora and the feed shows rated and unrated Reference together under "All", so the feed is
 * several index partitions (`<corpusId>#unrated`, `<corpusId>#rated`), each already in feed order. `MergedFeedReader` merges them
 * into one list in the same order as a single partition would give: Predictions by `predictionSortKey`, Newest by `feedArrivalAt`,
 * both newest-first on ties. The Quality sort and the minimum-stars choice read star partitions (`<corpusId>#stars#<n>`) the same way. One call to `more` makes at most one round of reads (one page per partition whose buffer ran dry, in
 * parallel) and returns what it can place; it never walks pages to fill a target, so a short answer simply means the next
 * scroll asks again.
 */
import type { ReferenceRecord } from "./category-repository";
import { referenceFeedKeys, starFeedKeyFor } from "./reference-feed-keys";
import { starsOf } from "./reference-policy";

/** Quality is stars first, then newest: the star partitions are read by arrival and merged by stars (docs/reference-feed-indexes.md). */
export type FeedStreamSort = "best" | "newest" | "quality";
export type FeedStreamShow = "unrated" | "all" | "rated";

/** `feedStateKey` is the partition read: a feed-state key for `readStream`, a star key (`<corpusId>#stars#<n>`) for `readStarStream`. */
export type FeedStreamQuery = { feedStateKey: string; sort: FeedStreamSort; limit: number; nextToken: string | null };
export type FeedStreamPage = { items: ReferenceRecord[]; nextToken: string | null };
export type FeedStreamReader = (query: FeedStreamQuery) => Promise<FeedStreamPage>;

/** One page of the screen: about what fills it plus a little (the feed shows about this many cards). */
export const FEED_READ_PAGE_SIZE = 24;

export function feedStateKeys(corpusIds: readonly string[], show: FeedStreamShow): string[] {
  const states = show === "all" ? ["unrated", "rated"] : [show];
  return [...new Set(corpusIds)].flatMap((corpusId) => states.map((state) => `${corpusId}#${state}`));
}

/** The whole star rating of a Reference, 0 when it has none or the value is not a rating (a missing, null, fractional or out of range value). */
export { starsOf };

/**
 * The star partitions a minimum reads: one per star level from `minStars` up to 5, for each corpus. `minStars` 1 is every starred Reference
 * (the Quality sort with the minimum on Any).
 */
export function starFeedKeys(corpusIds: readonly string[], minStars: number): string[] {
  const floor = Math.min(5, Math.max(1, Math.floor(minStars) || 1));
  return [...new Set(corpusIds)].flatMap((corpusId) => Array.from({ length: 6 - floor }, (_, offset) => starFeedKeyFor(corpusId, 5 - offset)!));
}

/** Whether a row from a star partition belongs under the chosen Show: a row with no `feedStateKey` (archived, superseded) never does. */
export function shownInFeed(reference: Pick<ReferenceRecord, "feedStateKey">, show: FeedStreamShow): boolean {
  const key = reference.feedStateKey;
  if (!key) return false;
  return show === "all" || key.endsWith(show === "unrated" ? "#unrated" : "#rated");
}

/**
 * A star partition holds a Reference for as long as it has a `starFeedKey`, whatever became of it, so a page is filtered after it is read: a
 * superseded or archived Reference (no `feedStateKey`) is dropped, and the rest are matched to the chosen Show. A page can come back short, or empty
 * with a next token; `MergedFeedReader` reads on.
 */
export function liveStarRows(read: FeedStreamReader, show: FeedStreamShow): FeedStreamReader {
  return async (query) => {
    const page = await read(query);
    return { ...page, items: page.items.filter((reference) => shownInFeed(reference, show)) };
  };
}

function sortValue(reference: ReferenceRecord, sort: FeedStreamSort): string {
  if (sort === "best") return reference.predictionSortKey ?? referenceFeedKeys(reference).predictionSortKey;
  return reference.feedArrivalAt ?? referenceFeedKeys(reference).feedArrivalAt;
}

/** Descending feed order: larger sort value first, then the id, so a tie never reorders between reads. Quality is more stars first, then newest arrival. */
export function compareFeedRecords(sort: FeedStreamSort) {
  return (left: ReferenceRecord, right: ReferenceRecord): number => {
    if (sort === "quality") {
      const stars = starsOf(right) - starsOf(left);
      if (stars) return stars;
    }
    const a = sortValue(left, sort === "quality" ? "newest" : sort);
    const b = sortValue(right, sort);
    if (a !== b) return a < b ? 1 : -1;
    return left.id < right.id ? 1 : left.id > right.id ? -1 : 0;
  };
}

type Stream = { key: string; buffer: ReferenceRecord[]; token: string | null; done: boolean; started: boolean };

export class MergedFeedReader {
  private readonly streams: Stream[];
  private readonly compare: (left: ReferenceRecord, right: ReferenceRecord) => number;
  private readonly emitted = new Set<string>();
  /** Number of index reads made so far. */
  reads = 0;

  constructor(
    private readonly options: {
      keys: readonly string[];
      sort: FeedStreamSort;
      read: FeedStreamReader;
      pageSize?: number;
    },
  ) {
    this.streams = options.keys.map((key) => ({ key, buffer: [], token: null, done: false, started: false }));
    this.compare = compareFeedRecords(options.sort);
  }

  get hasMore(): boolean {
    return this.streams.some((stream) => stream.buffer.length > 0 || !stream.done);
  }

  /** Place up to `count` more records. A failed read throws and leaves the reader as it was, so calling again retries it. */
  async more(count = this.options.pageSize ?? FEED_READ_PAGE_SIZE): Promise<ReferenceRecord[]> {
    const limit = this.options.pageSize ?? FEED_READ_PAGE_SIZE;
    const dry = this.streams.filter((stream) => !stream.done && stream.buffer.length === 0);
    if (dry.length) {
      this.reads += dry.length;
      const pages = await Promise.all(dry.map((stream) => this.options.read({
        feedStateKey: stream.key, sort: this.options.sort, limit, nextToken: stream.token,
      })));
      dry.forEach((stream, index) => {
        const page = pages[index];
        stream.started = true;
        stream.buffer.push(...page.items);
        stream.token = page.nextToken;
        stream.done = !page.nextToken;
      });
    }
    const placed: ReferenceRecord[] = [];
    while (placed.length < count) {
      // A record is placed only when no partition could still hold something that sorts before it.
      if (this.streams.some((stream) => !stream.done && stream.buffer.length === 0)) break;
      let best: Stream | null = null;
      for (const stream of this.streams) {
        if (!stream.buffer.length) continue;
        if (!best || this.compare(stream.buffer[0], best.buffer[0]) < 0) best = stream;
      }
      if (!best) break;
      const record = best.buffer.shift()!;
      if (this.emitted.has(record.id)) continue;
      this.emitted.add(record.id);
      placed.push(record);
    }
    return placed;
  }
}

/**
 * Serve the same indexes from records held in memory (the demo, the local preview and the test editor mock): the same keys, the same
 * order, a page at a time with a numeric token.
 */
export function feedReaderFromRecords(records: readonly ReferenceRecord[]): FeedStreamReader {
  return async ({ feedStateKey, sort, limit, nextToken }) => {
    const compare = compareFeedRecords(sort);
    const rows = records
      .map((record) => ({ ...record, ...referenceFeedKeys(record), predictionSortKey: record.predictionSortKey ?? referenceFeedKeys(record).predictionSortKey }) as ReferenceRecord)
      .filter((record) => record.feedStateKey === feedStateKey)
      .sort(compare);
    const start = nextToken ? Number(nextToken) || 0 : 0;
    const items = rows.slice(start, start + limit);
    const next = start + items.length;
    return { items, nextToken: next < rows.length ? String(next) : null };
  };
}

/** The star index served from records held in memory (the demo, the local preview and the test editor mock): every starred row, whatever its state, as the index holds them. */
export function starReaderFromRecords(records: readonly ReferenceRecord[]): FeedStreamReader {
  return async ({ feedStateKey, limit, nextToken }) => {
    const compare = compareFeedRecords("newest");
    const rows = records
      .map((record) => ({ ...record, ...referenceFeedKeys(record), starFeedKey: starFeedKeyFor(record.corpusId, record.starRating) }) as ReferenceRecord)
      .filter((record) => record.starFeedKey === feedStateKey)
      .sort(compare);
    const start = nextToken ? Number(nextToken) || 0 : 0;
    const items = rows.slice(start, start + limit);
    const next = start + items.length;
    return { items, nextToken: next < rows.length ? String(next) : null };
  };
}
