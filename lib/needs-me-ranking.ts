/**
 * How the "What needs me" feed is ordered, and which items the Cyclotron is confident enough about to decide on its own.
 *
 * The feed holds several kinds of item (a Reference, an AI draft, a story review, a held email, a capture that may be cut off, a flag).
 * What they share is one question: where would a person's answer change the most? In plain words, as the page says them:
 *   1. Hard gates first. Nothing continues until a person decides one, so it leads, oldest first.
 *   2. Then the interim "value of your input" score:
 *        value = uncertainty x importance x freshness
 *      - uncertainty is 1 - |2P - 1|, where P is the Cyclotron's probability that you would Accept. A coin toss (P = 0.5) is 1, a
 *        certainty is 0. An item with no prediction is 0.5: we do not know how unsure we are.
 *      - importance is the item's own priority (a relevance score, or a story or section priority). It is 1 until a source gives one.
 *      - freshness is exp(-age / tau), the weight the References feed already uses; tau is learned from how old the References you
 *        accepted were when you accepted them (reference-feed-ranking.ts). With too few examples there is no decay.
 *   3. Types are interleaved, never more than two of one type in a row while another type is waiting, so a long run of References
 *      does not bury the drafts and emails behind it.
 *   4. Confident items do not ask for you. An item whose uncertainty is below the threshold goes to "Decided automatically", where it
 *      can be overruled. The threshold is the median uncertainty of the predictions you have historically confirmed; with fewer than
 *      10 such examples there is no threshold and nothing is skipped. A hard gate, an item the Cyclotron itself sent to review, and
 *      an item with no prediction are never skipped.
 *
 * The scoring sits behind one interface, `AttentionModel`. A future Cyclotron "attention" decision (a model that predicts the value of
 * an editor's input directly) replaces `interimAttention` and nothing else in the page changes.
 */
import type { ReferenceRecord } from "./category-repository";
import { referenceLineageId } from "./newsroom-references";
import { normalizeReferenceCurationStatus } from "./reference-policy";
import type { RelevanceDecisionView } from "./relevance-decisions";
import { acceptProbability, MINIMUM_FRESHNESS_EXAMPLES, type FeedFreshness } from "./reference-feed-ranking";

export type NeedsMeType = "reference" | "draft" | "stage_review" | "held_email" | "incomplete_capture" | "concept_proposal" | "flag";

export const NEEDS_ME_TYPES: readonly NeedsMeType[] = ["reference", "draft", "stage_review", "held_email", "incomplete_capture", "concept_proposal", "flag"];

/** The pills above the feed. */
export type NeedsMeFilter = "all" | "references" | "drafts" | "stories" | "email" | "captures" | "other";
export const NEEDS_ME_FILTERS: readonly NeedsMeFilter[] = ["all", "references", "drafts", "stories", "email", "captures", "other"];
export const NEEDS_ME_FILTER_LABELS: Record<NeedsMeFilter, string> = {
  all: "All", references: "References", drafts: "Proposed Stories", stories: "Stories", email: "Email", captures: "Captures", other: "Other",
};

const FILTER_OF: Record<NeedsMeType, Exclude<NeedsMeFilter, "all">> = {
  reference: "references", draft: "drafts", stage_review: "stories", held_email: "email", incomplete_capture: "captures", concept_proposal: "other", flag: "other",
};

export function filterOfType(type: NeedsMeType): Exclude<NeedsMeFilter, "all"> {
  return FILTER_OF[type];
}

export function matchesFilter(item: Pick<NeedsMeItem, "type">, filter: NeedsMeFilter): boolean {
  return filter === "all" || FILTER_OF[item.type] === filter;
}

/** The words for a type, used on the card and in the detail pane. */
export const NEEDS_ME_TYPE_LABELS: Record<NeedsMeType, string> = {
  reference: "Reference", draft: "Proposed Story", stage_review: "Story review", held_email: "Held email", incomplete_capture: "Capture check", concept_proposal: "Concept proposal", flag: "For your information",
};

export type NeedsMePrediction = {
  label: "accept" | "reject";
  /** P(the editor accepts). */
  pAccept: number;
  /** The confidence the Cyclotron recorded, when it did. */
  confidence: number | null;
};

