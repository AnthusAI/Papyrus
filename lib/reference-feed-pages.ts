/**
 * The References feed, one page at a time.
 *
 * The page never loads every Reference. It reads a page (24) from one of two indexes on `Reference` (docs/reference-feed-indexes.md):
 * the unrated stream or the rated stream, in the order of the active sort, and the next page only when the editor scrolls toward the end.
 * "Unrated only" has one cursor; "Include rated" has two (unrated and rated), merged by the same comparator the index sorts by, each
 * paged lazily. What is on screen never reshuffles: a page is appended after what is already there, and rating a card patches it in place.
 * A card's attachments and decision are read per page, in one request, for the References on that page only.
 *
 * Everything here is plain TypeScript with no React and no network, so the paging rules are tested directly with a fake source.
 */
import type { ReferenceAttachmentRecord, ReferenceRecord } from "./category-repository";
import { referenceFeedKeys } from "./reference-feed-keys";
import { acceptProbability, type FeedShow, type FeedSort } from "./reference-feed-ranking";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import { selectCanonicalReferenceRecords } from "./newsroom-references";
import type { RelevanceDecisionView } from "./relevance-decisions";

/** How many References one page holds. */
export const FEED_PAGE_SIZE = 24;

export type FeedStream = "unrated" | "rated";

export type FeedPageRequest = { stream: FeedStream; sort: FeedSort; limit: number; nextToken: string | null };
export type FeedPage = { items: ReferenceRecord[]; nextToken: string | null };
export type FeedCompanions = { attachments: ReferenceAttachmentRecord[]; decisions: Map<string, RelevanceDecisionView> };

/** Where the feed's data comes from: the GraphQL indexes in the app, a fake in tests, an in-memory list for a static array of References. */
export interface ReferenceFeedSource {
  /** One page of one stream in the sort's order (highest key first). `nextToken` is null on the last page. */
  fetchPage(request: FeedPageRequest): Promise<FeedPage>;
  /** The attachments and decisions of these References only, in one round trip. */
  fetchCompanions(references: ReferenceRecord[]): Promise<FeedCompanions>;
  /** One Reference by id or lineage id, without the feed. Null when it does not exist. */
  fetchReference(idOrLineageId: string): Promise<ReferenceRecord | null>;
  /** How many unrated References arrived after `since` (an instant) and are not in `known` (lineage ids). A cheap check, not a load. */
  countNew(query: { since: string; known: ReadonlySet<string> }): Promise<number>;
  /** Whether any Reference has been rated, for the empty-feed words. Called only when the unrated stream is empty. */
  hasRated(): Promise<boolean>;
}

export function lineageOf(reference: ReferenceRecord): string {
  return reference.lineageId ?? reference.id;
}

/** The index key a record sorts by in a sort, taken from the record's own fields when it has them (it does when it came from an index). */
export function feedSortKey(reference: ReferenceRecord, sort: FeedSort): string {
  const keyed = referenceFeedKeys(reference);
  return sort === "newest"
    ? `${reference.feedArrivalAt ?? keyed.feedArrivalAt}#${reference.id}`
    : (reference.predictionSortKey ?? keyed.predictionSortKey);
}

/** Highest key first: the order both indexes are read in. */
export function compareFeedRecords(sort: FeedSort) {
  return (left: ReferenceRecord, right: ReferenceRecord) => {
    const a = feedSortKey(left, sort);
    const b = feedSortKey(right, sort);
    return a < b ? 1 : a > b ? -1 : 0;
  };
}

/** P(accept) for ordering and for the lead card: the original prediction on the Reference, else the decision's, else a coin toss. */
export function referenceProbability(reference: ReferenceRecord, decision: RelevanceDecisionView | undefined): number {
  return typeof reference.predictedAcceptProbability === "number" ? reference.predictedAcceptProbability : acceptProbability(decision);
}

export function isRated(reference: ReferenceRecord): boolean {
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  return status === "accepted" || status === "rejected";
}

class Cursor {
  private buffer: ReferenceRecord[] = [];
  private token: string | null = null;
  private done = false;
  /** Requests this cursor has made, for the tests. */
  requests = 0;

  constructor(
    private readonly source: ReferenceFeedSource,
    readonly stream: FeedStream,
    private readonly sort: FeedSort,
    private readonly pageSize: number,
  ) {}

  /** The next record without taking it, reading a page when the buffer is empty. A page can come back empty with a token (a filtered page). */
  async head(): Promise<ReferenceRecord | undefined> {
    while (!this.buffer.length && !this.done) {
      this.requests += 1;
      const page = await this.source.fetchPage({ stream: this.stream, sort: this.sort, limit: this.pageSize, nextToken: this.token });
      this.buffer = [...page.items];
      this.token = page.nextToken;
      this.done = !page.nextToken;
    }
    return this.buffer[0];
  }

  take(): ReferenceRecord | undefined {
    return this.buffer.shift();
  }

  get exhausted(): boolean {
    return this.done && !this.buffer.length;
  }
}

