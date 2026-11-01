import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import {
  countProposals,
  filterProposals,
  kindLabel,
  proposalMoves,
  proposalReceiptMessage,
  proposerLabel,
  sortProposals,
  stateLabel,
  type ProposalRow,
} from "../lib/proposals-admin";
import { ProposalsView } from "../components/proposals-view";

(globalThis as { React?: unknown }).React = React;

const row = (id: string, changes: Partial<ProposalRow> = {}): ProposalRow => ({
  id: `prop-${id.padStart(32, "0")}`, kind: "new_concept", title: `Story ${id}`, summary: "Why it matters.", body: "The draft.", state: "draft", proposer: "ai",
  createdAt: `2026-10-2${id}T10:00:00.000Z`, ...changes,
});

test("proposals are listed newest first and filtered by where they stand", () => {
  const rows = [row("1"), row("2", { state: "in_steering" }), row("3", { state: "editor_review" }), row("4", { state: "approved" }), row("5", { state: "declined" })];
  assert.deepEqual(sortProposals(rows).map((entry) => entry.title), ["Story 5", "Story 4", "Story 3", "Story 2", "Story 1"]);
  assert.deepEqual(countProposals(rows), { open: 3, draft: 1, in_steering: 1, editor_review: 1, decided: 2 });
  assert.deepEqual(filterProposals(rows, "decided").map((entry) => entry.state), ["approved", "declined"]);
});

const labels = (moves: ReturnType<typeof proposalMoves>) => moves.map((move) => move.label);

test("an editor is offered only the moves the function allows, and pin and hold", () => {
  assert.deepEqual(labels(proposalMoves({ state: "draft" })), ["Send to steering", "Decline", "Pin", "Hold"]);
  assert.deepEqual(labels(proposalMoves({ state: "in_steering" })), ["Move to editor review", "Pin", "Hold"]);
  assert.deepEqual(labels(proposalMoves({ state: "editor_review", pinned: true })), ["Approve", "Decline", "Unpin", "Hold"]);
  assert.deepEqual(labels(proposalMoves({ state: "approved" })), ["Pin"], "a decision is final and cannot be held");
  assert.deepEqual(labels(proposalMoves({ state: "draft", held: true })), ["Pin", "Release hold"], "a proposal on hold does not move");
});

test("without reader steering a draft goes straight to editor review and nothing says steering", () => {
  const moves = proposalMoves({ state: "draft" }, false);
  assert.deepEqual(labels(moves), ["Move to editor review", "Decline", "Pin", "Hold"]);
  assert.deepEqual(moves[0].path, ["in_steering", "editor_review"], "two moves, one click");
  assert.equal(stateLabel("in_steering", false), "Waiting for review");
  const html = renderToStaticMarkup(
    createElement(ProposalsView, { rows: [row("1"), row("2", { state: "in_steering" })], readers: false, filter: "open", busy: false, status: "", reason: "", onFilter() {}, onReason() {}, onMove() {}, onRefresh() {} }),
  );
  assert.equal(/steering|vote|reader/i.test(html), false, html);
  assert.match(html, /Waiting for review/);
  assert.match(html, /Pin/);
  assert.match(html, /Hold/);
});

test("labels say AI for AI and never show a reader's id", () => {
  assert.equal(proposerLabel("ai"), "AI");
  assert.equal(proposerLabel("ss1_secretsubject"), "Reader");
  assert.equal(stateLabel("overridden_by_editor"), "Decided by an editor");
  assert.equal(kindLabel("new_concept"), "New concept");
  assert.equal(kindLabel("story_draft"), "story_draft", "a story draft is not a kind the panel knows: generated ideas are stories at the idea stage");
  assert.equal(proposalReceiptMessage({ status: "ok" }), "Done.");
  assert.equal(proposalReceiptMessage({ status: "refused", message: "Someone else changed that proposal first." }), "Someone else changed that proposal first.");
});

test("the panel shows a proposal with its body and the move buttons, and no reader controls", () => {
  const html = renderToStaticMarkup(
    createElement(ProposalsView, { rows: [row("1")], readers: true, filter: "open", busy: false, status: "", reason: "", onFilter() {}, onReason() {}, onMove() {}, onRefresh() {} }),
  );
  assert.match(html, /New concept/);
  assert.doesNotMatch(html, /Proposed Stor/);
  assert.match(html, /Story 1/);
  assert.match(html, /from AI/);
  assert.match(html, /Send to steering/);
  assert.match(html, /Decline/);
  assert.match(html, /The draft\./);
  assert.equal(/vote|reader-steering|moderat/i.test(html), false);
});

test("a story draft filed before ideas became stories is left out of the panel", async () => {
  const { withoutStoryDrafts } = await import("../lib/proposals-admin");
  assert.deepEqual(withoutStoryDrafts([row("1"), row("2", { kind: "story_draft" }), row("3", { kind: "rename" })]).map((entry) => entry.title), ["Story 1", "Story 3"]);
});
