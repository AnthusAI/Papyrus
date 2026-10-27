import assert from "node:assert/strict";
import test from "node:test";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import {
  EARLIER_AFTER_TAUS,
  MINIMUM_FRESHNESS_EXAMPLES,
  acceptProbability,
  groupFeedItems,
  learnFreshness,
  partitionReferenceFeed,
} from "../lib/reference-feed-ranking";
import { dekAddsInformation, formatFeedAge, referenceDek, referencePreviewsByLineage, referenceSourceHost } from "../lib/reference-preview";
import { clearSavedNewsroomDisplay, loadFeedSnapshot, loadSessionDisplay, saveFeedSnapshot, saveSessionDisplay, SESSION_DISPLAY_TTL_MS } from "../lib/reference-feed-cache";

const DAY = 86_400_000;
const NOW = Date.parse("2026-10-27T12:00:00Z");
const ago = (days: number) => new Date(NOW - days * DAY).toISOString();

function reference(id: string, fields: Partial<ReferenceRecord> = {}): ReferenceRecord {
  return { id: `${id}-v1`, lineageId: id, versionState: "current", versionNumber: 1, corpusId: "c", externalItemId: id, title: id, sourceUri: `https://${id}.example.org/a`, curationStatus: "pending", createdAt: ago(0.5), ...fields };
}

function decision(label: "include" | "exclude", confidence: number | null): RelevanceDecisionView {
  return {
    decisionRelationId: "r", decisionId: "d", label, confidence, version: 1, reviewRecommended: false, reviewReason: null, reviewDetail: null,
    classes: ["include", "exclude"], positiveLabel: "include", question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt: null, provenance: null,
  };
}

function ids(items: Array<{ lineageId: string }>) { return items.map((item) => item.lineageId); }

test("A prediction becomes a probability that the editor accepts", () => {
  assert.equal(acceptProbability(decision("include", 0.8)), 0.8);
  assert.ok(Math.abs(acceptProbability(decision("exclude", 0.8)) - 0.2) < 1e-9);
  assert.equal(acceptProbability(undefined), 0.5, "no prediction sits in the middle");
  assert.ok(acceptProbability(decision("include", null)) > 0.5 && acceptProbability(decision("include", null)) < 0.8, "an unrecorded confidence is a mild lean");
});

test("Ranking: strongest Accepts first, no prediction in the middle, strongest Rejects last", () => {
  const references = ["weak-accept", "none", "strong-reject", "strong-accept", "weak-reject"].map((id) => reference(id));
  const decisions = new Map<string, RelevanceDecisionView>([
    ["weak-accept", decision("include", 0.6)], ["strong-accept", decision("include", 0.95)],
    ["weak-reject", decision("exclude", 0.6)], ["strong-reject", decision("exclude", 0.95)],
  ]);
  const { feed } = partitionReferenceFeed(references, decisions, { now: NOW });
  assert.deepEqual(ids(feed), ["strong-accept", "weak-accept", "none", "weak-reject", "strong-reject"]);
});

test("Age pulls a prediction toward uncertain, never to the bottom", () => {
  // Ten accepted items, each accepted two days after it arrived: tau = 2 / ln 2 days (a half-life of two days).
  const learned = Array.from({ length: 10 }, (_, index) => reference(`old-${index}`, { curationStatus: "accepted", createdAt: ago(12), curationStatusUpdatedAt: ago(10) }));
  const fresh = reference("fresh-accept", { createdAt: ago(0.1) });
  const stale = reference("stale-accept", { createdAt: ago(4) });
  const staleReject = reference("stale-reject", { createdAt: ago(4) });
  const freshReject = reference("fresh-reject", { createdAt: ago(0.1) });
  const decisions = new Map<string, RelevanceDecisionView>([
    ["fresh-accept", decision("include", 0.9)], ["stale-accept", decision("include", 0.9)],
    ["fresh-reject", decision("exclude", 0.9)], ["stale-reject", decision("exclude", 0.9)],
  ]);
  const partition = partitionReferenceFeed([...learned, fresh, stale, staleReject, freshReject], decisions, { now: NOW });
  assert.ok(Math.abs(partition.freshness.tauDays! - 2 / Math.LN2) < 1e-6, "tau is the median age at acceptance over ln 2");
  const byId = new Map([...partition.feed, ...partition.earlier].map((item) => [item.lineageId, item]));
  // After two half-lives (4 days) the 0.9 prediction keeps a quarter of its distance from 0.5.
  assert.ok(Math.abs(byId.get("stale-accept")!.score - (0.5 + 0.4 * 0.25)) < 1e-6);
  assert.ok(Math.abs(byId.get("stale-reject")!.score - (0.5 - 0.4 * 0.25)) < 1e-6);
  assert.deepEqual(ids(partition.feed), ["fresh-accept", "stale-accept", "stale-reject", "fresh-reject"], "a stale Reject ranks above a fresh Reject: decay is toward the middle");
});