/** Open until a person decides; the three answers are the page's one vocabulary (a flag is acknowledged). */
export type NeedsMeDecisionState = "open" | "accepted" | "rejected" | "acknowledged";

export type NeedsMeItem<Payload = unknown> = {
  type: NeedsMeType;
  /** Unique across types. */
  id: string;
  title: string;
  dek: string | null;
  /** The picture for the card, or null for the source's fallback tile. */
  image: string | null;
  source: string;
  host: string | null;
  /** When it reached the newsroom, in milliseconds; null when unknown. */
  createdAt: number | null;
  prediction?: NeedsMePrediction;
  /** The item's own priority. 1 until a source supplies one (a relevance score, a story or section priority). */
  importance: number;
  /** 1 - |2P - 1| with a prediction, 0.5 without. */
  uncertainty: number;
  decisionState: NeedsMeDecisionState;
  /** What happens if the editor ignores it, in words. */
  defaultOutcome: string;
  /** Nothing continues until a person decides it. */
  hardGate: boolean;
  /** The Cyclotron or the step that raised it asked for a person: never decided automatically. */
  askedForReview: boolean;
  payload: Payload;
};

// --- the scoring --------------------------------------------------------------------------------------------------------

export const UNKNOWN_UNCERTAINTY = 0.5;

/** 1 - |2P - 1|: 1 at a coin toss, 0 at a certainty. 0.5 when there is no prediction. */
export function uncertaintyOf(pAccept: number | undefined): number {
  if (pAccept === undefined || !Number.isFinite(pAccept)) return UNKNOWN_UNCERTAINTY;
  return 1 - Math.abs(2 * Math.min(1, Math.max(0, pAccept)) - 1);
}

export function predictionOf(decision: RelevanceDecisionView | undefined): NeedsMePrediction | undefined {
  if (!decision) return undefined;
  const pAccept = acceptProbability(decision);
  return { label: decision.label === (decision.positiveLabel ?? "include") ? "accept" : "reject", pAccept, confidence: decision.confidence };
}

const DAY_MILLISECONDS = 86_400_000;

/** exp(-age / tau) at `now`; 1 without a learned tau or an unknown arrival. The References feed's own weight. */
export function freshnessAt(createdAt: number | null, freshness: FeedFreshness, now: number): number {
  if (freshness.tauDays === null || createdAt === null) return 1;
  return Math.exp(-Math.max(now - createdAt, 0) / DAY_MILLISECONDS / freshness.tauDays);
}

export type AttentionContext = { now: number; freshness: FeedFreshness };

/**
 * The value of this editor's input on one item. Higher is earlier. The interim model below is a formula; a Cyclotron "attention"
 * decision implements the same interface and is passed to `rankNeedsMe` in its place.
 */
export interface AttentionModel {
  readonly id: string;
  value(item: NeedsMeItem, context: AttentionContext): number;
}

export const interimAttention: AttentionModel = {
  id: "interim-value-of-input",
  value: (item, { now, freshness }) => item.uncertainty * item.importance * freshnessAt(item.createdAt, freshness, now),
};

// --- confident items ----------------------------------------------------------------------------------------------------

export const MINIMUM_CONFIRMED_EXAMPLES = MINIMUM_FRESHNESS_EXAMPLES;

export type ConfidenceThreshold = {
  /** Null with fewer than MINIMUM_CONFIRMED_EXAMPLES confirmed predictions: nothing is guessed, nothing is skipped. */
  threshold: number | null;
  /** How many predictions the editor has confirmed. */
  examples: number;
};

/**
 * Uncertainty below which the Cyclotron decides without you: the median uncertainty of the predictions you confirmed (the Reference you
 * accepted or rejected agrees with what the Cyclotron said). Half of what you tend to confirm is then confident enough to skip.
 * `ignore` keeps the item an editor just rated from moving the very feed they are looking at.
 */
