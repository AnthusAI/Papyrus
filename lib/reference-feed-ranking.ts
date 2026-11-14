/**
 * How the References feed is ordered, in plain words (the "How this feed is ranked" popover says them too):
 *   - One list, three sorts. "Predictions" is the Cyclotron's confidence that you will Accept (P), highest first; a prediction of
 *     Accept at 80% is P = 0.8, a prediction of Reject at 80% is P = 0.2, no prediction is P = 0.5. Age does not change it.
 *   - "Newest" is reverse chronological by when the Reference arrived.
 *   - "Quality" is the editor's stars, most first, newest first within a star level; only starred References are in it.
 *   - Ties go to the newest item, then to a stable id order.
 *   - "Minimum stars" (Any, 3+, 4+, 5) keeps References with at least that many stars, in whichever sort is chosen.
 *   - "Reviewed" (Any, Accepted, Yes, No): Accepted shows only the References someone accepted (never a rejected one), Yes shows the References someone has accepted or rejected, No the ones nobody has answered, Any both in one list.
 *   - "Captured" (Any, Yes, No): Yes shows References whose content we hold in full, No the ones we could not collect (thin, still running, or only an address).
 * Nothing is cut off by age, and age never changes the order of Predictions: the original confidence is what ranks.
 */
import type { ReferenceRecord } from "./category-repository";
import type { RelevanceDecisionView } from "./relevance-decisions";
import { matchesCaptured, normalizeReferenceCurationStatus, starsOf, type CapturedChoice } from "./reference-policy";
import { referenceLineageId } from "./newsroom-references";

/** The probability that stands for "no prediction". */
export const UNDECIDED_PROBABILITY = 0.5;
/** A prediction that recorded a label but no confidence is a mild lean, not a coin toss and not a certainty. */
export const UNRECORDED_CONFIDENCE = 0.6;


