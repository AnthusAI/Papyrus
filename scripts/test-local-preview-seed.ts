import assert from "node:assert/strict";
import { contentItemStageKeys } from "../lib/content-item-lifecycle";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import {
  createLocalPreviewAssignments,
  createLocalPreviewContentItemVersions,
} from "../lib/local-preview-seed";
import { projectContentItemBoard } from "../lib/newsroom-board";
import { getContentItemStageDefinitions } from "../lib/site-brand";

assert.equal(isLocalPreviewEnabled(), false, "preview mode is opt-in");

const contentItemVersions = createLocalPreviewContentItemVersions();
const stageKeysWithSeededItems = new Set(contentItemVersions.map((version) => version.stage));
for (const stageKey of contentItemStageKeys(getContentItemStageDefinitions())) {
  assert.ok(stageKeysWithSeededItems.has(stageKey), `seed has an item in stage ${stageKey}`);
}

const lineageIds = new Set(contentItemVersions.map((version) => version.lineageId));
assert.equal(lineageIds.size, contentItemVersions.length, "every seeded item has its own lineage");
for (const assignment of createLocalPreviewAssignments()) {
  if (assignment.itemLineageId) assert.ok(lineageIds.has(assignment.itemLineageId), "assignments point at seeded items");
}

const boardIssues = projectContentItemBoard({
  contentItemVersions,
  assignments: createLocalPreviewAssignments(),
});
assert.ok(boardIssues.length >= contentItemVersions.length, "board projects every seeded item");

console.log("local preview seed ok");
