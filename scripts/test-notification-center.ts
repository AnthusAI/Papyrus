import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReferenceRecord } from "../lib/category-repository";
import type { RelevanceDecisionView } from "../lib/relevance-decisions";
import { FIXTURE_REVIEW_REQUESTS } from "../lib/review-fixture";
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
  assert.deepEqual(sections.softReviews.map((r) => r.id), ["rr-soft-1", "rr-soft-2"], "soonest deadline first");
  assert.deepEqual(sections.flags.map((r) => r.id), ["rr-flag-1"]);
  assert.deepEqual(sections.decided.map((r) => r.id), ["rr-done-2", "rr-done-1", "rr-late-1"]);

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

  // The summary says it in the three counts Ryan asked for.
  const summary = summarize(sections, held, auto, 3);
  assert.equal(summaryText(summary), "3 waiting for you · 2 proceeding soon · 2 recently decided by the system");

  // Only a hard gate says "Waiting for you"; a soft review says when it proceeds on its own; a flag waits for nothing.
  assert.match(nextText(FIXTURE_REVIEW_REQUESTS[0]), /^Waiting for you/);
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[1]), "Proceeds automatically on 2026-10-30 07:00 UTC unless you steer it.");
  assert.match(nextText(FIXTURE_REVIEW_REQUESTS[3]), /^Nothing is waiting on this/);
  assert.equal(nextText(FIXTURE_REVIEW_REQUESTS[4]), "Proceeded without review on 2026-10-17 07:00 UTC.");
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

  // The page: summary first, sections in order, controls where relevant, read and unread in words.
  const render = (overrides: Partial<Parameters<typeof NotificationCenterView>[0]> = {}) =>
    renderToStaticMarkup(createElement(NotificationCenterView, {
      loadState: "ready", requests: FIXTURE_REVIEW_REQUESTS, readIds: new Set(["rr-flag-1"]), held, autoDecided: auto, ...overrides,
    }));
  const html = render();
  const loadingHtml = render({ loadState: "loading", requests: [], held: [], autoDecided: [] });
  assert.match(loadingHtml, /data-notification-state="loading"/);
  assert.match(loadingHtml, /aria-label="Loading Notification Center"/);
  assert.doesNotMatch(text(loadingHtml), /No hard gates|Nothing unread|Nothing needs attention/);
  const unavailableHtml = render({ loadState: "unavailable", requests: [], held: [], autoDecided: [] });
  assert.match(unavailableHtml, /role="alert"/);
  assert.match(text(unavailableHtml), /current request state is unknown/);
  const page = text(html);
  assert.ok(page.includes("3 waiting for you · 2 proceeding soon · 2 recently decided by the system"));
  const order = ["Waiting for you: hard gates", "Proceeding soon: soft reviews", "Cyclotron items routed to a person", "Flags: for your information", "Answered, and what became of it", "Recently decided by the system (2)"]
    .map((heading) => page.indexOf(heading));
  assert.ok(order.every((position, index) => position >= 0 && (index === 0 || position > order[index - 1])), `sections in order: ${order}`);
  assert.ok(page.indexOf("Look, or steer.") < page.indexOf("Waiting for you: hard gates"), "the ignore-safe sentence comes before the stream");
  for (const expected of [
    "■ Hard gate", "◐ Soft review", "⚑ Flag", "● New", "Read", "Approve", "Reject", "Steer with this note", "Not this kind of thing", "Acknowledge",
    "Held for review: it stays pending until someone decides", "Open it in References to correct it", "Review it in References",
    "You steered \"Fewer listicles\". Applied in run run-w43", "Proceeded without review on 2026-10-17 07:00 UTC.", "6 unread",
  ]) assert.ok(page.includes(expected), `page shows: ${expected}`);
  assert.equal((page.match(/Waiting for you\. Nothing continues/g) ?? []).length, 1, "one hard gate says Waiting for you");
  assert.match(html, /href="\/newsroom\/articles\/story-ruling-1"/, "the entry links to its item");
  assert.match(html, /href="\/newsroom\/topics\?proposal=proposal-1"/, "batch members link to their proposals");
  assert.match(html, /<details data-notification-section="auto-decided">/, "the stream is collapsible");
  assert.equal((html.match(/data-review-controls/g) ?? []).length, 4, "controls only on open requests");

  // A story request shows the story's title, linked, with the id as the fallback.
  const titled = text(render({ storyTitles: { "story-ruling-1": "Board refuses registration" } }));
  assert.ok(titled.includes("About: Board refuses registration"), "a known story shows its title");
  assert.ok(page.includes("About: story story-ruling-1"), "an unknown story shows its id");
  assert.match(render({ storyTitles: { "story-ruling-1": "Board refuses registration" } }), /href="\/newsroom\/articles\/story-ruling-1"[^>]*>Board refuses registration</);
  assert.equal(subjectLabel({ type: "story", id: "s1" }, { s1: "Title" }), "Title");
  assert.equal(subjectLabel({ type: "proposal", id: "p1" }), "proposal p1");

  // The console home: the Notification Center does not scroll inside the page on a phone, and the section headings avoid the avoided word.
  const css = readFileSync(new URL("../components/newsroom-organizer.css", import.meta.url), "utf8");
  const frame = css.split("\n").filter((line) => line.includes(".newsroom-overview-feed-frame"));
  assert.ok(frame.length === 2 && !frame[0].includes("height:3") && !frame[0].includes("overflow"), "no fixed height or overflow below 640px");
  assert.ok(frame[1].includes("@media(min-width:640px)"), "a fixed scrolling frame only from 640px");
  const overview = readFileSync(new URL("../components/newsroom-ops-overview.tsx", import.meta.url), "utf8");
  assert.ok(!/frame[^"]*overflow-y-auto/.test(overview.match(/className="newsroom-overview-feed-frame[^"]*"/)?.[0] ?? ""), "no inline scroll class on the feed");
  assert.ok(!/\b(Core |Rotating )?Desks\b|\b(Core|Rotating) desks\b/.test(overview), "the home has no desk heading");

  // Words and marks, no colour encoding, and not the avoided word.
  assert.ok(!/ style=/.test(html), "no inline style");
  assert.ok(!/\bdesk\b/i.test(page), "no avoided vocabulary");

  // Each state says so plainly.
  assert.ok(text(render({ loadState: "forbidden" })).includes("for editors and admins"));
  assert.ok(text(render({ loadState: "unavailable" })).includes("could not be read right now"));
  assert.match(render({ loadState: "loading" }), /aria-label="Loading Notification Center"/);
  const empty = text(render({ requests: [], held: [], autoDecided: [] }));
  assert.ok(empty.includes("0 waiting for you · 0 proceeding soon · 0 recently decided by the system"));
  assert.ok(empty.includes("No hard gates. Nothing is blocked on you.") && empty.includes("Nothing unread"));

  console.log("notification center: ok");
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
