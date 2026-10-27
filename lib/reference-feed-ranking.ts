/**
 * How the References feed is ordered, and which cards belong in which tab.
 *
 * Plain words, as the "How this feed is ranked" popover says them:
 *   1. The Cyclotron's prediction becomes a probability that you will Accept (P). A prediction of Accept at 80% is
 *      P = 0.8; a prediction of Reject at 80% is P = 0.2; no prediction is P = 0.5.
 *   2. Old items lose their say. The score is 0.5 + (P - 0.5) * w, where w = exp(-age / tau) is a freshness weight.
 *      Age pulls an item toward "uncertain" (0.5), never to the bottom.
 *   3. tau is learned from how old the References you accepted were when you accepted them
 *      (tau = median age / ln 2). With fewer than 10 accepted examples nothing is guessed: no decay.
 *   4. Highest score first. The strongest Reject predictions end up last. Ties go to the newest item.
 *   5. Unrated items older than 3 tau move to "Earlier" at the bottom. Nothing is deleted.
 *
 * The same recipe ranks monitor stories (`learn_freshness` in src/papyrus_content/ideas/monitor_stories.py).
 */
import type { ReferenceRecord } from "./category-repository";
import type { RelevanceDecisionView } from "./relevance-decisions";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import { referenceLineageId } from "./newsroom-references";

/** Fewer accepted examples than this and there is no freshness weight: a constant is never guessed. */
export const MINIMUM_FRESHNESS_EXAMPLES = 10;
/** An unrated item whose age passes this many tau has a weight below exp(-3), about 5%, and moves to Earlier. */
export const EARLIER_AFTER_TAUS = 3;
/** The probability that stands for "no prediction". */
export const UNDECIDED_PROBABILITY = 0.5;
/** A prediction that recorded a label but no confidence is a mild lean, not a coin toss and not a certainty. */
export const UNRECORDED_CONFIDENCE = 0.6;

const DAY_MILLISECONDS = 86_400_000;

export type FeedFreshness = {
  /** Null when there were too few accepted examples to learn from: no decay at all. */
  tauDays: number | null;
  medianAgeDays: number | null;
  examples: number;
};

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

/**
 * tau from the age at acceptance of accepted References: median / ln 2, since the median age of an exponential
 * exp(-age / tau) is tau * ln 2. `ignore` keeps the item an editor just rated from moving the very ranking they are looking at.
 */
export function learnFreshness(references: ReferenceRecord[], ignore: ReadonlySet<string> = new Set()): FeedFreshness {
  const ages: number[] = [];
  for (const reference of references) {
    if (normalizeReferenceCurationStatus(reference.curationStatus) !== "accepted" || ignore.has(referenceLineageId(reference))) continue;
    const arrived = referenceArrivalTime(reference);
    const decided = timeOf(reference.curationStatusUpdatedAt);
    if (arrived === null || decided === null) continue;
    const age = (decided - arrived) / DAY_MILLISECONDS;
    if (age > 0) ages.push(age);
  }
  if (ages.length < MINIMUM_FRESHNESS_EXAMPLES) return { tauDays: null, medianAgeDays: null, examples: ages.length };
  ages.sort((left, right) => left - right);
  const middle = Math.floor(ages.length / 2);
  const median = ages.length % 2 ? ages[middle] : (ages[middle - 1] + ages[middle]) / 2;
  return { tauDays: median / Math.LN2, medianAgeDays: median, examples: ages.length };
}

/** exp(-age / tau) at `now`; 1 without a learned tau or an unreadable arrival. */
export function freshnessWeight(reference: ReferenceRecord, freshness: FeedFreshness, now: number): number {
  const arrived = referenceArrivalTime(reference);
  if (freshness.tauDays === null || arrived === null) return 1;
  return Math.exp(-Math.max(now - arrived, 0) / DAY_MILLISECONDS / freshness.tauDays);
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
  /** P(accept) before freshness. */
  probability: number;
  weight: number;
  /** 0.5 + (P - 0.5) * weight. Highest is first. */
  score: number;
  /** True when this unrated item is older than the Earlier threshold. */
  earlier: boolean;
};

export function scoreFeedItem(reference: ReferenceRecord, decision: RelevanceDecisionView | undefined, freshness: FeedFreshness, now: number): FeedItem {
  const probability = acceptProbability(decision);
  const weight = freshnessWeight(reference, freshness, now);
  const arrived = referenceArrivalTime(reference);
  const earlier = freshness.tauDays !== null && arrived !== null && (now - arrived) / DAY_MILLISECONDS > EARLIER_AFTER_TAUS * freshness.tauDays;
  return {
    reference,
    lineageId: referenceLineageId(reference),
    decision,
    probability,
    weight,
    score: UNDECIDED_PROBABILITY + (probability - UNDECIDED_PROBABILITY) * weight,
    earlier,
  };
}

/** Highest score first; ties go to the newest item, then to a stable id order. */
export function compareFeedItems(left: FeedItem, right: FeedItem): number {
  if (right.score !== left.score) return right.score - left.score;
  const newest = (referenceDisplayTime(right.reference) ?? 0) - (referenceDisplayTime(left.reference) ?? 0);
  return newest || left.lineageId.localeCompare(right.lineageId);
}

export type ReferenceFeedTabKey = "feed" | "rated" | "earlier";