test("Fewer than ten accepted examples means no decay and no guessed constant", () => {
  const few = Array.from({ length: MINIMUM_FRESHNESS_EXAMPLES - 1 }, (_, index) => reference(`a${index}`, { curationStatus: "accepted", createdAt: ago(9), curationStatusUpdatedAt: ago(8) }));
  assert.deepEqual(learnFreshness(few), { tauDays: null, medianAgeDays: null, examples: 9 });
  const ancient = reference("ancient", { createdAt: ago(400) });
  const partition = partitionReferenceFeed([...few, ancient], new Map([["ancient", decision("include", 0.9)]]), { now: NOW });
  assert.equal(partition.earlier.length, 0, "nothing moves to Earlier without a learned tau");
  assert.equal(partition.feed[0].score, 0.9, "and the score is the probability itself");
});

test("Unrated items older than three tau move to Earlier, still ratable and never dropped", () => {
  const learned = Array.from({ length: 10 }, (_, index) => reference(`a${index}`, { curationStatus: "accepted", createdAt: ago(6), curationStatusUpdatedAt: ago(5) }));
  const tau = 1 / Math.LN2;
  const young = reference("young", { createdAt: ago(EARLIER_AFTER_TAUS * tau - 0.2) });
  const aged = reference("aged", { createdAt: ago(EARLIER_AFTER_TAUS * tau + 0.2) });
  const partition = partitionReferenceFeed([...learned, young, aged], undefined, { now: NOW });
  assert.deepEqual(ids(partition.feed), ["young"]);
  assert.deepEqual(ids(partition.earlier), ["aged"]);
  assert.equal(partition.rated.length, 10);
});

test("A card rated this visit stays in place, and on the next load it is under Rated, most recent first", () => {
  const references = ["a", "b", "c"].map((id, index) => reference(id, { createdAt: ago(0.1 + index * 0.1) }));
  const decisions = new Map<string, RelevanceDecisionView>([["a", decision("include", 0.9)], ["b", decision("include", 0.8)], ["c", decision("include", 0.7)]]);
  const before = partitionReferenceFeed(references, decisions, { now: NOW });
  assert.deepEqual(ids(before.feed), ["a", "b", "c"]);
  const rated = references.map((item) => (item.lineageId === "b" ? { ...item, curationStatus: "accepted", curationStatusUpdatedAt: ago(0) } : item));
  const sameVisit = partitionReferenceFeed(rated, decisions, { now: NOW, visitRated: new Set(["b"]) });
  assert.deepEqual(ids(sameVisit.feed), ["a", "b", "c"], "same place, now showing the answer");
  assert.deepEqual(ids(sameVisit.rated), ["b"]);
  const nextLoad = partitionReferenceFeed(rated, decisions, { now: NOW });
  assert.deepEqual(ids(nextLoad.feed), ["a", "c"]);
  const more = rated.map((item) => (item.lineageId === "a" ? { ...item, curationStatus: "rejected", curationStatusUpdatedAt: ago(0.2) } : item));
  assert.deepEqual(ids(partitionReferenceFeed(more, decisions, { now: NOW }).rated), ["b", "a"], "Rated is most recent first");
});

test("Rating one item does not move the others: tau ignores what was rated this visit", () => {
  const learned = Array.from({ length: 10 }, (_, index) => reference(`a${index}`, { curationStatus: "accepted", createdAt: ago(6), curationStatusUpdatedAt: ago(4) }));
  const rated = reference("just-rated", { curationStatus: "accepted", createdAt: ago(20), curationStatusUpdatedAt: ago(0) });
  assert.equal(learnFreshness([...learned, rated], new Set(["just-rated"])).tauDays, learnFreshness(learned).tauDays);
});

test("Previews come from the preview attachment; the dek falls back to the Reference's own metadata", () => {
  const attachments = [
    { id: "s", referenceId: "x-v1", referenceLineageId: "x", role: "source", sortKey: "001-source", sourceUri: "https://x.example.org/a" },
    { id: "p", referenceId: "x-v1", referenceLineageId: "x", role: "preview", sortKey: "002-preview", sourceUri: "https://cdn.example.org/x.jpg", metadata: JSON.stringify({ description: "A dek.", siteName: "X News" }) },
    { id: "q", referenceId: "y-v1", referenceLineageId: "y", role: "preview", sortKey: "002-preview", sourceUri: "data:image/png;base64,AAAA", metadata: "{}" },
  ] as ReferenceAttachmentRecord[];
  const previews = referencePreviewsByLineage(attachments);
  assert.equal(previews.get("x")!.imageUrl, "https://cdn.example.org/x.jpg");
  assert.equal(previews.get("x")!.siteName, "X News");
  assert.equal(previews.get("y")!.imageUrl, null, "only http(s) images are used: anything else falls back to the tile");
  assert.equal(previews.has("nothing"), false);
  assert.equal(referenceDek(reference("x"), previews.get("x")), "A dek.");
  assert.equal(referenceDek({ ...reference("z"), metadata: { summary: "From metadata." } }, undefined), "From metadata.");
  assert.equal(referenceSourceHost(reference("www", { sourceUri: "https://www.example.org/a" })), "example.org");
  assert.equal(referenceSourceHost(reference("none", { sourceUri: "s3://bucket/file" })), null);
  assert.equal(formatFeedAge(NOW - 3 * 3_600_000, NOW), "3h");
  assert.equal(formatFeedAge(NOW - 2 * DAY, NOW), "2d");
});

