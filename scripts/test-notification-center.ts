import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { FIXTURE_DRAFTS, FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
import { draftView } from "../lib/review-drafts";
import { buildNotificationItems, draftPicture, filterCount, previewsBySourceAddress, recentDecisions, requestCaption, waitingText } from "../lib/notification-feed";
import {
  answerUpdate, cyclotronAutoDecided, cyclotronHeldForReview, isDue, nextText, normalizeReviewRow, sectionReviews,
  steeringText, subjectHref, subjectLabel, summarize, summaryText, timeoutUpdate, type ReviewRequest,
} from "../lib/review-requests";

function text(html: string): string {
  return html.replace(/<[^>]+>/g, " ").replace(/&amp;/g, "&").replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/\s+/g, " ");
}

const NOW = new Date("2026-10-23T12:00:00Z");
const reference = (id: string, status = "pending"): ReferenceRecord => ({ id, lineageId: id, title: `Source ${id}`, externalItemId: id, curationStatus: status } as unknown as ReferenceRecord);
const decision = (label: string, confidence: number, reviewRecommended: boolean, decidedAt: string): RelevanceDecisionView => ({
  decisionRelationId: `rel-${label}`, decisionId: "d", label, confidence, version: 1, reviewRecommended, reviewReason: reviewRecommended ? "program" : null,
  reviewDetail: reviewRecommended ? "Confidence is below the review threshold" : null, classes: ["relevant", "not_relevant"], positiveLabel: "relevant",
  question: null, reviewControl: "thumbs", cyclotronId: "c", decidedAt, provenance: null,
});