export type ReferenceFeedPartition = {
  freshness: FeedFreshness;
  /** Pending items, plus the ones rated during this visit (they keep their place), best prediction first. */
  feed: FeedItem[];
  /** Everything an editor has answered, most recent answer first. */
  rated: FeedItem[];
  /** Unrated items past the freshness threshold, ranked like the feed. Still ratable. */
  earlier: FeedItem[];
};

/**
 * Splits canonical References into the three tabs.
 * `visitRated` holds lineage ids rated since the page opened: they stay in Feed, in place, showing the answer.
 */
export function partitionReferenceFeed(
  references: ReferenceRecord[],
  decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined,
  options: { now: number; visitRated?: ReadonlySet<string>; tauDaysOverride?: number | null },
): ReferenceFeedPartition {
  const visitRated = options.visitRated ?? new Set<string>();
  const learned = learnFreshness(references, visitRated);
  const freshness: FeedFreshness = options.tauDaysOverride && options.tauDaysOverride > 0
    ? { ...learned, tauDays: options.tauDaysOverride }
    : learned;
  const feed: FeedItem[] = [];
  const rated: FeedItem[] = [];
  const earlier: FeedItem[] = [];
  for (const reference of references) {
    const status = normalizeReferenceCurationStatus(reference.curationStatus);
    const lineageId = referenceLineageId(reference);
    const item = scoreFeedItem(reference, decisions?.get(lineageId), freshness, options.now);
    if (status === "archived") continue;
    if (status === "accepted" || status === "rejected") {
      rated.push(item);
      if (visitRated.has(lineageId)) (item.earlier ? earlier : feed).push(item);
    } else if (item.earlier) earlier.push(item);
    else feed.push(item);
  }
  feed.sort(compareFeedItems);
  earlier.sort(compareFeedItems);
  rated.sort((left, right) => (timeOf(right.reference.curationStatusUpdatedAt) ?? 0) - (timeOf(left.reference.curationStatusUpdatedAt) ?? 0)
    || left.lineageId.localeCompare(right.lineageId));
  return { freshness, feed, rated, earlier };
}

export type FeedGroupKey = "top" | "more" | "least";

/**
 * The feed's sections, from the ranked list (already best first). No fixed counts: Top predictions are the Accepts at least half as
 * strong as the strongest one, Least likely are the predicted Rejects, and More for you is everything between (weaker Accepts and
 * items with no prediction). A group with no members is absent.
 */
export function groupFeedItems(items: FeedItem[]): Array<{ key: FeedGroupKey; items: FeedItem[] }> {
  const strongest = items.reduce((best, item) => Math.max(best, item.score - UNDECIDED_PROBABILITY), 0);
  const groups: Record<FeedGroupKey, FeedItem[]> = { top: [], more: [], least: [] };
  for (const item of items) {
    const strength = item.score - UNDECIDED_PROBABILITY;
    if (strength < 0) groups.least.push(item);
    else if (strength > 0 && strength >= strongest / 2) groups.top.push(item);
    else groups.more.push(item);
  }
  return (["top", "more", "least"] as const).filter((key) => groups[key].length).map((key) => ({ key, items: groups[key] }));
}

/**
 * The order of the feed, taken once per visit when it loads and then left alone: selecting, rating, a background refresh and a cache
 * revalidation never re-rank it. Items that arrive later are counted as new and wait behind a "N new items: show" pill.
 */
export type FeedOrderSnapshot = {
  /** Every Reference lineage the snapshot knew about (pending, rated and earlier): anything else is new. */
  known: ReadonlySet<string>;
  feed: string[];
  earlier: string[];
  groups: Array<{ key: FeedGroupKey; ids: string[] }>;
  leadId: string | undefined;
};

export function takeFeedOrderSnapshot(partition: ReferenceFeedPartition): FeedOrderSnapshot {
  const groups = groupFeedItems(partition.feed);
  return {
    known: new Set([...partition.feed, ...partition.earlier, ...partition.rated].map((item) => item.lineageId)),
    feed: partition.feed.map((item) => item.lineageId),
    earlier: partition.earlier.map((item) => item.lineageId),
    groups: groups.map((group) => ({ key: group.key, ids: group.items.map((item) => item.lineageId) })),
    leadId: groups[0]?.key !== "least" ? groups[0]?.items[0]?.lineageId : undefined,
  };
}

/** The live partition with its feed order, sections and lead taken from the snapshot; records and scores stay current. */
export function applyFeedOrderSnapshot(snapshot: FeedOrderSnapshot, live: ReferenceFeedPartition): {
  partition: ReferenceFeedPartition;
  groups: Array<{ key: FeedGroupKey; items: FeedItem[] }>;
  leadId: string | undefined;
  newCount: number;
} {
  const byId = new Map<string, FeedItem>();
  for (const item of [...live.rated, ...live.earlier, ...live.feed]) byId.set(item.lineageId, item);
  const pick = (ids: string[]) => ids.flatMap((id) => { const item = byId.get(id); return item ? [item] : []; });
  const groups = snapshot.groups.map((group) => ({ key: group.key, items: pick(group.ids) })).filter((group) => group.items.length);
  const newCount = [...live.feed, ...live.earlier].filter((item) => !snapshot.known.has(item.lineageId)).length;
  return {
    partition: { ...live, feed: pick(snapshot.feed), earlier: pick(snapshot.earlier) },
    groups,
    leadId: snapshot.leadId && byId.has(snapshot.leadId) ? snapshot.leadId : undefined,
    newCount,
  };
}
