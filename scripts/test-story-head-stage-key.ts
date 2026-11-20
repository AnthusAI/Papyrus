import assert from "node:assert/strict";
import test from "node:test";
import { contentItemHeadStageKey } from "../lib/content-item-lifecycle";
import { createLocalPreviewContentItemVersions } from "../lib/local-preview-seed";

// The same rule as head_stage_key in src/papyrus_content/content_item_lifecycle.py (features_backend/story-head-stage-index.feature).
test("the head row of a lineage carries its stage; a superseded row and a row with no stage carry nothing", () => {
  assert.equal(contentItemHeadStageKey({ stage: "copywriting", versionState: "current" }), "copywriting");
  assert.equal(contentItemHeadStageKey({ stage: "reporting", versionState: "draft" }), "reporting", "a story whose only row is a draft is still on the board");
  assert.equal(contentItemHeadStageKey({ stage: "idea" }), "idea", "a row with no version state is the head");
  assert.equal(contentItemHeadStageKey({ stage: "published", versionState: "superseded" }), null, "a superseded version is in no head stage index");
  assert.equal(contentItemHeadStageKey({ stage: null, versionState: "current" }), null, "a sub-task or a doctrine page has no stage");
});

test("every local preview story is the head of its one-row lineage, in its own stage", () => {
  const rows = createLocalPreviewContentItemVersions();
  assert.ok(rows.length > 0);
  for (const row of rows) assert.equal(row.headStageKey, row.stage, `${row.id} carries its stage as its head stage key`);
  assert.equal(new Set(rows.map(row => row.lineageId)).size, rows.length, "one head per lineage");
});
