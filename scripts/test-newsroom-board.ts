import assert from "node:assert/strict";
import type { AssignmentRecord } from "../lib/category-repository";
import {
  deskBoardConfig,
  deskContainsAssignment,
  deskContainsContentItem,
  contentItemBoardPathSegment, assignmentBoardConfig, canReadNewsroomBoard, contentItemBoardConfig, contentItemBoardType, contentItemColumnOrder, projectAssignmentBoard, projectContentItemBoard } from "../lib/newsroom-board";
import { DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS, contentItemStageKeys } from "../lib/content-item-lifecycle";
import { getContentItemName } from "../lib/site-brand";
import { isEditorialWorkAssignment } from "../lib/newsroom-assignments";

const contentItemType = contentItemBoardType();
assert.equal(contentItemType, getContentItemName().singular.toLowerCase(), "content item cards use the publication's name");

const contentItemVersions = [
  { id: "story-1-v1", lineageId: "story-1", versionNumber: 1, stage: "report", type: "article", status: "draft", title: "Candidate", slug: "draft-1", updatedAt: "2026-10-15" },
  { id: "story-1-v2", lineageId: "story-1", versionNumber: 2, stage: "copywriting", type: "article", status: "draft", headline: "Hospitals are paying", slug: "draft-2", updatedAt: "2026-10-16" },
  { id: "same", lineageId: "same", versionNumber: 1, stage: "published", type: "article", status: "published", title: "Out", slug: "out", updatedAt: "2026-10-14" },
];
const assignments = [
  { id: "same", title: "Custom work", assignmentTypeKey: "custom", queueKey: "desk", queueStatusKey: "desk/waiting-for-review", status: "waiting-for-review", createdAt: "2026-10-14", updatedAt: "2026-10-15" },
  { id: "copywriting-1", title: "Write it", assignmentTypeKey: "copywriting.article-draft", queueKey: "copy", queueStatusKey: "copy#open", status: "open", createdAt: "2026-10-15", updatedAt: "2026-10-15", itemLineageId: "story-1" },
];

const storyIssues = projectContentItemBoard({ contentItemVersions, assignments });
assert.equal(storyIssues.length, 2, "one card per content item, not one per version");
assert(storyIssues.every(issue => issue.kind === "contentItem"), "the story board shows only stories");
const story = storyIssues.find(issue => issue.nativeId === "story-1");
assert.equal(story?.status, `${contentItemType}/copywriting`, "the card sits in the latest version's stage");
assert.equal(story?.title, "Hospitals are paying");
assert.match(story?.description ?? "", /1 assignment on this/, "work on a content item is counted on its card");
assert(storyIssues.every(issue => !issue.parent), "no parent/child content hierarchy");

const assignmentIssues = projectAssignmentBoard(assignments);
assert.equal(assignmentIssues.length, 2, "every assignment is a card, including work on a content item");
assert(assignmentIssues.every(issue => issue.kind === "assignment"), "the assignment board shows only assignments");
assert.equal(assignmentIssues.find(issue => issue.nativeId === "same")?.nativeStatus, "waiting-for-review");
assert.equal(new Set([...storyIssues, ...assignmentIssues].map(issue => issue.id)).size, 4, "IDs from separate native models must not collide");