export function learnConfidenceThreshold(
  references: ReferenceRecord[],
  decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined,
  ignore: ReadonlySet<string> = new Set(),
): ConfidenceThreshold {
  const confirmed: number[] = [];
  for (const reference of references) {
    const lineageId = referenceLineageId(reference);
    const decision = decisions?.get(lineageId);
    const status = normalizeReferenceCurationStatus(reference.curationStatus);
    if (!decision || ignore.has(lineageId) || (status !== "accepted" && status !== "rejected")) continue;
    const prediction = predictionOf(decision);
    if (prediction && prediction.label === (status === "accepted" ? "accept" : "reject")) confirmed.push(uncertaintyOf(prediction.pAccept));
  }
  if (confirmed.length < MINIMUM_CONFIRMED_EXAMPLES) return { threshold: null, examples: confirmed.length };
  confirmed.sort((left, right) => left - right);
  const middle = Math.floor(confirmed.length / 2);
  return { threshold: confirmed.length % 2 ? confirmed[middle] : (confirmed[middle - 1] + confirmed[middle]) / 2, examples: confirmed.length };
}

/** True when the Cyclotron is sure enough that the item does not need a person. */
export function isConfident(item: NeedsMeItem, threshold: number | null): boolean {
  return threshold !== null && item.decisionState === "open" && !item.hardGate && !item.askedForReview && item.prediction !== undefined && item.uncertainty < threshold;
}

// --- the order ----------------------------------------------------------------------------------------------------------

export const MAXIMUM_RUN = 2;

/**
 * Apple-News-style mixing: keep the order, but never more than `maxRun` of one type in a row while another type is waiting. When a run
 * is full, the highest-ranked item of a different type goes next. `prior` is what already sits in front of this list.
 */
export function interleaveByType<T extends { type: NeedsMeType }>(ordered: readonly T[], maxRun = MAXIMUM_RUN, prior: readonly NeedsMeType[] = []): T[] {
  const remaining = [...ordered];
  const placed: T[] = [];
  const history = [...prior];
  while (remaining.length) {
    const last = history[history.length - 1];
    let run = 0;
    for (let index = history.length - 1; index >= 0 && history[index] === last; index -= 1) run += 1;
    let pick = 0;
    if (last !== undefined && run >= maxRun) {
      const alternative = remaining.findIndex((item) => item.type !== last);
      if (alternative >= 0) pick = alternative;
    }
    const [next] = remaining.splice(pick, 1);
    placed.push(next);
    history.push(next.type);
  }
  return placed;
}

export type NeedsMeRanking<P = unknown> = {
  /** Hard gates first, then everything that asks for a person, interleaved. */
  feed: NeedsMeItem<P>[];
  /** Confident items: decided by the Cyclotron unless overruled. Newest first. */
  auto: NeedsMeItem<P>[];
  scores: ReadonlyMap<string, number>;
  threshold: ConfidenceThreshold;
};

function newestFirst(left: NeedsMeItem, right: NeedsMeItem): number {
  return (right.createdAt ?? 0) - (left.createdAt ?? 0) || left.id.localeCompare(right.id);
}

export function rankNeedsMe<P>(
  items: readonly NeedsMeItem<P>[],
  options: { now: number; freshness: FeedFreshness; threshold: ConfidenceThreshold; attention?: AttentionModel },
): NeedsMeRanking<P> {
  const attention = options.attention ?? interimAttention;
  const context: AttentionContext = { now: options.now, freshness: options.freshness };
  const scores = new Map(items.map((item) => [item.id, attention.value(item, context)]));
  const score = (item: NeedsMeItem) => scores.get(item.id) ?? 0;
  const gates = items.filter((item) => item.hardGate).sort((left, right) => (left.createdAt ?? 0) - (right.createdAt ?? 0) || left.id.localeCompare(right.id));
  const rest = items.filter((item) => !item.hardGate);
  const auto = rest.filter((item) => isConfident(item, options.threshold.threshold)).sort(newestFirst);
  const autoIds = new Set(auto.map((item) => item.id));
  const asking = rest.filter((item) => !autoIds.has(item.id)).sort((left, right) => score(right) - score(left) || newestFirst(left, right));
  const mixed = interleaveByType(asking, MAXIMUM_RUN, gates.map((item) => item.type));
  return { feed: [...gates, ...mixed], auto, scores, threshold: options.threshold };
}