class FakeStorage {
  private values = new Map<string, string>();
  limit = Infinity;
  getItem(key: string) { return this.values.get(key) ?? null; }
  setItem(key: string, value: string) { if (value.length > this.limit) throw new Error("QuotaExceededError"); this.values.set(key, value); }
  removeItem(key: string) { this.values.delete(key); }
}

test("The saved copy and the session display survive a return visit, expire, and are wiped on sign-out", () => {
  const local = new FakeStorage();
  const session = new FakeStorage();
  (globalThis as unknown as { window: unknown }).window = { localStorage: local, sessionStorage: session };
  try {
    const references = Array.from({ length: 8 }, (_, index) => reference(`r${index}`, { curationStatusReason: "private note" }));
    assert.equal(saveFeedSnapshot("site", { references, previews: new Map(), decisions: new Map([["r0", { ...decision("include", 0.9), provenance: { labelSet: [], doctrineFingerprint: "x", teachingFingerprint: null, teachingLabels: null, primingExamples: null } }]]) }, 1000), true);
    const snapshot = loadFeedSnapshot("site")!;
    assert.equal(snapshot.references.length, 8);
    assert.equal(snapshot.decisions[0][1].provenance, null, "provenance is not kept");
    saveSessionDisplay("site", { label: "Editor", isAdmin: false }, 1000);
    assert.equal(loadSessionDisplay("site", 1000 + SESSION_DISPLAY_TTL_MS)?.label, "Editor");
    assert.equal(loadSessionDisplay("site", 1001 + SESSION_DISPLAY_TTL_MS), null, "a stale session summary is not shown");
    clearSavedNewsroomDisplay("site");
    assert.equal(loadFeedSnapshot("site"), null);
    assert.equal(loadSessionDisplay("site", 1000), null);
    // A full store keeps what fits; a blocked store simply caches nothing.
    local.limit = 3000;
    assert.equal(saveFeedSnapshot("site", { references: Array.from({ length: 60 }, (_, index) => reference(`q${index}`)), previews: new Map(), decisions: new Map() }), true);
    assert.ok(loadFeedSnapshot("site")!.references.length < 60);
    local.limit = 10;
    assert.equal(saveFeedSnapshot("site", { references, previews: new Map(), decisions: new Map() }), false);
    (globalThis as unknown as { window: unknown }).window = { get localStorage(): never { throw new Error("blocked"); }, get sessionStorage(): never { throw new Error("blocked"); } };
    assert.equal(loadFeedSnapshot("site"), null);
    assert.doesNotThrow(() => saveSessionDisplay("site", { label: "Editor", isAdmin: false }));
  } finally {
    delete (globalThis as unknown as { window?: unknown }).window;
  }
});

test("Sections: Top predictions are the Accepts at least half as strong as the best, Least likely the predicted Rejects", () => {
  const ids3 = ["a", "b", "c", "d", "e", "f"];
  const decisions = new Map<string, RelevanceDecisionView>([
    ["a", decision("include", 0.95)], ["b", decision("include", 0.8)], ["c", decision("include", 0.65)], ["e", decision("exclude", 0.6)], ["f", decision("exclude", 0.9)],
  ]);
  const groups = groupFeedItems(partitionReferenceFeed(ids3.map((id) => reference(id)), decisions, { now: NOW }).feed);
  assert.deepEqual(groups.map((group) => [group.key, ids(group.items)]), [["top", ["a", "b"]], ["more", ["c", "d"]], ["least", ["e", "f"]]]);
  assert.deepEqual(groupFeedItems(partitionReferenceFeed([reference("x")], undefined, { now: NOW }).feed).map((group) => group.key), ["more"], "no prediction at all is one plain section");
  assert.deepEqual(groupFeedItems([]), []);
});

test("A dek is dropped when it adds nothing to the headline or the picture", () => {
  assert.equal(dekAddsInformation("Jukebox-OS: time-travel replay for AI agents", "Jukebox-OS: time-travel replay for AI agents - owner/jukebox-os", null), false, "repeats the headline");
  assert.equal(dekAddsInformation("Jukebox-OS", "A deterministic flight recorder for multi-agent systems", "https://opengraph.githubassets.com/abc/owner/repo"), false, "a GitHub social card already prints it");
  assert.equal(dekAddsInformation("Formal verification gets feasible", "Claude proved security properties in the compiled code of 123 open-source libraries.", "https://cdn.example.org/x.jpg"), true);
  assert.equal(dekAddsInformation("Anything", null, null), false);
});
