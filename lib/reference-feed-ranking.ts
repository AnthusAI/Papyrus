/**
 * How the References feed is ordered, in plain words (the "How this feed is ranked" popover says them too):
 *   - One list, two sorts. "Best bets" is the Cyclotron's confidence that you will Accept (P), highest first; a prediction of
 *     Accept at 80% is P = 0.8, a prediction of Reject at 80% is P = 0.2, no prediction is P = 0.5. Age does not change it.
 *   - "Newest" is reverse chronological by when the Reference arrived.
 *   - Ties go to the newest item, then to a stable id order.
 *   - "Unrated only" shows References nobody has answered; "Include rated" adds the answered ones to the same list.
 * Nothing is cut off by age, and age never changes the order of Best bets: the original confidence is what ranks.
 *
 * In the app the order comes from the two indexes on Reference, one page at a time (lib/reference-feed-pages.ts); the functions here rank
 * a list already in memory (the saved copy shown while the first page loads) and say what the lead card is.
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
    probability: typeof reference.predictedAcceptProbability === "number" ? reference.predictedAcceptProbability : acceptProbability(decision),
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
