import assert from "node:assert/strict";
import { contentItemStageKeys } from "../lib/content-item-lifecycle";
import { isLocalPreviewEnabled } from "../lib/local-preview";
import {
  createLocalPreviewAssignments,
  createLocalPreviewContentItemVersions,
} from "../lib/local-preview-seed";
import { projectAssignmentBoard, projectContentItemBoard } from "../lib/newsroom-board";
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

const assignments = createLocalPreviewAssignments();
const storyBoardIssues = projectContentItemBoard({ contentItemVersions, assignments });
assert.equal(storyBoardIssues.length, contentItemVersions.length, "story board projects every seeded item");
assert.equal(projectAssignmentBoard(assignments).length, assignments.length, "assignment board projects every seeded assignment");

console.log("local preview seed ok");
