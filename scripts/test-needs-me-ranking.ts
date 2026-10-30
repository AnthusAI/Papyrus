/** The "What needs me" feed's model: the value-of-input score, hard gates first, interleaving, confident items, one order per visit, and each source's adapter. */
import assert from "node:assert/strict";
import type { ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import type { MonitoringEmailSummary } from "../lib/monitoring-overview";
import type { CaptureStatus } from "../lib/reference-capture";
import { FIXTURE_DRAFTS, FIXTURE_HELD_EMAILS, FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
import { draftView } from "../lib/review-drafts";
import {
  applyNeedsMeSnapshot, countNeedsMe, interleaveByType, interimAttention, isConfident, learnConfidenceThreshold, matchesFilter, rankNeedsMe, shapingThisWeek,
  takeNeedsMeSnapshot, uncertaintyOf, weekStartUtc, type AttentionModel, type NeedsMeItem, type NeedsMeType,
} from "../lib/needs-me-ranking";
import { buildNeedsMeItems, captureIsIncomplete, conceptProposalItems, waitingTextFor, type NeedsMeEntry } from "../lib/needs-me-items";

const NOW = Date.parse("2026-10-27T12:00:00Z");
const DAY = 86_400_000;
const NO_THRESHOLD = { threshold: null, examples: 0 };

const item = (id: string, type: NeedsMeType, fields: Partial<NeedsMeItem> = {}): NeedsMeItem => ({
  type, id, title: id, dek: null, image: null, source: "s", host: null, createdAt: NOW - DAY, importance: 1, uncertainty: 0.5, decisionState: "open",
  defaultOutcome: "", hardGate: false, askedForReview: false, payload: null, ...fields,
});
const predicted = (id: string, type: NeedsMeType, pAccept: number, fields: Partial<NeedsMeItem> = {}) =>
  item(id, type, { prediction: { label: pAccept >= 0.5 ? "accept" : "reject", pAccept, confidence: Math.max(pAccept, 1 - pAccept) }, uncertainty: uncertaintyOf(pAccept), ...fields });
const ids = (list: readonly { id: string }[]) => list.map((entry) => entry.id);

// Uncertainty: 1 at a coin toss, 0 at a certainty, 0.5 with no prediction.
assert.equal(uncertaintyOf(0.5), 1);
assert.equal(uncertaintyOf(1), 0);
assert.equal(uncertaintyOf(0), 0);
assert.ok(Math.abs(uncertaintyOf(0.9) - 0.2) < 1e-9 && Math.abs(uncertaintyOf(0.1) - 0.2) < 1e-9, "an Accept and a Reject at the same confidence are equally sure");
assert.equal(uncertaintyOf(undefined), 0.5);

// The interim score is uncertainty x importance. Age does not change it: the Cyclotron's recorded confidence is used as it was.
assert.equal(interimAttention.value(item("a", "draft", { uncertainty: 0.8, importance: 2 })), 1.6);
assert.equal(interimAttention.value(item("b", "draft", { uncertainty: 1, createdAt: NOW - 400 * DAY })), 1, "a year-old item scores the same as a fresh one");

// Hard gates first (oldest first), then the highest value of input, whatever the type.
const ranked = rankNeedsMe([
  predicted("sure-ref", "reference", 0.5),
  item("gate-new", "stage_review", { hardGate: true, createdAt: NOW - DAY }),
  item("gate-old", "stage_review", { hardGate: true, createdAt: NOW - 3 * DAY }),
  predicted("coin-toss", "reference", 0.5, { importance: 3 }),
  predicted("lean", "reference", 0.8),
  item("draft", "draft"),
], { threshold: NO_THRESHOLD });
assert.deepEqual(ids(ranked.feed).slice(0, 2), ["gate-old", "gate-new"], "hard gates lead, oldest first");
assert.equal(ranked.feed[2].id, "coin-toss", "then the highest value: a coin toss that matters most");
assert.ok(ranked.scores.get("coin-toss")! > ranked.scores.get("lean")!, "a lean is worth less than a coin toss");

// Interleaving: never three of a type in a row while another type waits; order otherwise kept.
const run = interleaveByType([item("r1", "reference"), item("r2", "reference"), item("r3", "reference"), item("r4", "reference"), item("d1", "draft"), item("e1", "held_email")]);
assert.deepEqual(ids(run), ["r1", "r2", "d1", "r3", "r4", "e1"], "the best of another type fills the third slot");
const only = interleaveByType([item("r1", "reference"), item("r2", "reference"), item("r3", "reference")]);
assert.deepEqual(ids(only), ["r1", "r2", "r3"], "with no alternative the run stays");
assert.deepEqual(ids(interleaveByType([item("r1", "reference"), item("d1", "draft")], 2, ["reference", "reference"])), ["d1", "r1"], "a run already in front counts");
const mixed = rankNeedsMe([
  ...Array.from({ length: 5 }, (_, index) => predicted(`ref-${index}`, "reference", 0.5, { createdAt: NOW - index * 60_000 })),
  item("draft-1", "draft", { uncertainty: 0.1 }), item("mail-1", "held_email", { uncertainty: 0.1 }),
], { threshold: NO_THRESHOLD });
const types = mixed.feed.map((entry) => entry.type);
for (let index = 2; index < types.length; index += 1) {
  if (types[index] === types[index - 1] && types[index] === types[index - 2]) assert.ok(types.slice(index).every((type) => type === types[index]), `no run of three while another type waits: ${types.join(",")}`);
}

// Confident items: below the threshold, with a prediction, not a gate, not asked-for. Learned from confirmed predictions; none with fewer than 10.
const reference = (id: string, status: string, fields: Record<string, unknown> = {}): ReferenceRecord => ({ id: `${id}-v1`, lineageId: id, title: id, externalItemId: id, curationStatus: status, ...fields } as unknown as ReferenceRecord);
const decision = (label: string, confidence: number, reviewRecommended = false): RelevanceDecisionView => ({
  decisionRelationId: "r", decisionId: "d", label, confidence, version: 1, reviewRecommended, reviewReason: null, reviewDetail: null, classes: ["include", "exclude"],
  positiveLabel: "include", question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt: null, provenance: null,
});
const confirmedRefs = Array.from({ length: 10 }, (_, index) => reference(`c${index}`, "accepted"));
const confirmedDecisions = new Map(confirmedRefs.map((entry, index) => [entry.lineageId!, decision("include", 0.8 + index * 0.02)]));
const few = learnConfidenceThreshold(confirmedRefs.slice(0, 9), confirmedDecisions);
assert.deepEqual(few, { threshold: null, examples: 9 }, "fewer than 10 confirmed predictions: nothing is guessed");
const learned = learnConfidenceThreshold(confirmedRefs, confirmedDecisions);
assert.equal(learned.examples, 10);
assert.ok(Math.abs(learned.threshold! - (uncertaintyOf(0.88) + uncertaintyOf(0.9)) / 2) < 1e-9, "the median uncertainty of the confirmed");
const overruledToo = learnConfidenceThreshold([...confirmedRefs, reference("x", "rejected")], new Map([...confirmedDecisions, ["x", decision("include", 0.95)]]));
assert.equal(overruledToo.examples, 10, "an overruled prediction is not a confirmation");
const sure = predicted("sure", "reference", 0.99);
assert.equal(isConfident(sure, learned.threshold), true);
assert.equal(isConfident(sure, null), false, "no threshold, nothing skipped");
assert.equal(isConfident({ ...sure, askedForReview: true }, learned.threshold), false, "an item the Cyclotron sent to review is never skipped");
assert.equal(isConfident({ ...sure, hardGate: true }, learned.threshold), false);
assert.equal(isConfident(item("none", "reference"), learned.threshold), false, "no prediction, no confidence");
assert.equal(isConfident({ ...sure, decisionState: "accepted" }, learned.threshold), false, "an item decided in this visit stays put");
const split = rankNeedsMe([sure, predicted("unsure", "reference", 0.55)], { threshold: learned });
assert.deepEqual([ids(split.feed), ids(split.auto)], [["unsure"], ["sure"]]);

// One order per visit: the snapshot keeps places while content changes; later arrivals wait behind the pill.
const first = rankNeedsMe([predicted("a", "reference", 0.5), predicted("b", "reference", 0.6), item("d", "draft")], { threshold: NO_THRESHOLD });
const snapshot = takeNeedsMeSnapshot(first);
const later = rankNeedsMe([predicted("b", "reference", 0.5), predicted("a", "reference", 0.9, { decisionState: "accepted" }), item("d", "draft"), predicted("new", "reference", 0.5)], { threshold: NO_THRESHOLD });
const placed = applyNeedsMeSnapshot(snapshot, later);
assert.deepEqual(ids(placed.feed), ids(first.feed), "deciding and re-scoring never re-rank");
assert.equal(placed.newCount, 1, "the arrival is counted, not placed");
assert.equal(placed.feed.find((entry) => entry.id === "a")!.decisionState, "accepted", "content stays current");

// A future Cyclotron attention decision replaces the formula through the same interface.
const reversed: AttentionModel = { id: "test", value: (entry) => -entry.uncertainty };
const swapped = rankNeedsMe([predicted("a", "reference", 0.5), predicted("b", "reference", 0.9)], { threshold: NO_THRESHOLD, attention: reversed });
assert.deepEqual(ids(swapped.feed), ["b", "a"]);

// Filters and counts: only what waits is counted; decided items stay on the page but not in the numbers.
const everything: NeedsMeItem[] = [
  item("1", "reference"), item("2", "reference", { decisionState: "accepted" }), item("3", "draft"), item("4", "stage_review"), item("5", "held_email"), item("6", "incomplete_capture"), item("7", "flag"), item("8", "concept_proposal"),
];
assert.deepEqual(countNeedsMe(everything), { all: 7, references: 1, drafts: 1, stories: 1, email: 1, captures: 1, other: 2 });
assert.deepEqual(everything.filter((entry) => matchesFilter(entry, "other")).map((entry) => entry.id), ["7", "8"]);
assert.equal(waitingTextFor(countNeedsMe(everything)), "1 Proposed Story, 1 reference, 1 story review, 1 held email, 1 capture to check and 2 other items waiting for you");
assert.equal(waitingTextFor(countNeedsMe([])), "All caught up");

// This week is a calendar week (Monday, UTC), and agreement counts only References that had a prediction.
assert.equal(new Date(weekStartUtc(NOW)).toISOString(), "2026-10-26T00:00:00.000Z");
assert.equal(new Date(weekStartUtc(Date.parse("2026-10-25T23:00:00Z"))).toISOString(), "2026-10-19T00:00:00.000Z", "Sunday belongs to the week before");
const rated = [reference("agree", "accepted", { curationStatusUpdatedAt: "2026-10-27T09:00:00Z" }), reference("overrule", "rejected", { curationStatusUpdatedAt: "2026-10-26T09:00:00Z" }),
  reference("old", "accepted", { curationStatusUpdatedAt: "2026-10-20T09:00:00Z" }), reference("unpredicted", "accepted", { curationStatusUpdatedAt: "2026-10-27T09:00:00Z" })];
const stats = shapingThisWeek({ decidedAt: ["2026-10-27T09:00:00Z", "2026-10-26T09:00:00Z", "2026-10-20T09:00:00Z", "2026-10-27T09:00:00Z"], references: rated, now: NOW,
  decisions: new Map([["agree", decision("include", 0.9)], ["overrule", decision("include", 0.8)], ["old", decision("include", 0.9)]]) });
assert.deepEqual(stats, { decisions: 3, agreed: 1, overruled: 1 });

// The adapters: what each source becomes.
const capture = (state: CaptureStatus["state"], extra: Partial<CaptureStatus> = {}): CaptureStatus => ({ state, words: 10, estimated: false, source: "curation", ...extra });
assert.equal(captureIsIncomplete(capture("thin")), true);
assert.equal(captureIsIncomplete(capture("none")), true, "a curation card that records no text");
assert.equal(captureIsIncomplete(capture("none", { source: "none" })), false, "nothing was attempted, so nothing is incomplete");
assert.equal(captureIsIncomplete(capture("thin", { assessment: "complete" })), false, "an editor's verdict settles it");
assert.equal(captureIsIncomplete(capture("full")), false);
const drafts = Object.fromEntries(FIXTURE_DRAFTS.map((row) => [row.id, draftView(row)]));
const email: MonitoringEmailSummary = FIXTURE_HELD_EMAILS[0];
const built = buildNeedsMeItems({
  references: [reference("ref-p", "pending", { createdAt: "2026-10-26T10:00:00Z", sourceUri: "https://example.org/p" }), reference("ref-cut", "pending"), reference("ref-done", "accepted"), reference("ref-archived", "archived")],
  decisions: new Map([["ref-p", decision("include", 0.7, true)]]), previews: new Map(), captures: new Map([["ref-cut", capture("thin")]]), visitRated: new Set(),
  requests: FIXTURE_REVIEW_REQUESTS, drafts, missingDrafts: new Set(["proposal-9"]), draftsState: "ready", stay: new Set(), bySource: new Map(),
  storyTitles: { "story-ruling-1": "Board refuses registration" }, storyExcerpts: { "story-ruling-1": "The Board refused." }, deletedStories: new Set(), emails: [email], emailsDecided: new Map(),
});
const byId = new Map(built.map((entry) => [entry.id, entry] as const));
const type = (id: string) => byId.get(id)?.type;
assert.equal(type("ref-p"), "reference");
assert.equal(type("ref-cut"), "incomplete_capture", "a cut-off capture asks a different question of the same Reference");
assert.equal(byId.has("ref-done") || byId.has("ref-archived"), false, "only pending References");
assert.deepEqual(["rr-soft-2#proposal-1", "rr-soft-2#proposal-2", "rr-soft-2#proposal-3"].map(type), ["draft", "draft", "draft"]);
assert.equal(type("rr-hard-1"), "stage_review");
assert.equal(byId.get("rr-hard-1")!.hardGate, true);
assert.equal(byId.get("rr-hard-1")!.payload && (byId.get("rr-hard-1")!.payload as { excerpt: string }).excerpt, "The Board refused.");
assert.equal(type("rr-flag-1"), "flag");
assert.equal(type("email#receipt-held-1"), "held_email");
const ref = byId.get("ref-p")!;
assert.deepEqual([ref.prediction?.label, ref.prediction?.pAccept, ref.askedForReview, Math.round(ref.uncertainty * 100) / 100], ["accept", 0.7, true, 0.6]);
assert.ok(ref.defaultOutcome.includes("Accept 70%"), "the default is the Cyclotron's suggestion, said in words");
assert.equal(byId.get("ref-cut")!.uncertainty, 0.5, "no prediction is 0.5");
assert.match(byId.get("rr-soft-2#proposal-1")!.defaultOutcome, /^Closes on 2026-10-30/);
assert.match(byId.get("email#receipt-held-1")!.defaultOutcome, /stays held privately/);
assert.equal(byId.get("rr-soft-2#proposal-1")!.title, "Sparse attention goes open");
for (const entry of built) assert.ok(entry.defaultOutcome.length > 0 && entry.importance === 1, `${entry.id} says what happens if ignored`);
assert.deepEqual(conceptProposalItems([{ id: "c", title: "t", summary: null, proposedBy: "reader", createdAt: null }]), [] as NeedsMeEntry[], "the concept and reader proposal adapters are typed stubs");
// A decided held email stays in place for the visit, showing its answer; a decided one from before does not return.
const decidedMail = buildNeedsMeItems({ ...{ references: [], decisions: undefined, previews: new Map(), captures: undefined, visitRated: new Set(), requests: [], drafts: {}, missingDrafts: new Set(), draftsState: "ready" as const, stay: new Set<string>(), bySource: new Map(), storyTitles: {}, storyExcerpts: {}, deletedStories: new Set<string>() }, emails: [email], emailsDecided: new Map([["receipt-held-1", "reject" as const]]) });
assert.equal(decidedMail[0].decisionState, "rejected");

console.log("needs me ranking: ok");