function timeOf(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

/** When the item reached the newsroom. The same arrival the monitor stories use. */
export function referenceArrivalTime(reference: ReferenceRecord): number | null {
  return timeOf(reference.createdAt) ?? timeOf(reference.importedAt) ?? timeOf(reference.retrievedAt) ?? timeOf(reference.sourcePublishedAt);
}

/** The date a card shows: when the source says it was published, else when it arrived. */
export function referenceDisplayTime(reference: ReferenceRecord): number | null {
  return timeOf(reference.sourcePublishedAt) ?? timeOf(reference.sourceUpdatedAt) ?? referenceArrivalTime(reference);
}

/** P(the editor accepts), from the Cyclotron's decision: its confidence is in the label it chose. */
export function acceptProbability(decision: RelevanceDecisionView | undefined): number {
  if (!decision) return UNDECIDED_PROBABILITY;
  const confidence = decision.confidence ?? UNRECORDED_CONFIDENCE;
  const accepts = decision.label === (decision.positiveLabel ?? "include");
  return accepts ? confidence : 1 - confidence;
}

export type FeedItem = {
  reference: ReferenceRecord;
  lineageId: string;
  decision: RelevanceDecisionView | undefined;
  /** P(accept): the Cyclotron's confidence that the editor accepts. The Predictions sort key. */
  probability: number;
  /** True when a human has already answered (accepted or rejected). */
  rated: boolean;
};

export type FeedSort = "best" | "newest" | "quality";
/**
 * Reviewed (Ryan, 2026-11): whether a Reference has been accepted or rejected. The saved values keep their old names so nobody's choice resets:
 * `rated` is Reviewed Yes (accepted or rejected), `unrated` is Reviewed No, `all` is Reviewed Any, and `accepted` is Reviewed Accepted: only the
 * ones someone accepted (`REVIEWED_LABELS` in components/reference-feed.tsx).
 */
export type FeedShow = "unrated" | "all" | "rated" | "accepted";
/** Captured: whether the newsroom holds the content (`Reference.captureState` is `full`). `no` includes a capture still running, a thin one and none. */
export type FeedCaptured = CapturedChoice;
export const FEED_CAPTURED: readonly FeedCaptured[] = ["any", "yes", "no"];
export const DEFAULT_FEED_CAPTURED: FeedCaptured = "any";
/** The fewest stars to show: 0 is Any. Never "only 3" or "only 2": a minimum is a floor, and the lowest worth asking for is 3. */
export type FeedMinStars = 0 | 3 | 4 | 5;
export const FEED_MIN_STARS: readonly FeedMinStars[] = [0, 3, 4, 5];
export const DEFAULT_FEED_SORT: FeedSort = "best";
export const DEFAULT_FEED_SHOW: FeedShow = "unrated";
export const DEFAULT_FEED_MIN_STARS: FeedMinStars = 0;

/** The items the Captured choice lets through, for the pages that hold every Reference in memory (the demo); the indexed feed filters its pages as it reads them (`capturedRows`). */
export function filterByCaptured(items: FeedItem[], captured: FeedCaptured): FeedItem[] {
  return captured === "any" ? items : items.filter((item) => matchesCaptured(item.reference, captured));
}

export function scoreFeedItem(reference: ReferenceRecord, decision: RelevanceDecisionView | undefined): FeedItem {
  const status = normalizeReferenceCurationStatus(reference.curationStatus);
  return {
    reference,
    lineageId: referenceLineageId(reference),
    decision,
    probability: acceptProbability(decision),
    rated: status === "accepted" || status === "rejected",
  };
}

/** Every canonical Reference that is not archived, scored. Unordered: use `orderFeedItems`. */
export function buildFeedItems(references: ReferenceRecord[], decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined): FeedItem[] {
  const items: FeedItem[] = [];
  for (const reference of references) {
    if (normalizeReferenceCurationStatus(reference.curationStatus) === "archived") continue;
    items.push(scoreFeedItem(reference, decisions?.get(referenceLineageId(reference))));
  }
  return items;
}

function isAcceptedItem(item: FeedItem): boolean {
  return normalizeReferenceCurationStatus(item.reference.curationStatus) === "accepted";
}

/** Predictions: highest P(accept) first; ties go to the newest item, then to a stable id order. */
export function compareBestBets(left: FeedItem, right: FeedItem): number {
  if (right.probability !== left.probability) return right.probability - left.probability;
  return compareNewest(left, right);
}

/** Newest: latest arrival first; ties go to the higher P(accept), then to a stable id order. */
export function compareNewest(left: FeedItem, right: FeedItem): number {
  const newest = (referenceArrivalTime(right.reference) ?? 0) - (referenceArrivalTime(left.reference) ?? 0);
  if (newest) return newest;
  if (right.probability !== left.probability) return right.probability - left.probability;
  return left.lineageId.localeCompare(right.lineageId);
}

/** Quality: most stars first, then latest arrival, then a stable id order. */
export function compareQuality(left: FeedItem, right: FeedItem): number {
  return starsOf(right.reference) - starsOf(left.reference) || compareNewest(left, right);
}

export function orderFeedItems(items: FeedItem[], sort: FeedSort): FeedItem[] {
  return [...items].sort(sort === "newest" ? compareNewest : sort === "quality" ? compareQuality : compareBestBets);
}

/** The items with at least `minStars` stars; Quality keeps the starred only, whatever the minimum. Used where the feed is not read from the star index (the demo). */
export function filterByStars(items: FeedItem[], sort: FeedSort, minStars: FeedMinStars): FeedItem[] {
  const floor = Math.max(minStars, sort === "quality" ? 1 : 0);
  return floor ? items.filter((item) => starsOf(item.reference) >= floor) : items;
}

/**
 * The visible list: ordered by `sort`; "Unrated" keeps the items answered during this visit, which stay in place. "Rated"
 * lists the answered items, and keeps one whose answer was cleared this visit, so it does not vanish under the editor's hand.
 */
export function visibleFeedItems(items: FeedItem[], sort: FeedSort, show: FeedShow, visitRated: ReadonlySet<string> = new Set()): FeedItem[] {
  const keep = (item: FeedItem) => show === "all" || (show === "rated" ? item.rated : show === "accepted" ? isAcceptedItem(item) : !item.rated) || visitRated.has(item.lineageId);
  return orderFeedItems(items.filter(keep), sort);
}

/** The lead card is the first card, unless it is a predicted Reject. */
export function feedLeadId(items: FeedItem[]): string | undefined {
  return items[0] && items[0].probability >= UNDECIDED_PROBABILITY ? items[0].lineageId : undefined;
}

/**
 * The order of the feed, taken once per visit when it loads and then left alone: selecting, rating, a background refresh and a cache
 * revalidation never re-rank it, in either sort. Items that arrive later are counted as new and wait behind a "N new items: show" pill.
 */
export type FeedOrderSnapshot = {
  /** Every Reference lineage the snapshot knew about: anything else is new. */
  known: ReadonlySet<string>;
  /** The ones nobody had answered when the snapshot was taken: they stay listed under "Unrated" after being rated this visit. */
  unrated: ReadonlySet<string>;
  best: string[];
  newest: string[];
  quality: string[];
  /** The lead card of each sort, taken with the order: it is never a predicted Reject when the snapshot is taken. */
  lead: { best: string | undefined; newest: string | undefined; quality: string | undefined };
};

export function takeFeedOrderSnapshot(items: FeedItem[]): FeedOrderSnapshot {
  const unrated = items.filter((item) => !item.rated);
  const best = orderFeedItems(items, "best");
  const newest = orderFeedItems(items, "newest");
  return {
    known: new Set(items.map((item) => item.lineageId)),
    unrated: new Set(unrated.map((item) => item.lineageId)),
    best: best.map((item) => item.lineageId),
    newest: newest.map((item) => item.lineageId),
    quality: orderFeedItems(items, "quality").map((item) => item.lineageId),
    lead: { best: feedLeadId(orderFeedItems(unrated, "best")), newest: feedLeadId(orderFeedItems(unrated, "newest")), quality: feedLeadId(orderFeedItems(unrated, "quality")) },
  };
}

/** The visible list in the snapshot's order; records and predictions stay current. */
export function applyFeedOrderSnapshot(snapshot: FeedOrderSnapshot, live: FeedItem[], sort: FeedSort, show: FeedShow): {
  items: FeedItem[];
  leadId: string | undefined;
  newCount: number;
} {
  const byId = new Map(live.map((item) => [item.lineageId, item] as const));
  const items = (sort === "newest" ? snapshot.newest : sort === "quality" ? snapshot.quality : snapshot.best)
    .filter((id) => show === "all" || (show === "rated" ? !snapshot.unrated.has(id) || byId.get(id)?.rated
      : show === "accepted" ? Boolean(byId.get(id) && isAcceptedItem(byId.get(id)!)) : snapshot.unrated.has(id)))
    .flatMap((id) => { const item = byId.get(id); return item ? [item] : []; });
  const lead = snapshot.lead[sort];
  return {
    items,
    leadId: lead && items.some((item) => item.lineageId === lead) ? lead : undefined,
    newCount: live.filter((item) => !item.rated && !snapshot.known.has(item.lineageId)).length,
  };
}

/** How many unanswered items one page of the feed adds. A page of the screen, not a limit: scrolling to the end shows the next. */
export const FEED_PAGE_SIZE = 24;

/**
 * The part of the feed that is on screen: the newest `pages` pages of unanswered items, plus the answered items that arrived since the
 * oldest of them. Predictions are read for these items only. The server's own order (newest arrival first) decides which items are next,
 * so nothing has to be read about the older ones to know where the next page starts.
 */
export function feedWindow(items: FeedItem[], pages: number, pageSize = FEED_PAGE_SIZE): FeedItem[] {
  const newestFirst = [...items].sort((left, right) => (referenceArrivalTime(right.reference) ?? 0) - (referenceArrivalTime(left.reference) ?? 0)
    || left.lineageId.localeCompare(right.lineageId));
  const wanted = Math.max(1, pages) * pageSize;
  let unrated = 0;
  let cut = newestFirst.length;
  for (let index = 0; index < newestFirst.length; index += 1) {
    if (newestFirst[index].rated) continue;
    unrated += 1;
    if (unrated === wanted) { cut = index + 1; break; }
  }
  return newestFirst.slice(0, cut);
}

/**
 * Add a later page to the order: older items go after everything already placed, each sort in its own order, so nothing above moves.
 * Items that arrived after the snapshot are not added here; they wait behind the "new items" pill as before.
 */
export function extendFeedOrderSnapshot(snapshot: FeedOrderSnapshot, items: FeedItem[]): FeedOrderSnapshot {
  const fresh = items.filter((item) => !snapshot.known.has(item.lineageId));
  if (!fresh.length) return snapshot;
  return {
    ...snapshot,
    known: new Set([...snapshot.known, ...fresh.map((item) => item.lineageId)]),
    unrated: new Set([...snapshot.unrated, ...fresh.filter((item) => !item.rated).map((item) => item.lineageId)]),
    best: [...snapshot.best, ...orderFeedItems(fresh, "best").map((item) => item.lineageId)],
    newest: [...snapshot.newest, ...orderFeedItems(fresh, "newest").map((item) => item.lineageId)],
    quality: [...snapshot.quality, ...orderFeedItems(fresh, "quality").map((item) => item.lineageId)],
  };
}

/**
 * The items in `live` that were already in the newsroom when the snapshot was taken (`seen`) but not yet placed: the next page, as opposed to
 * items that arrived since, which wait behind the new-items pill.
 */
export function laterPageItems(snapshot: FeedOrderSnapshot, seen: ReadonlySet<string>, live: FeedItem[]): FeedItem[] {
  return live.filter((item) => seen.has(item.lineageId) && !snapshot.known.has(item.lineageId));
}