const storyConfig = contentItemBoardConfig(storyIssues);
assert.deepEqual(
  storyConfig.statuses.map(status => status.key),
  contentItemStageKeys(DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS).map(stage => `${contentItemType}/${stage}`),
  "every lifecycle stage is a column, in order",
);
assert.deepEqual(storyConfig.types, [contentItemType]);
const assignmentConfig = assignmentBoardConfig(assignmentIssues);
assert.deepEqual(
  assignmentConfig.statuses.map(status => status.key),
  ["assignment/open", "assignment/claimed", "assignment/waiting-for-review", "assignment/completed", "assignment/canceled"],
  "assignment statuses read left to right with unknown statuses between claimed and completed",
);
assert.deepEqual(assignmentConfig.types, ["assignment"]);
assert.deepEqual(contentItemColumnOrder(["draft", "published", "copywriting", "draft"]), ["reporting", "copywriting", "illustration", "typesetting", "draft", "published", "held", "spiked"], "an unrecognized stage lands just before the published column");
assert.deepEqual(contentItemColumnOrder(["draft", "done"], ["pitch", "write", "done"]), ["pitch", "write", "draft", "done"], "a publication can define its own stages and the last one stays rightmost");
assert.deepEqual(storyConfig.hierarchy, []);
assert.equal(canReadNewsroomBoard("ready"), true);
for (const phase of [undefined, "signedOut", "forbidden", "error", "checkingAccess", "loadingDesk", "refreshing"]) assert.equal(canReadNewsroomBoard(phase), false);
assert.equal(contentItemBoardPathSegment(), getContentItemName().plural.toLowerCase(), "the board path follows the configured content item name");
const legacyAndAssignmentPhaseVersions = [
  { id: "legacy-v1", lineageId: "legacy", versionNumber: 1, stage: "editor_select", type: "article", status: "draft", title: "Legacy", slug: "legacy", updatedAt: "2026-10-14" },
  { id: "idea-v1", lineageId: "idea", versionNumber: 1, stage: "idea", type: "article", status: "draft", title: "Idea", slug: "idea", updatedAt: "2026-10-14" },
  { id: "placeholder-v1", lineageId: "placeholder", versionNumber: 1, stage: "assignment", type: "article", status: "draft", title: "Placeholder", slug: "placeholder", updatedAt: "2026-10-14" },
];
const legacyBoard = projectContentItemBoard({ contentItemVersions: legacyAndAssignmentPhaseVersions });
assert.deepEqual(legacyBoard.map(issue => issue.status), [`${contentItemType}/reporting`], "a legacy stage reads as reporting and assignment-phase items stay off the stories board");
const spikedStatus = contentItemBoardConfig([]).statuses.find(status => status.key === `${contentItemType}/spiked`);
assert.equal(spikedStatus?.collapsed, true, "the spiked column starts collapsed");
assert.equal(contentItemBoardConfig([]).statuses.filter(status => status.collapsed).length, 1, "only spiked starts collapsed");
const newsDeskStory = { id: "desk-story-v1", lineageId: "desk-story", versionNumber: 1, stage: "copywriting", type: "article", status: "draft", title: "News story", slug: "news-story", section: "news", updatedAt: "2026-10-14" };
assert.equal(deskContainsContentItem(newsDeskStory, "news"), true);
assert.equal(deskContainsContentItem(newsDeskStory, "News"), true, "desk matching ignores case");
assert.equal(deskContainsContentItem(newsDeskStory, "features"), false);
const newsDeskAssignment = { id: "desk-assignment", sectionKey: "news", status: "open", title: "News assignment" } as AssignmentRecord;
assert.equal(deskContainsAssignment(newsDeskAssignment, "news"), true);
assert.equal(deskContainsAssignment({ ...newsDeskAssignment, sectionKey: "features" }, "news"), false);
const deskIssues = [...projectContentItemBoard({ contentItemVersions: [newsDeskStory] }), ...projectAssignmentBoard([newsDeskAssignment])];
const deskConfig = deskBoardConfig(deskIssues);
assert.deepEqual(deskConfig.types, [contentItemType, "assignment"], "a desk board offers both record types to filter by");
assert.deepEqual(Object.keys(deskConfig.workflows ?? {}), [contentItemType, "assignment"]);
assert.ok(Object.keys(deskConfig.workflows?.assignment ?? {}).every(key => key.startsWith("assignment/")), "assignment columns stay separate from story columns");
assert.ok(Object.keys(deskConfig.workflows?.[contentItemType] ?? {}).every(key => key.startsWith(`${contentItemType}/`)));
console.log("PASS separate story and assignment boards, one card per record by stage or status, and board access gate");

for (const bookkeepingTypeKey of ["curation.reference-intake", "reference.corpus-accession", "reference.identifier-backfill", "reference.text-extraction", "analysis.reindex"]) {
  assert.equal(isEditorialWorkAssignment({ assignmentTypeKey: bookkeepingTypeKey }), false, `${bookkeepingTypeKey} stays off the assignments board`);
}
for (const workTypeKey of ["copywriting.article-draft", "research.edition-candidate", "reporting.edition-candidate", "custom", undefined]) {
  assert.equal(isEditorialWorkAssignment({ assignmentTypeKey: workTypeKey }), true, `${workTypeKey} is real work`);
}
