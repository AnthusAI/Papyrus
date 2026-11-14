import assert from "node:assert/strict";
import test from "node:test";
import { EMPTY_STORY_REPORTING_TRAIL, agentNoteOf, stageMovesOf, storyMessageFeed, storyReportingTrailIsEmpty } from "../lib/story-reporting-trail";

test("stage moves are read from the Item version metadata, not from Messages", () => {
  const metadata = JSON.stringify({ stageMoves: [
    { at: "2026-10-29T10:00:00Z", from: "reporting", to: "copywriting", by: "Ada", reason: "draft is ready" },
    { at: "2026-10-29T11:00:00Z", from: "copywriting", to: "typesetting", by: "automation:site.copy", reason: null },
  ] });
  assert.deepEqual(stageMovesOf(metadata).map(move => [move.from, move.to, move.by, move.reason]), [
    ["reporting", "copywriting", "Ada", "draft is ready"],
    ["copywriting", "typesetting", "automation:site.copy", null],
  ]);
});

test("malformed or missing stage moves read as none", () => {
  assert.deepEqual(stageMovesOf(null), []);
  assert.deepEqual(stageMovesOf("not json"), []);
  assert.deepEqual(stageMovesOf({ stageMoves: [{ to: 3 }, null, "x"] }), []);
});

test("a story with only stage moves is not an empty trail", () => {
  const trail = { ...EMPTY_STORY_REPORTING_TRAIL, stageMoves: stageMovesOf({ stageMoves: [{ at: "2026-10-29T10:00:00Z", to: "idea" }] }) };
  assert.equal(storyReportingTrailIsEmpty(trail), false);
  assert.equal(storyReportingTrailIsEmpty(EMPTY_STORY_REPORTING_TRAIL), true);
});

test("an agent note is read from its attachment body and a stray JSON file is not a note", () => {
  const note = agentNoteOf("a1", { kind: "story.agent_note", agent: "ChatGPT", summary: "S", body: "B", createdAt: "2026-11-03T10:00:00Z", versionNumber: 2, referenceLineageId: null });
  assert.deepEqual(note, { id: "a1", agent: "ChatGPT", summary: "S", body: "B", referenceLineageId: null, versionNumber: 2, createdAt: "2026-11-03T10:00:00Z" });
  assert.equal(agentNoteOf("a2", { kind: "something.else" }), null);
  assert.equal(agentNoteOf("a3", null), null);
});

test("agent notes sit in the message feed by time, marked as agent notes, and make the trail non-empty", () => {
  const notes = [
    { id: "n1", agent: "ChatGPT", summary: "early", body: "b", referenceLineageId: null, versionNumber: null, createdAt: "2026-11-03T10:00:00Z" },
    { id: "n2", agent: "Claude", summary: "late", body: "b", referenceLineageId: null, versionNumber: null, createdAt: "2026-11-03T12:00:00Z" },
  ];
  const message = { id: "m1", sequenceNumber: 1, messageKind: "note", authorLabel: "ryan", summary: "mine", content: "x", createdAt: "2026-11-03T11:00:00Z" };
  const trail = { ...EMPTY_STORY_REPORTING_TRAIL, agentNotes: notes, threads: [{ id: "t", title: null, threadKind: "story_reporting", summary: null, messages: [message] }] };
  assert.deepEqual(storyMessageFeed(trail).map(entry => entry.entryKind === "agent_note" ? `AI ${entry.note.agent}` : entry.entryKind), ["AI Claude", "message", "AI ChatGPT"]);
  assert.equal(storyReportingTrailIsEmpty({ ...EMPTY_STORY_REPORTING_TRAIL, agentNotes: notes }), false);
});
