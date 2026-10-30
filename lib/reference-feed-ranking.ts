/**
 * How the References feed is ordered, in plain words (the "How this feed is ranked" popover says them too):
 *   - One list, two sorts. "Best bets" is the Cyclotron's confidence that you will Accept (P), highest first; a prediction of
 *     Accept at 80% is P = 0.8, a prediction of Reject at 80% is P = 0.2, no prediction is P = 0.5. Age does not change it.
 *   - "Newest" is reverse chronological by when the Reference arrived.
 *   - Ties go to the newest item, then to a stable id order.
 *   - "Unrated only" shows References nobody has answered; "Include rated" adds the answered ones to the same list.
 * Nothing is cut off by age, and age never changes the order of Best bets: the original confidence is what ranks.
 */
import type { ReferenceRecord } from "./category-repository";
import type { RelevanceDecisionView } from "./relevance-decisions";
import { normalizeReferenceCurationStatus } from "./reference-policy";
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
  /** P(accept): the Cyclotron's confidence that the editor accepts. The Best bets sort key. */
  probability: number;
  /** True when a human has already answered (accepted or rejected). */
  rated: boolean;
};

export type FeedSort = "best" | "newest";
export type FeedShow = "unrated" | "all";
export const DEFAULT_FEED_SORT: FeedSort = "best";
export const DEFAULT_FEED_SHOW: FeedShow = "unrated";

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

/** Best bets: highest P(accept) first; ties go to the newest item, then to a stable id order. */
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

export function orderFeedItems(items: FeedItem[], sort: FeedSort): FeedItem[] {
  return [...items].sort(sort === "newest" ? compareNewest : compareBestBets);
}

/** The visible list: ordered by `sort`; "Unrated only" keeps the items answered during this visit, which stay in place. */
export function visibleFeedItems(items: FeedItem[], sort: FeedSort, show: FeedShow, visitRated: ReadonlySet<string> = new Set()): FeedItem[] {
  return orderFeedItems(items.filter((item) => show === "all" || !item.rated || visitRated.has(item.lineageId)), sort);
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
  /** The ones nobody had answered when the snapshot was taken: they stay listed under "Unrated only" after being rated this visit. */
  unrated: ReadonlySet<string>;
  best: string[];
  newest: string[];
  /** The lead card of each sort, taken with the order: it is never a predicted Reject when the snapshot is taken. */
  lead: { best: string | undefined; newest: string | undefined };
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
    lead: { best: feedLeadId(orderFeedItems(unrated, "best")), newest: feedLeadId(orderFeedItems(unrated, "newest")) },
  };
}

/** The visible list in the snapshot's order; records and predictions stay current. */
export function applyFeedOrderSnapshot(snapshot: FeedOrderSnapshot, live: FeedItem[], sort: FeedSort, show: FeedShow): {
  items: FeedItem[];
  leadId: string | undefined;
  newCount: number;
} {
  const byId = new Map(live.map((item) => [item.lineageId, item] as const));
  const items = (sort === "newest" ? snapshot.newest : snapshot.best)
    .filter((id) => show === "all" || snapshot.unrated.has(id))
    .flatMap((id) => { const item = byId.get(id); return item ? [item] : []; });
  const lead = snapshot.lead[sort];
  return {
    items,
    leadId: lead && items.some((item) => item.lineageId === lead) ? lead : undefined,
    newCount: live.filter((item) => !item.rated && !snapshot.known.has(item.lineageId)).length,
  };
}
