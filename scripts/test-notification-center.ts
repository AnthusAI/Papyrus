import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { FIXTURE_IDEAS, FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
import { batchHasIdeasWaiting, buildNotificationItems, recentDecisions, requestCaption } from "../lib/notification-feed";
import {
  answerReasonUpdate, answerUpdate, applyReviewUpdate, cyclotronAutoDecided, cyclotronHeldForReview, ideaIdsOf, ideasBoardHref, isDue, isIdeaBatch, nextText, normalizeReviewRow,
  sectionReviews, steeringText, subjectHref, subjectLabel, summarize, summaryText, timeoutUpdate,
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
  const { NeedsMeView } = await import("../components/needs-me-feed");

  // Sections: hard gates, then soft reviews by deadline, then flags; answered and timed out are kept apart.
  const sections = sectionReviews(FIXTURE_REVIEW_REQUESTS);
  assert.deepEqual(sections.hardGates.map((r) => r.id), ["rr-hard-1"]);
  assert.deepEqual(sections.ideaBatches.map((r) => r.id), ["rr-soft-2"], "batches of generated story ideas");
  assert.deepEqual(sections.softReviews.map((r) => r.id), ["rr-soft-1", "rr-soft-3"], "other soft reviews apart from the idea batches, soonest deadline first");
  assert.deepEqual(sections.flags.map((r) => r.id), ["rr-flag-1"]);
  assert.deepEqual(sections.decided.map((r) => r.id), ["rr-done-2", "rr-done-1", "rr-late-1"]);

  // A soft review with no deadline stays open until handled: listed after the ones with deadlines, never due, and its text says so.
  const openEnded = { ...FIXTURE_REVIEW_REQUESTS[7], id: "rr-soft-open", deadline: null, raisedAt: "2026-10-01T00:00:00Z" };
  assert.deepEqual(sectionReviews([...FIXTURE_REVIEW_REQUESTS, openEnded]).softReviews.map((r) => r.id), ["rr-soft-1", "rr-soft-3", "rr-soft-open"]);
  assert.equal(isDue(openEnded, new Date("2036-01-01T00:00:00Z")), false);
  assert.equal(nextText(openEnded), "No deadline. Stays open until someone answers it.");
  const ideaBatch = FIXTURE_REVIEW_REQUESTS[1];
  assert.ok(isIdeaBatch(ideaBatch) && !isIdeaBatch(FIXTURE_REVIEW_REQUESTS[7]), "only the idea pipeline's batch reviews are idea batches");
  assert.deepEqual(ideaIdsOf(ideaBatch), ["idea-1", "idea-2", "idea-3"], "an idea batch names the ideas filed in the run");
  assert.equal(nextText(ideaBatch), "Move an idea forward to accept it, or move it to Spiked with a reason to decline it. The ideas stay in the Idea column until someone moves them. Nothing is published.");
  assert.equal(ideasBoardHref(), "/newsroom/work", "the batch links to the Stories board");

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

  // The summary says it in plain counts: what waits, how many ideas, the other reviews, what the system decided.
  const summary = summarize(sections, held, auto, 3);
  assert.equal(summaryText(summary), "3 waiting for you · 3 ideas to review · 2 other reviews open · 2 recently decided by the system");

  // Only a hard gate says "Waiting for you"; a soft review says in plain words what its deadline does; a flag waits for nothing.
  assert.match(nextText(FIXTURE_REVIEW_REQUESTS[0]), /^Waiting for you/);
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[2]), "If nobody answers by 2026-10-25 07:00 UTC, this closes and trend-pipeline carries on without a review.");
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[7]), "If nobody answers by 2026-10-31 07:00 UTC, this closes and copy-editor carries on without a review.");
  for (const request of FIXTURE_REVIEW_REQUESTS) assert.ok(!/Proceeds automatically|unless you steer/.test(nextText(request)), request.id);
  assert.match(nextText(FIXTURE_REVIEW_REQUESTS[3]), /^Nothing is waiting on this/);
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[4]), "Proceeded without review on 2026-10-17 07:00 UTC.");
  assert.equal(nextText({ ...FIXTURE_REVIEW_REQUESTS[1], state: "timed_out", updatedAt: "2026-10-30T07:00:00Z" }), "Closed with no answer on 2026-10-30 07:00 UTC. The ideas stay in the Idea column.");
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
  assert.equal(subjectHref({ type: "proposal", id: "p 1" }), null, "ideas are stories now, so nothing links to a story draft Proposal");


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

  // The feed (What needs me?): one card per batch of ideas, never one per idea, and none for a batch with no idea left in the Idea column.
  const stages = Object.fromEntries(FIXTURE_IDEAS.map((idea) => [idea.id, idea.stage]));
  const items = buildNotificationItems({ requests: FIXTURE_REVIEW_REQUESTS, ideaStages: stages, stay: new Set() });
  assert.deepEqual(items.ideas.map((item) => item.key), ["rr-soft-2"], "a request covering 3 ideas is ONE card");
  assert.deepEqual(items.reviews.map((item) => item.key), ["rr-hard-1", "rr-soft-1", "rr-soft-3"], "hard gates first, then the other soft reviews by deadline");
  assert.deepEqual(items.flags.map((item) => item.key), ["rr-flag-1"]);
  assert.equal(requestCaption(FIXTURE_REVIEW_REQUESTS[1]), "from Idea pipeline · Oct 23", "a batch id with no words falls back to the step that raised it");
  assert.equal(requestCaption({ subject: { type: "batch", id: "monitor-stories-run-20261027T163255Z-a0a2e4" }, raisedBy: "idea-pipeline", raisedAt: "2026-10-27T16:33:54Z" }), "from Monitor stories run · Oct 27");
  // Accepting = moving forward, declining = spiked: once every idea has left the Idea column the batch is done and its card goes.
  assert.ok(batchHasIdeasWaiting(ideaBatch, stages), "two of the three still wait");
  const allMoved = { "idea-1": "writing", "idea-2": "spiked", "idea-3": "spiked" };
  assert.ok(!batchHasIdeasWaiting(ideaBatch, allMoved), "all three left the Idea column");
  assert.deepEqual(buildNotificationItems({ requests: [ideaBatch], ideaStages: allMoved, stay: new Set() }).ideas, [], "no card for a batch that is decided on the board");
  assert.deepEqual(buildNotificationItems({ requests: [ideaBatch], ideaStages: allMoved, stay: new Set(["rr-soft-2"]) }).ideas.map((item) => item.key), ["rr-soft-2"], "a card on screen stays for the visit");
  assert.ok(batchHasIdeasWaiting(ideaBatch, {}), "ideas whose stage is not read yet count as waiting");
  const legacyBatch = { ...ideaBatch, id: "rr-legacy", links: [{ type: "proposal", id: "proposal-1" }] };
  assert.deepEqual(buildNotificationItems({ requests: [legacyBatch], stay: new Set() }).ideas, [], "a batch raised when ideas were Proposals names no story, so it has no card");
  // What you decided: ideas decided in a batch before the board, references, newest first, a few.
  const answered = { ...FIXTURE_REVIEW_REQUESTS[5], answer: { ...FIXTURE_REVIEW_REQUESTS[5].answer!, drafts: [{ id: "proposal-1", choice: "reject" as const, title: "Sparse attention goes open", by: "Ed", at: "2026-10-26T09:00:00Z" }] } };
  const rated = { id: "ref-a", lineageId: "ref-a", title: "A source", curationStatus: "accepted", curationStatusUpdatedAt: "2026-10-27T09:00:00Z" } as unknown as ReferenceRecord;
  const recent = recentDecisions([answered], [rated], false, 5);
  assert.deepEqual(recent.map((entry) => [entry.kind, entry.word, entry.title]), [["reference", "Accepted", "A source"], ["idea", "Rejected", "Sparse attention goes open"]]);

  // The page, rendered: header, filters, cards, no retired wording, no inline colour.
  const { buildNeedsMeItems } = await import("../lib/needs-me-items");
  const { learnConfidenceThreshold } = await import("../lib/needs-me-ranking");
  const sources = (overrides: Partial<Parameters<typeof buildNeedsMeItems>[0]> = {}): Parameters<typeof buildNeedsMeItems>[0] => ({
    references: [], decisions: undefined, previews: new Map(), captures: undefined, visitRated: new Set(), requests: FIXTURE_REVIEW_REQUESTS, stay: new Set(), ideaStages: stages,
    storyTitles: Object.fromEntries(FIXTURE_IDEAS.map((idea) => [idea.id, idea.title])), storyExcerpts: {}, deletedStories: new Set(), emails: [], emailsDecided: new Map(), ...overrides,
  });
  const render = (overrides: Partial<Parameters<typeof NeedsMeView>[0]> = {}, from: Partial<Parameters<typeof buildNeedsMeItems>[0]> = {}) =>
    renderToStaticMarkup(createElement(NeedsMeView, {
      loadState: "ready", entries: buildNeedsMeItems(sources(from)), threshold: learnConfidenceThreshold([], undefined),
      now: NOW.getTime(), shaping: { decisions: 0, agreed: 0, overruled: 0 }, recent: [], settled: true, onDecide: async () => undefined, ...overrides,
    }));
  const html = render();
  const page = text(html);
  assert.match(page, /What needs me\? 1 idea batch(, [\w ]+)* waiting for you/, "the header counts what waits");
  for (const expected of ["All", "References", "Ideas", "Stories", "Email", "Captures", "Other", "3 new story ideas to review", "Open the Idea column", "2 of 3 still in the Idea column", "Hard gate", "You\u2019re shaping this", "Accept", "Reject", "Acknowledge"]) assert.ok(page.includes(expected), `page shows: ${expected}`);
  assert.equal((html.match(/data-idea-batch-footer/g) ?? []).length, 1, "one card for the batch of three ideas");
  assert.match(html, /data-idea-batch-open="true" href="\/newsroom\/work"/, "the batch links to the Stories board");
  assert.ok(!/data-review-draft=/.test(html), "no per-draft cards");
  for (const retired of ["Approve", "Steer with this note", "Steering note", "Agree", "Proceeds automatically", "unless you steer", "draft batches", "Proposed Stor", "Mark all read", "Needs attention"]) assert.ok(!page.includes(retired), `the retired wording is gone: ${retired}`);
  assert.ok(!/\bdesk\b/i.test(page), "no avoided vocabulary");
  assert.match(html, /aria-pressed="true"[^>]*data-notification-filter="all"|data-notification-filter="all"/, "the active filter is marked");
  assert.ok(text(render({}, { requests: [] })).includes("All caught up"), "empty state");
  assert.ok(text(render({ loadState: "forbidden" })).includes("for editors and admins"));
  assert.ok(text(render({ loadState: "unavailable" })).includes("could not be read right now"));
  assert.match(render({ loadState: "loading" }), /data-notification-skeleton/);
  const autoCards = [{ lineageId: "x", title: "A confident call", label: "include", confidence: 0.97, decidedAt: null, reviewDetail: null, reviewedByPerson: false, href: "/newsroom/references/x" }];
  assert.ok(text(render({ legacyAuto: autoCards })).includes("Decided automatically (1)"), "the system's decisions are a collapsed footer");
  assert.match(render({ legacyAuto: autoCards }), /<details[^>]*data-notification-section="auto-decided"/);
  assert.ok(!text(render()).includes("Decided automatically"), "no footer when there are none");
  assert.ok(!/<svg(?![^>]*lucide)/.test(html), "Lucide icons only");
  assert.ok(!/<select/.test(html), "no dropdowns");

  // No borders, no lines: the new components never use a border or divider utility.
  for (const file of ["../components/notification-cards.tsx", "../components/notification-center.tsx", "../components/needs-me-feed.tsx", "../components/needs-me-detail.tsx", "../components/needs-me-shared.tsx"]) {
    const source = readFileSync(new URL(file, import.meta.url), "utf8");
    assert.ok(!/["' `]border(-[a-z0-9\[\]#/-]+)?["' `]|divide-|<hr|outline-(?!none)/.test(source.replace(/focus-visible:ring[^"' ]*/g, "")), `${file} draws no borders, dividers or outlines`);
  }
  const overview = readFileSync(new URL("../components/newsroom-ops-overview.tsx", import.meta.url), "utf8");
  assert.ok(!overview.includes("newsroom-overview-feed-frame") && !/Needs attention/.test(overview), "the framed, scrolling feed and the duplicate Needs attention list are gone");
  assert.ok(!/\b(Core |Rotating )?Desks\b|\b(Core|Rotating) desks\b/.test(overview), "the home has no desk heading");

  // A request's own note: needs an answer, changes only the feedback.
  {
    const gate = FIXTURE_REVIEW_REQUESTS.find((entry) => entry.id === "rr-hard-1")!;
    assert.throws(() => answerReasonUpdate(gate, "x", "Ed Itor", NOW), /no answer yet/, "an unanswered request has nothing to add a note to");
    const answered = applyReviewUpdate(gate, answerUpdate(gate, { decision: "approve" }, "Ed Itor", NOW));
    const noted = applyReviewUpdate(answered, answerReasonUpdate(answered, " Safe to proceed. ", "Ed Itor", NOW));
    assert.deepEqual([noted.answer!.decision, noted.answer!.feedback, noted.answer!.by, noted.state], ["approve", "Safe to proceed.", "Ed Itor", "answered"]);
  }

  console.log("notification center: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