async function main() {
  (globalThis as { React?: typeof React }).React = React;
  const { NotificationCenterView } = await import("../components/notification-center");

  // Sections: hard gates, then soft reviews by deadline, then flags; answered and timed out are kept apart.
  const sections = sectionReviews(FIXTURE_REVIEW_REQUESTS);
  assert.deepEqual(sections.hardGates.map((r) => r.id), ["rr-hard-1"]);
  assert.deepEqual(sections.draftBatches.map((r) => r.id), ["rr-soft-1", "rr-soft-2"], "AI draft reviews, soonest deadline first");
  assert.deepEqual(sections.softReviews.map((r) => r.id), ["rr-soft-3"], "other soft reviews apart from the drafts");
  assert.deepEqual(sections.flags.map((r) => r.id), ["rr-flag-1"]);
  assert.deepEqual(sections.decided.map((r) => r.id), ["rr-done-2", "rr-done-1", "rr-late-1"]);

  // A soft review with no deadline stays open until handled: listed after the ones with deadlines, never due, and its text says so.
  const openEnded = { ...FIXTURE_REVIEW_REQUESTS[7], id: "rr-soft-open", deadline: null, raisedAt: "2026-10-01T00:00:00Z" };
  assert.deepEqual(sectionReviews([...FIXTURE_REVIEW_REQUESTS, openEnded]).softReviews.map((r) => r.id), ["rr-soft-3", "rr-soft-open"]);
  assert.equal(isDue(openEnded, new Date("2036-01-01T00:00:00Z")), false);
  assert.equal(nextText(openEnded), "No deadline. Stays open until someone answers it.");
  const openEndedDrafts = { ...FIXTURE_REVIEW_REQUESTS[1], deadline: null };
  assert.equal(nextText(openEndedDrafts), "No deadline. The drafts stay in Proposals until an editor decides them.");

  // Cyclotron: low-confidence pending items are held (least confident first); confident ones are the read-only stream.
  const references = [reference("a"), reference("b"), reference("c"), reference("d", "accepted"), reference("e")];
  const decisions = new Map<string, RelevanceDecisionView>([
    ["a", decision("relevant", 0.55, true, "2026-10-23T09:00:00Z")], ["b", decision("relevant", 0.41, true, "2026-10-23T08:00:00Z")],
    ["c", decision("not_relevant", 0.97, false, "2026-10-23T10:00:00Z")], ["d", decision("relevant", 0.52, true, "2026-10-22T10:00:00Z")],
    ["e", decision("relevant", 0.99, false, "2026-10-23T11:00:00Z")],
  ]);
  const held = cyclotronHeldForReview(references, decisions);
  assert.deepEqual(held.map((entry) => entry.lineageId), ["b", "a"], "pending only, least confident first");
  const auto = cyclotronAutoDecided(references, decisions, new Set(["c"]));
  assert.deepEqual(auto.map((entry) => entry.lineageId), ["e", "c"], "newest first");
  assert.equal(auto[1].reviewedByPerson, true);

  // The summary says it in plain counts: what waits, how many AI drafts, the other reviews, what the system decided.
  const summary = summarize(sections, held, auto, 3);
  assert.equal(summaryText(summary), "3 waiting for you · 4 AI drafts to review · 1 other review open · 2 recently decided by the system");

  // Only a hard gate says "Waiting for you"; a soft review says in plain words what its deadline does; a flag waits for nothing.
  assert.match(nextText(FIXTURE_REVIEW_REQUESTS[0]), /^Waiting for you/);
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[1]), "Closes on 2026-10-30 07:00 UTC if nobody answers. The drafts stay in Proposals.");
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[7]), "If nobody answers by 2026-10-31 07:00 UTC, this closes and copy-editor carries on without a review.");
  for (const request of FIXTURE_REVIEW_REQUESTS) assert.ok(!/Proceeds automatically|unless you steer/.test(nextText(request)), request.id);
  assert.match(nextText(FIXTURE_REVIEW_REQUESTS[3]), /^Nothing is waiting on this/);
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[4]), "Proceeded without review on 2026-10-17 07:00 UTC.");
  assert.equal(nextText({ ...FIXTURE_REVIEW_REQUESTS[1], state: "timed_out", updatedAt: "2026-10-30T07:00:00Z" }), "Closed with no answer on 2026-10-30 07:00 UTC. The drafts stay in Proposals.");
  for (const request of FIXTURE_REVIEW_REQUESTS.filter((r) => r.mode !== "hard_gate")) assert.ok(!/Waiting for you/.test(nextText(request)), request.id);

  // What became of steering: applied in a run, or not yet used.
  assert.equal(steeringText(FIXTURE_REVIEW_REQUESTS[5]), 'You steered "Fewer listicles". Applied in run run-w43 on 2026-10-20 07:00 UTC.');
  assert.match(steeringText(FIXTURE_REVIEW_REQUESTS[6]) ?? "", /Keep the old name for sports". concept-bot has not used it yet/);
  assert.equal(steeringText(FIXTURE_REVIEW_REQUESTS[0]), null);

  // The deadline, checked on read: a due soft review times out, a hard gate and a flag never do.
  const due = FIXTURE_REVIEW_REQUESTS[2];
  assert.ok(!isDue(due, new Date("2026-10-24T00:00:00Z")) && isDue(due, new Date("2026-10-25T07:00:00Z")));
  assert.ok(!isDue(FIXTURE_REVIEW_REQUESTS[0], new Date("2036-01-01T00:00:00Z")), "a hard gate never times out");
  assert.ok(!isDue(FIXTURE_REVIEW_REQUESTS[3], new Date("2036-01-01T00:00:00Z")), "a flag never times out");
  const timeout = timeoutUpdate(due, new Date("2026-10-25T08:00:00Z"));
  assert.equal(timeout.state, "timed_out");
  assert.match(String(timeout.history), /proceeded without review/);

  // Answers: approve, reject, feedback; a note or a steer is required for feedback; a closed request refuses.
  const approve = answerUpdate(FIXTURE_REVIEW_REQUESTS[0], { decision: "approve" }, "Ed Itor", NOW);
  assert.equal(approve.state, "answered");
  assert.equal(JSON.parse(String(approve.answer)).by, "Ed Itor");
  assert.throws(() => answerUpdate(FIXTURE_REVIEW_REQUESTS[0], { decision: "feedback" }, "x", NOW), /Write a note/);
  assert.equal(JSON.parse(String(answerUpdate(FIXTURE_REVIEW_REQUESTS[0], { decision: "feedback", steer: "not_this_kind" }, "x", NOW).answer)).steer, "not_this_kind");
  assert.throws(() => answerUpdate(FIXTURE_REVIEW_REQUESTS[4], { decision: "approve" }, "x", NOW), /proceeded without review/);

  // Rows from the API carry JSON as strings.
  const row = normalizeReviewRow({ id: "r", subject: '{"type":"story","id":"s"}', mode: "flag", reason: "x", raisedBy: "p", raisedAt: "t", state: "open", links: "[]", history: "[]", answer: null, updatedAt: "t" });
  assert.deepEqual(row.subject, { type: "story", id: "s" });

  // Links to the item.
  assert.equal(subjectHref({ type: "story", id: "s 1" }), "/newsroom/articles/s%201");
  assert.equal(subjectHref({ type: "batch", id: "x" }), null);
  assert.equal(subjectHref({ type: "proposal", id: "p 1" }), "/newsroom/administration/proposals?proposal=p%201", "a proposal opens in the Proposals panel");


  // A story request shows the story's title, linked, with the id as the fallback.
  assert.equal(subjectLabel({ type: "story", id: "s1" }, { s1: "Title" }), "Title");
  assert.equal(subjectLabel({ type: "proposal", id: "p1" }), "proposal p1");

  // A flag is acknowledged, not approved: new answers store "acknowledge"; an old stored "approve" on a flag still reads as Acknowledged.
  const flag = FIXTURE_REVIEW_REQUESTS[3];
  assert.equal(flag.mode, "flag");
  const acknowledged = answerUpdate(flag, { decision: "acknowledge" }, "Ed Itor", NOW);
  assert.equal(JSON.parse(String(acknowledged.answer)).decision, "acknowledge");
  assert.throws(() => answerUpdate(FIXTURE_REVIEW_REQUESTS[0], { decision: "acknowledge" }, "x", NOW), /Only a flag is acknowledged/);
  const answeredFlag = (decision: "acknowledge" | "approve") => ({ ...flag, state: "answered" as const, answer: { decision, feedback: null, steer: null, by: "Ed Itor", at: "2026-10-22T11:00:00Z" } });
  assert.equal(nextText(answeredFlag("acknowledge")), "Acknowledged by Ed Itor on 2026-10-22 11:00 UTC.");
  assert.equal(nextText(answeredFlag("approve")), "Acknowledged by Ed Itor on 2026-10-22 11:00 UTC.");
  assert.equal(nextText({ ...answeredFlag("approve"), mode: "hard_gate" }), "Accepted by Ed Itor on 2026-10-22 11:00 UTC.");

  // The feed (What needs me?): one card per draft, never per batch.
  const drafts = Object.fromEntries(FIXTURE_DRAFTS.map((row) => [row.id, draftView(row)]));
  const items = buildNotificationItems({ requests: FIXTURE_REVIEW_REQUESTS, drafts, missingDrafts: new Set(["proposal-9"]), draftsState: "ready", stay: new Set(), referenceCount: 12 });
  assert.deepEqual(items.drafts.map((item) => item.key), ["rr-soft-2#proposal-1", "rr-soft-2#proposal-2", "rr-soft-2#proposal-3"], "a request covering 3 drafts is 3 draft cards");
  assert.deepEqual(items.reviews.map((item) => item.key), ["rr-hard-1", "rr-soft-3", "rr-soft-1"], "hard gates first; a request whose draft is not a Proposal here takes the answer itself");
  assert.deepEqual(items.flags.map((item) => item.key), ["rr-flag-1"]);
  assert.deepEqual(items.counts, { drafts: 3, references: 12, other: 4 });
  assert.equal(waitingText({ drafts: 3, references: 12, other: 0 }), "3 drafts and 12 references waiting for you");
  assert.equal(waitingText({ drafts: 1, references: 0, other: 0 }), "1 draft waiting for you");
  assert.equal(waitingText({ drafts: 3, references: 12, other: 2 }), "3 drafts, 12 references and 2 other items waiting for you");
  assert.equal(waitingText({ drafts: 0, references: 0, other: 0 }), "All caught up");
  assert.equal(filterCount("all", items.counts), 19);
  assert.equal(requestCaption(FIXTURE_REVIEW_REQUESTS[1]), "from Idea pipeline · Oct 23", "a batch id with no words falls back to the step that raised it");
  assert.equal(requestCaption({ subject: { type: "batch", id: "monitor-stories-run-20261027T163255Z-a0a2e4" }, raisedBy: "idea-pipeline", raisedAt: "2026-10-27T16:33:54Z" }), "from Monitor stories run · Oct 27");
  // A draft decided in this visit stays in place; one decided before does not come back.
  const decided = FIXTURE_REVIEW_REQUESTS[1].links.map((link) => (link.id === "proposal-1" ? { ...link, decision: { choice: "accept" as const, by: "Ed", at: "2026-10-24T09:00:00Z" } } : link));
  const partial = [{ ...FIXTURE_REVIEW_REQUESTS[1], links: decided }];
  const base = { requests: partial, drafts, missingDrafts: new Set<string>(), draftsState: "ready" as const, referenceCount: 0 };
  assert.deepEqual(buildNotificationItems({ ...base, stay: new Set() }).drafts.map((item) => item.draftId), ["proposal-2", "proposal-3"]);
  const kept = buildNotificationItems({ ...base, stay: new Set(["rr-soft-2#proposal-1"]) });
  assert.deepEqual(kept.drafts.map((item) => item.draftId), ["proposal-1", "proposal-2", "proposal-3"]);
  assert.equal(kept.counts.drafts, 2, "a decided draft no longer counts as waiting");
  // Pictures: a draft's cited source finds the preview of the Reference it points to.
  const cited = { ...draftView({ ...FIXTURE_DRAFTS[0], body: "x\n\n## Sources\n\n1. A page (2026-10-20) https://www.example.org/a/\n" }) };
  const pictures = previewsBySourceAddress([{ id: "r", lineageId: "r", sourceUri: "https://example.org/a" } as unknown as ReferenceRecord], new Map([["r", { imageUrl: "https://img.example/x.jpg", description: null, siteName: "Example", title: null }]]));
  assert.equal(draftPicture(cited, pictures).imageUrl, "https://img.example/x.jpg");
  assert.equal(draftPicture(draftView(FIXTURE_DRAFTS[1]), pictures).imageUrl, null, "no picture is invented");
  // Real Proposals carry JSON encoded twice and a relevance sentence.
  const real = draftView({ ...FIXTURE_DRAFTS[1], evidence: JSON.stringify(JSON.stringify({ signals: 1, source: "hn monitor: https://example.org/q" })), body: "Dek. [1]\n\n## Source\n\n1. T (2026-10-22) https://example.org/q\n\nSection: articles. Drafted by AI from an item the hn monitor found. The relevance check labelled it include with a score of 0.96. An editor approves the copy before anything is published.\n" });
  assert.deepEqual(real.evidence, ["Found by the hn monitor.", "Relevance check: include, score 0.96."]);
  assert.equal(real.section, "articles");
  // What you decided: drafts, references, newest first, a few.
  const answered = { ...FIXTURE_REVIEW_REQUESTS[5], answer: { ...FIXTURE_REVIEW_REQUESTS[5].answer!, drafts: [{ id: "proposal-1", choice: "reject" as const, title: "Sparse attention goes open", by: "Ed", at: "2026-10-26T09:00:00Z" }] } };
  const rated = { id: "ref-a", lineageId: "ref-a", title: "A source", curationStatus: "accepted", curationStatusUpdatedAt: "2026-10-27T09:00:00Z" } as unknown as ReferenceRecord;
  const recent = recentDecisions([answered], [rated], false, 5);
  assert.deepEqual(recent.map((entry) => [entry.kind, entry.word, entry.title]), [["reference", "Accepted", "A source"], ["draft", "Rejected", "Sparse attention goes open"]]);

  // The page, rendered: header, filters, cards, no retired wording, no inline colour.
  const render = (overrides: Partial<Parameters<typeof NotificationCenterView>[0]> = {}) =>
    renderToStaticMarkup(createElement(NotificationCenterView, { loadState: "ready", requests: FIXTURE_REVIEW_REQUESTS, drafts, missingDrafts: new Set(["proposal-9"]), ...overrides }));
  const html = render();
  const page = text(html);
  assert.ok(page.includes("What needs me?") && page.includes("3 drafts and 4 other items waiting for you"));
  for (const expected of ["All", "Drafts", "References", "Other", "Sparse attention goes open", "from Idea pipeline · Oct 23", "Open full draft", "Accept", "Reject", "Acknowledge", "Hard gate", "Waiting for you. Nothing continues"]) assert.ok(page.includes(expected), `page shows: ${expected}`);
  assert.ok(html.includes('aria-label="Why? (optional)"'), "every decidable card has the optional Why box");
  assert.equal((html.match(/data-review-draft="proposal-/g) ?? []).length, 3, "three draft cards");
  assert.ok(!html.includes("data-review-drafts"), "no batch container");
  for (const retired of ["Approve", "Steer with this note", "Steering note", "Agree", "Overrule", "Proceeds automatically", "unless you steer", "draft batches", "Mark all read", "Needs attention"]) assert.ok(!page.includes(retired), `the retired wording is gone: ${retired}`);
  assert.ok(!/\bdesk\b/i.test(page), "no avoided vocabulary");
  assert.match(html, /aria-pressed="true"[^>]*data-notification-filter="all"|data-notification-filter="all"/, "the active filter is marked");
  assert.ok(text(render({ requests: [], drafts: {} })).includes("All caught up"), "empty state");
  const autoCards = [{ lineageId: "x", title: "A confident call", label: "include", confidence: 0.97, decidedAt: null, reviewDetail: null, reviewedByPerson: false, href: "/newsroom/references/x" }];
  assert.ok(text(render({ autoDecided: autoCards })).includes("Decided automatically (1)"), "the system's decisions are a collapsed footer");
  assert.match(render({ autoDecided: autoCards }), /<details[^>]*data-notification-section="auto-decided"/);
  assert.ok(!text(render()).includes("Decided automatically"), "no footer when there are none");
  assert.ok(text(render({ loadState: "forbidden" })).includes("for editors and admins"));
  assert.ok(text(render({ loadState: "unavailable" })).includes("could not be read right now"));
  assert.match(render({ loadState: "loading" }), /data-notification-skeleton/);
  assert.match(text(render({ draftsState: "failed" })), /The drafts could not be loaded right now\./);
  assert.ok(text(render({ deletedStories: new Set(["story-ruling-1"]) })).includes("About: story story-ruling-1 (story deleted)"), "the card marks the deleted story");
  assert.ok(text(render({ storyTitles: { "story-ruling-1": "Board refuses registration" } })).includes("About: Board refuses registration"));
  assert.match(html, /href="\/newsroom\/administration\/proposals\?proposal=proposal-1"/, "a draft opens in Proposals");
  assert.ok(!/<svg(?![^>]*lucide)/.test(html), "Lucide icons only");
  assert.ok(!/<select/.test(html), "no dropdowns");

  // No borders, no lines: the new components never use a border or divider utility.
  for (const file of ["../components/notification-cards.tsx", "../components/notification-center.tsx"]) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.ok(!/["' `]border(-[a-z0-9\[\]#/-]+)?["' `]|divide-|<hr|outline-(?!none)/.test(source.replace(/focus-visible:ring[^"' ]*/g, "")), `${file} draws no borders, dividers or outlines`);
  }
  const overview = readFileSync(new URL("../components/newsroom-ops-overview.tsx", import.meta.url), "utf8");
  assert.ok(!overview.includes("newsroom-overview-feed-frame") && !/Needs attention/.test(overview), "the framed, scrolling feed and the duplicate Needs attention list are gone");
  assert.ok(!/\b(Core |Rotating )?Desks\b|\b(Core|Rotating) desks\b/.test(overview), "the home has no desk heading");

  console.log("notification center: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
