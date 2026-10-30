import assert from "node:assert/strict";
import test from "node:test";
import { EMPTY_STORY_REPORTING_TRAIL, stageMovesOf, storyReportingTrailIsEmpty } from "../lib/story-reporting-trail";

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