/** One (sort, show) feed: its loaded records in display order, and the cursors that load more. */
export class ReferenceFeedPager {
  readonly records: ReferenceRecord[] = [];
  private readonly cursors: Cursor[];
  private readonly seen = new Set<string>();
  private loading: Promise<ReferenceRecord[]> | null = null;
  firstPageLoaded = false;

  constructor(
    private readonly source: ReferenceFeedSource,
    readonly sort: FeedSort,
    readonly show: FeedShow,
    private readonly pageSize = FEED_PAGE_SIZE,
  ) {
    this.cursors = [new Cursor(source, "unrated", sort, pageSize), ...(show === "all" ? [new Cursor(source, "rated", sort, pageSize)] : [])];
  }

  get exhausted(): boolean {
    return this.cursors.every((cursor) => cursor.exhausted);
  }

  get requests(): number {
    return this.cursors.reduce((total, cursor) => total + cursor.requests, 0);
  }

  get busy(): boolean {
    return this.loading !== null;
  }

  /** Append the next page of the merged streams. Concurrent calls share one load. Resolves to what was appended. */
  loadMore(): Promise<ReferenceRecord[]> {
    this.loading ??= this.takeMerged().finally(() => { this.loading = null; });
    return this.loading;
  }

  private async takeMerged(): Promise<ReferenceRecord[]> {
    const compare = compareFeedRecords(this.sort);
    const added: ReferenceRecord[] = [];
    while (added.length < this.pageSize) {
      const heads = await Promise.all(this.cursors.map(async (cursor) => ({ cursor, head: await cursor.head() })));
      const live = heads.filter((entry): entry is { cursor: Cursor; head: ReferenceRecord } => entry.head !== undefined);
      if (!live.length) break;
      const best = live.reduce((winner, entry) => (compare(entry.head, winner.head) < 0 ? entry : winner));
      const record = best.cursor.take()!;
      const lineage = lineageOf(record);
      // A card rated this visit moves streams; it must not appear a second time when the other stream reaches it.
      if (this.seen.has(lineage)) continue;
      this.seen.add(lineage);
      this.records.push(record);   // kept as it is taken, so a failed read later in the page loses nothing
      added.push(record);
    }
    this.firstPageLoaded = true;
    return added;
  }
}

// --- In-memory source -----------------------------------------------------------------------------------------------------------

export type StaticFeedData = {
  references: ReferenceRecord[];
  decisions?: ReadonlyMap<string, RelevanceDecisionView> | undefined;
  attachments?: ReferenceAttachmentRecord[] | undefined;
};

/**
 * A source over a list already in memory: the fixtures the harnesses mount and any host that has the References in hand. It pages the same
 * way the indexes do (the same keys, the same streams, the same page size), so there is one code path. `data` is read on every call, so a
 * host can keep it current.
 */
export function createStaticFeedSource(data: () => StaticFeedData): ReferenceFeedSource {
  const decorated = (reference: ReferenceRecord, decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined): ReferenceRecord => {
    const decision = decisions?.get(lineageOf(reference));
    const probability = typeof reference.predictedAcceptProbability === "number"
      ? reference.predictedAcceptProbability
      : decision ? acceptProbability(decision) : null;
    const keys = referenceFeedKeys(reference, probability);
    return {
      ...reference,
      predictedAcceptProbability: reference.predictedAcceptProbability ?? probability,
      feedStateKey: keys.feedStateKey,
      feedArrivalAt: keys.feedArrivalAt,
      predictionSortKey: keys.predictionSortKey,
    };
  };
  const stream = (request: FeedPageRequest): ReferenceRecord[] => {
    const { references, decisions } = data();
    return selectCanonicalReferenceRecords(references)
      .filter((reference) => normalizeReferenceCurationStatus(reference.curationStatus) !== "archived")
      .filter((reference) => (request.stream === "rated") === isRated(reference))
      .map((reference) => decorated(reference, decisions))
      .sort(compareFeedRecords(request.sort));
  };
  return {
    async fetchPage(request) {
      const all = stream(request);
      const start = request.nextToken ? Number(request.nextToken) : 0;
      const end = start + request.limit;
      return { items: all.slice(start, end), nextToken: end < all.length ? String(end) : null };
    },
    async fetchCompanions(references) {
      const { decisions, attachments } = data();
      const wanted = new Set(references.map(lineageOf));
      return {
        attachments: (attachments ?? []).filter((attachment) => wanted.has(attachment.referenceLineageId)),
        decisions: new Map([...(decisions ?? [])].filter(([lineage]) => wanted.has(lineage))),
      };
    },
    async fetchReference(idOrLineageId) {
      const { references, decisions } = data();
      const found = references.find((reference) => reference.id === idOrLineageId || reference.lineageId === idOrLineageId);
      return found ? decorated(found, decisions) : null;
    },
    async countNew({ known }) {
      return stream({ stream: "unrated", sort: "newest", limit: 0, nextToken: null }).filter((reference) => !known.has(lineageOf(reference))).length;
    },
    async hasRated() {
      return stream({ stream: "rated", sort: "newest", limit: 0, nextToken: null }).length > 0;
    },
  };
}
