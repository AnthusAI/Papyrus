import assert from "node:assert/strict";
import test from "node:test";
import type { ReferenceAttachmentRecord, ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import {
  acceptProbability,
  applyFeedOrderSnapshot,
  buildFeedItems,
  feedLeadId,
  orderFeedItems,
  takeFeedOrderSnapshot,
  visibleFeedItems,
} from "../lib/reference-feed-ranking";
import { withoutSiteName } from "../lib/newsroom-references";
import { dekAddsInformation, formatFeedAge, referenceDek, referencePreviewsByLineage, referenceSourceHost } from "../lib/reference-preview";
import { captureLine, captureStatus, curationCardOf, completenessFlags, captureStatusesByLineage, countWords, structuredRows, teaserWords, DEFAULT_TEASER_WORDS } from "../lib/reference-capture";
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

const items = (references: ReferenceRecord[], decisions?: Map<string, RelevanceDecisionView>) => buildFeedItems(references, decisions);

test("Best bets: strongest Accepts first, no prediction in the middle, strongest Rejects last", () => {
  const references = ["weak-accept", "none", "strong-reject", "strong-accept", "weak-reject"].map((id) => reference(id));
  const decisions = new Map<string, RelevanceDecisionView>([
    ["weak-accept", decision("include", 0.6)], ["strong-accept", decision("include", 0.95)],
    ["weak-reject", decision("exclude", 0.6)], ["strong-reject", decision("exclude", 0.95)],
  ]);
  assert.deepEqual(ids(orderFeedItems(items(references, decisions), "best")), ["strong-accept", "weak-accept", "none", "weak-reject", "strong-reject"]);
});

test("Best bets is the Cyclotron's own confidence: age never changes it", () => {
  const references = [reference("old-strong", { createdAt: ago(400) }), reference("new-weak", { createdAt: ago(0.1) }), reference("new-reject", { createdAt: ago(0.1) }), reference("old-reject", { createdAt: ago(400) })];
  const decisions = new Map<string, RelevanceDecisionView>([
    ["old-strong", decision("include", 0.9)], ["new-weak", decision("include", 0.6)], ["new-reject", decision("exclude", 0.9)], ["old-reject", decision("exclude", 0.7)],
  ]);
  const ordered = orderFeedItems(items(references, decisions), "best");
  assert.deepEqual(ids(ordered), ["old-strong", "new-weak", "old-reject", "new-reject"], "a year-old 90% Accept still outranks a fresh 60% one");
  assert.equal(ordered[0].probability, 0.9, "no fading");
});

test("Ties in Best bets go to the newest item, then to a stable id order", () => {
  const references = [reference("b", { createdAt: ago(2) }), reference("a", { createdAt: ago(2) }), reference("c", { createdAt: ago(1) })];
  assert.deepEqual(ids(orderFeedItems(items(references), "best")), ["c", "a", "b"]);
});

test("Newest is reverse chronological by arrival, whatever the predictions say", () => {
  const references = [reference("older", { createdAt: ago(3) }), reference("newest", { createdAt: ago(0.1) }), reference("middle", { createdAt: ago(1) })];
  const decisions = new Map<string, RelevanceDecisionView>([["older", decision("include", 0.99)], ["newest", decision("exclude", 0.99)]]);
  assert.deepEqual(ids(orderFeedItems(items(references, decisions), "newest")), ["newest", "middle", "older"]);
  const tied = [reference("y", { createdAt: ago(1) }), reference("x", { createdAt: ago(1) })];
  assert.deepEqual(ids(orderFeedItems(items(tied), "newest")), ["x", "y"], "ties are deterministic");
});

test("Unrated only hides answered items except those answered this visit; Include rated adds them in the active sort", () => {
  const references = [
    reference("open", { createdAt: ago(1) }),
    reference("yes", { createdAt: ago(2), curationStatus: "accepted" }),
    reference("no", { createdAt: ago(0.5), curationStatus: "rejected" }),
    reference("gone", { curationStatus: "archived" }),
  ];
  const all = items(references);
  assert.ok(!ids(all).includes("gone"), "archived items are never listed");
  assert.deepEqual(ids(visibleFeedItems(all, "newest", "unrated")), ["open"]);
  assert.deepEqual(ids(visibleFeedItems(all, "newest", "all")), ["no", "open", "yes"]);
  assert.deepEqual(ids(visibleFeedItems(all, "newest", "unrated", new Set(["yes"]))), ["open", "yes"], "answered this visit: stays");
  assert.ok(visibleFeedItems(all, "best", "all").find((item) => item.lineageId === "yes")!.rated);
});

test("An old unrated item stays in the one list, placed by its original confidence, never dropped, and its rating works", () => {
  const aged = reference("aged", { createdAt: ago(900) });
  const young = reference("young", { createdAt: ago(0.1) });
  const none = reference("none", { createdAt: ago(0.1) });
  const reject = reference("reject", { createdAt: ago(0.1) });
  const decisions = new Map<string, RelevanceDecisionView>([["young", decision("include", 0.8)], ["aged", decision("include", 0.9)], ["reject", decision("exclude", 0.7)]]);
  assert.deepEqual(ids(visibleFeedItems(items([young, aged, none, reject], decisions), "best", "unrated")), ["aged", "young", "none", "reject"]);
  assert.deepEqual(ids(visibleFeedItems(items([young, aged, none, reject], decisions), "newest", "unrated")).at(-1), "aged", "and last by date");
  const rated = [young, { ...aged, curationStatus: "accepted", curationStatusUpdatedAt: ago(0) }, none, reject];
  assert.deepEqual(ids(visibleFeedItems(items(rated, decisions), "best", "unrated", new Set(["aged"]))), ["aged", "young", "none", "reject"], "rated in place");
});

test("The lead card is the first card unless it is a predicted Reject", () => {
  const decisions = new Map<string, RelevanceDecisionView>([["r", decision("exclude", 0.9)]]);
  assert.equal(feedLeadId(orderFeedItems(items([reference("r")], decisions), "best")), undefined);
  assert.equal(feedLeadId(orderFeedItems(items([reference("n")]), "best")), "n");
  assert.equal(feedLeadId([]), undefined);
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

test("A title drops the site name tacked on its end, and only that", () => {
  assert.equal(withoutSiteName("Auditing employment algorithms for discrimination | Brookings", "www.brookings.edu"), "Auditing employment algorithms for discrimination");
  assert.equal(withoutSiteName("How an algorithm denied food to the poor | Poverty and Development | Al Jazeera", "www.aljazeera.com"), "How an algorithm denied food to the poor", "with a pipe the section name goes too");
  assert.equal(withoutSiteName("Welfare system fuels mass surveillance – report - Amnesty International", "www.amnesty.org"), "Welfare system fuels mass surveillance – report", "only the shortest segment naming the site");
  assert.equal(withoutSiteName("GitHub - foo/bar: a tool", "github.com"), "GitHub - foo/bar: a tool", "a site name at the start stays");
  assert.equal(withoutSiteName("Malicious AI Models Undermine Supply-Chain Security", "cacm.acm.org"), "Malicious AI Models Undermine Supply-Chain Security");
  assert.equal(withoutSiteName("Brookings", "brookings.edu"), "Brookings", "never an empty title");
  assert.equal(withoutSiteName("A | B", null), "A | B");
});

test("A dek is dropped when it adds nothing to the headline or the picture", () => {
  assert.equal(dekAddsInformation("Jukebox-OS: time-travel replay for AI agents", "Jukebox-OS: time-travel replay for AI agents - owner/jukebox-os", null), false, "repeats the headline");
  assert.equal(dekAddsInformation("Jukebox-OS", "A deterministic flight recorder for multi-agent systems", "https://opengraph.githubassets.com/abc/owner/repo"), false, "a GitHub social card already prints it");
  assert.equal(dekAddsInformation("Formal verification gets feasible", "Claude proved security properties in the compiled code of 123 open-source libraries.", "https://cdn.example.org/x.jpg"), true);
  assert.equal(dekAddsInformation("Anything", null, null), false);
});

const attach = (lineage: string, role: string, extra: Record<string, unknown> = {}) => ({ id: `${lineage}-${role}`, referenceId: `${lineage}-v1`, referenceLineageId: lineage, referenceVersionKey: `reference#${lineage}-v1`, role, sortKey: role, ...extra }) as ReferenceAttachmentRecord;

test("Capture status: none without extracted text, thin under the teaser line, full above it, with plain words", () => {
  const source = attach("a", "source", { sourceUri: "https://a.example.org" });
  assert.deepEqual({ ...captureStatus([source]) }, { state: "none", words: null, estimated: false, source: "none", curation: null, reason: null, flags: [], assessment: null, summaryStale: false }, "a monitored Reference has only its address");
  const text = (characters: number) => attach("a", "extracted_text", { storagePath: "s3://x", metadata: JSON.stringify({ textLength: characters }) });
  assert.equal(captureStatus([source, text(600)]).state, "thin", "100 words is a teaser");
  assert.equal(captureStatus([source, text(6000)]).state, "full");
  assert.equal(captureStatus([source, text(6000)], DEFAULT_TEASER_WORDS, 40).state, "thin", "the loaded text's own count wins over the estimate");
  assert.equal(captureLine(captureStatus([source])).label, "No text captured");
  assert.equal(captureLine(captureStatus([source, text(6000)])).label, "Full text captured");
  assert.equal(captureLine(captureStatus([source, text(600)], DEFAULT_TEASER_WORDS, 87)).label, "Only 87 words — may be a teaser or paywalled");
  assert.equal(countWords("  one two\nthree "), 3);
});

test("The teaser line is learned from the corpus once there are ten captured texts, never guessed before", () => {
  assert.equal(teaserWords([1000, 2000]), DEFAULT_TEASER_WORDS);
  assert.equal(teaserWords(Array.from({ length: 10 }, () => 2000)), 500, "a quarter of the median");
  const statuses = captureStatusesByLineage(
    [attach("a", "extracted_text", { storagePath: "p", byteSize: 6000 }), attach("b", "source")],
    ["a", "b", "c"],
  );
  assert.equal(statuses.statuses.get("a")!.state, "full");
  assert.equal(statuses.statuses.get("b")!.state, "none");
  assert.equal(statuses.statuses.get("c")!.state, "none", "a Reference with no attachments at all has no capture");
});

test("Structured extraction (GROBID fields) becomes plain label and value rows", () => {
  const rows = structuredRows([attach("a", "extracted_text_raw", { storagePath: "p", metadata: JSON.stringify({ grobid: { title: "A Paper", authors: ["X. One", "Y. Two"], doi: "10.1/abc", citations: [1, 2, 3] } }) })]);
  assert.deepEqual(rows, [{ label: "Title", value: "A Paper" }, { label: "Authors", value: "X. One, Y. Two" }, { label: "DOI", value: "10.1/abc" }, { label: "Citations", value: "3 cited works" }]);
  assert.deepEqual(structuredRows([attach("a", "source")]), []);
});

test("The feed order is taken once and kept, in both sorts: new predictions re-rank nothing, new items are counted, not shuffled in", () => {
  const references = ["a", "b", "c", "d"].map((id, index) => reference(id, { createdAt: ago(0.1 + index * 0.1) }));
  const first = new Map<string, RelevanceDecisionView>([["a", decision("include", 0.95)], ["b", decision("include", 0.8)], ["c", decision("exclude", 0.9)]]);
  const snapshot = takeFeedOrderSnapshot(items(references, first));
  assert.deepEqual(snapshot.best, ["a", "b", "d", "c"]);
  assert.deepEqual(snapshot.newest, ["a", "b", "c", "d"]);
  // The predictions change completely, a card is rated, and a new item arrives.
  const later = new Map<string, RelevanceDecisionView>([["a", decision("exclude", 0.99)], ["b", decision("exclude", 0.9)], ["d", decision("include", 0.99)]]);
  const rated = [...references.map((item) => (item.lineageId === "b" ? { ...item, curationStatus: "accepted", curationStatusUpdatedAt: ago(0) } : item)), reference("e", { createdAt: ago(0) })];
  const live = items(rated, later);
  assert.notDeepEqual(ids(visibleFeedItems(live, "best", "unrated", new Set(["b"]))), snapshot.best, "a live re-rank would have reshuffled the feed");
  const stable = applyFeedOrderSnapshot(snapshot, live, "best", "unrated");
  assert.deepEqual(ids(stable.items), ["a", "b", "d", "c"], "the order is the snapshot's: nothing moved, the rated card stayed");
  assert.equal(stable.leadId, "a");
  assert.equal(stable.newCount, 1, "the new item is counted for the pill");
  assert.ok(!ids(stable.items).includes("e"), "and not shuffled in");
  assert.deepEqual(ids(applyFeedOrderSnapshot(snapshot, live, "newest", "unrated").items), ["a", "b", "c", "d"], "Newest keeps its own snapshot order too");
  const refreshed = applyFeedOrderSnapshot(takeFeedOrderSnapshot(live), live, "newest", "unrated");
  assert.ok(ids(refreshed.items).includes("e") && refreshed.newCount === 0, "showing the new items takes a fresh snapshot");
  assert.equal(ids(refreshed.items)[0], "e");
});

test("Include rated adds answered cards from the snapshot, in the active sort, with no re-rank", () => {
  const references = [reference("open", { createdAt: ago(1) }), reference("done", { createdAt: ago(0.5), curationStatus: "accepted" }), reference("old", { createdAt: ago(5) })];
  const live = items(references, new Map([["old", decision("include", 0.9)]]));
  const snapshot = takeFeedOrderSnapshot(live);
  assert.deepEqual(ids(applyFeedOrderSnapshot(snapshot, live, "newest", "all").items), ["done", "open", "old"]);
  assert.deepEqual(ids(applyFeedOrderSnapshot(snapshot, live, "best", "all").items), ["old", "done", "open"]);
  assert.deepEqual(ids(applyFeedOrderSnapshot(snapshot, live, "newest", "unrated").items), ["open", "old"]);
});

const curation = (body: Record<string, unknown>) => attach("a", "curation", { sortKey: "003-curation", metadata: JSON.stringify({ kind: "reference-curation", ...body }) });

test("The curation card is read first; extracted_text is the fallback; No text only when neither exists", () => {
  const source = attach("a", "source");
  const ready = curation({ status: "ready", capture: { status: "completed", wordCount: 912, textSortKey: "curation-text" }, signals: { wordCount: 912, endingPattern: "sentence_end" } });
  const status = captureStatus([source, ready]);
  assert.deepEqual([status.state, status.words, status.estimated, status.source, status.curation], ["full", 912, false, "curation", "ready"]);
  const failed = curation({ status: "capture_failed", capture: { status: "failed", reason: "blocked" }, signals: {} });
  const none = captureStatus([source, failed]);
  assert.deepEqual([none.state, none.source, none.curation, none.reason], ["none", "none", "capture_failed", "blocked"]);
  assert.match(captureLine(none).detail, /refused our request/);
  const extracted = attach("a", "extracted_text", { storagePath: "p", metadata: JSON.stringify({ textLength: 6000 }) });
  assert.deepEqual([captureStatus([source, failed, extracted]).state, captureStatus([source, failed, extracted]).source], ["full", "extracted"], "a failed card does not hide older extracted text");
  assert.equal(captureStatus([source, curation({ status: "running", capture: { status: "not_run" }, signals: {} })]).state, "running");
  assert.equal(curationCardOf([source]), null);
  assert.equal(curationCardOf([attach("a", "curation", { metadata: JSON.stringify({ status: "nonsense" }) })]), null, "an unknown status is not a card");
});

test("Completeness signals become plain facts, and a paywall phrase in the tail makes a long capture doubtful, but a bare unpunctuated ending does not", () => {
  assert.deepEqual(completenessFlags({ paywallMarkers: [{ id: "subscribe_to_continue", inTail: true }], endingPattern: "ellipsis", bodyNotLongerThanDescription: true }),
    ["The text ends with a subscribe or sign-in phrase.", "The text stops with an ellipsis or a cut-off marker.", "The text is no longer than the page's own description."]);
  assert.deepEqual(completenessFlags({ endingPattern: "sentence_end" }), []);
  const tail = curation({ status: "ready", capture: { status: "completed", wordCount: 800 }, signals: { wordCount: 800, paywallMarkers: [{ id: "x", inTail: true }] } });
  assert.equal(captureStatus([attach("a", "source"), tail]).thinBy, "signals");
  const midSentence = curation({ status: "ready", capture: { status: "completed", wordCount: 5407 }, signals: { wordCount: 5407, endingPattern: "no_terminal_punctuation" } });
  const unpunctuated = captureStatus([attach("a", "source"), midSentence]);
  assert.equal(unpunctuated.state, "full", "a long text that only ends without a full stop is not sent for a capture check");
  assert.deepEqual(unpunctuated.flags, ["The text stops mid-sentence."], "the ending is still listed as a fact");
  const ellipsis = curation({ status: "ready", capture: { status: "completed", wordCount: 5407 }, signals: { wordCount: 5407, endingPattern: "ellipsis" } });
  assert.equal(captureStatus([attach("a", "source"), ellipsis]).thinBy, "signals", "an ellipsis or cut-off marker still is");
  const vouched = curation({ status: "ready", capture: { status: "completed", wordCount: 800 }, signals: { wordCount: 800, paywallMarkers: [{ id: "x", inTail: true }] }, labels: [{ kind: "capture_completeness", assessment: "complete" }] });
  assert.equal(captureStatus([attach("a", "source"), vouched]).state, "full", "an editor's Complete is not second-guessed");
  const edited = curation({ status: "ready", capture: { status: "completed", wordCount: 5 }, signals: { wordCount: 5 }, editedSignals: { wordCount: 1500 }, current: { textSortKey: "curation-edit-0001-text" } });
  assert.equal(captureStatus([attach("a", "source"), edited]).words, 1500, "the edited text's own word count");
});