// --- one order per visit ------------------------------------------------------------------------------------------------

/**
 * The order of the feed, taken once per visit when it has loaded and then left alone: selecting, deciding, a background refresh and a
 * cache revalidation never re-rank it. Items that arrive later are counted as new and wait behind an "N new items: show" pill.
 * The same rule as the References feed.
 */
export type NeedsMeSnapshot = { known: ReadonlySet<string>; feed: string[]; auto: string[] };

export function takeNeedsMeSnapshot(ranking: Pick<NeedsMeRanking, "feed" | "auto">): NeedsMeSnapshot {
  return {
    known: new Set([...ranking.feed, ...ranking.auto].map((item) => item.id)),
    feed: ranking.feed.map((item) => item.id),
    auto: ranking.auto.map((item) => item.id),
  };
}

/** The live items placed where the snapshot put them. Their content stays current; their places do not. */
export function applyNeedsMeSnapshot<P>(snapshot: NeedsMeSnapshot, live: Pick<NeedsMeRanking<P>, "feed" | "auto">): { feed: NeedsMeItem<P>[]; auto: NeedsMeItem<P>[]; newCount: number } {
  const byId = new Map<string, NeedsMeItem<P>>();
  for (const item of [...live.auto, ...live.feed]) byId.set(item.id, item);
  const pick = (ids: string[]) => ids.flatMap((id) => { const item = byId.get(id); return item ? [item] : []; });
  const newCount = [...live.feed, ...live.auto].filter((item) => !snapshot.known.has(item.id) && item.decisionState === "open").length;
  return { feed: pick(snapshot.feed), auto: pick(snapshot.auto), newCount };
}

// --- counts and "you're shaping this" -----------------------------------------------------------------------------------

export type NeedsMeCounts = Record<NeedsMeFilter, number>;

/** What waits for a person, by pill: only open items count. */
export function countNeedsMe(items: readonly Pick<NeedsMeItem, "type" | "decisionState">[]): NeedsMeCounts {
  const counts: NeedsMeCounts = { all: 0, references: 0, drafts: 0, stories: 0, email: 0, captures: 0, other: 0 };
  for (const item of items) {
    if (item.decisionState !== "open") continue;
    counts.all += 1;
    counts[FILTER_OF[item.type]] += 1;
  }
  return counts;
}

/** Monday 00:00 UTC of the week that contains `now`: "this week" is a calendar week, not a rolling window. */
export function weekStartUtc(now: number): number {
  const date = new Date(now);
  const day = (date.getUTCDay() + 6) % 7; // Monday = 0
  return Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate() - day);
}

export type ShapingStats = {
  /** Everything you decided this week, of any type. */
  decisions: number;
  /** Of the References you rated this week that had a prediction: you agreed with the Cyclotron. */
  agreed: number;
  /** ... and you overruled it. */
  overruled: number;
};

/** The "You're shaping this" strip. `decidedAt` lists when each decision was made (see recentDecisions in notification-feed.ts). */
export function shapingThisWeek(input: {
  decidedAt: readonly string[];
  references: ReferenceRecord[];
  decisions: ReadonlyMap<string, RelevanceDecisionView> | undefined;
  now: number;
}): ShapingStats {
  const since = weekStartUtc(input.now);
  const thisWeek = (iso: string | null | undefined) => {
    const time = iso ? Date.parse(iso) : NaN;
    return Number.isFinite(time) && time >= since && time <= input.now;
  };
  let agreed = 0;
  let overruled = 0;
  for (const reference of input.references) {
    const status = normalizeReferenceCurationStatus(reference.curationStatus);
    if ((status !== "accepted" && status !== "rejected") || !thisWeek(reference.curationStatusUpdatedAt)) continue;
    const prediction = predictionOf(input.decisions?.get(referenceLineageId(reference)));
    if (!prediction) continue;
    if (prediction.label === (status === "accepted" ? "accept" : "reject")) agreed += 1;
    else overruled += 1;
  }
  return { decisions: input.decidedAt.filter(thisWeek).length, agreed, overruled };
}
