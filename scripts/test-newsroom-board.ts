import assert from "node:assert/strict";
import { canReadNewsroomBoard, contentItemBoardType, contentItemColumnOrder, newsroomBoardConfig, projectNewsroomBoard } from "../lib/newsroom-board";
import { CONTENT_ITEM_STAGES } from "../lib/content-item-lifecycle";
import { getContentItemName } from "../lib/site-brand";

const contentItemType = contentItemBoardType();
assert.equal(contentItemType, getContentItemName().singular.toLowerCase(), "content item cards use the publication's name");

const issues = projectNewsroomBoard({
  contentItemVersions: [
    { id: "story-1-v1", lineageId: "story-1", versionNumber: 1, stage: "report", type: "article", status: "draft", title: "Candidate", slug: "draft-1", updatedAt: "2026-10-15" },
    { id: "story-1-v2", lineageId: "story-1", versionNumber: 2, stage: "copywriting", type: "article", status: "draft", headline: "Hospitals are paying", slug: "draft-2", updatedAt: "2026-10-16" },
    { id: "same", lineageId: "same", versionNumber: 1, stage: "published", type: "article", status: "published", title: "Out", slug: "out", updatedAt: "2026-10-14" },
  ],
  references: [
    { id: "same", lineageId: "source/lineage", corpusId: "corpus", externalItemId: "source", versionState: "current", curationStatus: "accepted" },
    { id: "old", corpusId: "corpus", externalItemId: "source", versionState: "superseded", curationStatus: "pending" },
  ],
  assignments: [
    { id: "same", title: "Custom work", assignmentTypeKey: "custom", queueKey: "desk", queueStatusKey: "desk/waiting-for-review", status: "waiting-for-review", createdAt: "2026-10-14", updatedAt: "2026-10-15" },
    { id: "copywriting-1", title: "Write it", assignmentTypeKey: "copywriting.article-draft", queueKey: "copy", queueStatusKey: "copy#open", status: "open", createdAt: "2026-10-15", updatedAt: "2026-10-15", itemLineageId: "story-1" },
  ],
});

const contentItemCards = issues.filter(issue => issue.kind === "contentItem");
assert.equal(contentItemCards.length, 2, "one card per content item, not one per version");
const story = contentItemCards.find(issue => issue.nativeId === "story-1");
assert.equal(story?.status, `${contentItemType}/copywriting`, "the card sits in the latest version's stage");
assert.equal(story?.title, "Hospitals are paying");
assert.match(story?.description ?? "", /1 assignment on this/, "work on a content item is counted on its card");
assert(!issues.some(issue => issue.nativeId === "copywriting-1"), "work on a content item is not a separate card");
assert.equal(issues.length, 4, "superseded source revisions must not appear as current work");
assert.equal(new Set(issues.map(issue => issue.id)).size, 4, "IDs from separate native models must not collide");
assert(issues.every(issue => !issue.parent), "no parent/child content hierarchy");
assert.equal(issues.find(issue => issue.kind === "reference")?.href, "/newsroom/references/source%2Flineage", "curator selection uses canonical lineage");
assert.equal(issues.find(issue => issue.kind === "assignment")?.nativeStatus, "waiting-for-review");

const config = newsroomBoardConfig(issues);
assert.deepEqual(
  config.statuses.filter(status => status.key.startsWith(`${contentItemType}/`)).map(status => status.key),
  CONTENT_ITEM_STAGES.map(stage => `${contentItemType}/${stage}`),
  "every lifecycle stage is a column, in order",
);
assert(config.statuses.some(status => status.key === "assignment/waiting-for-review"), "unknown native stages stay visible");
const lastContentItemColumnIndex = config.statuses.map(status => status.key).lastIndexOf(`${contentItemType}/published`);
assert(config.statuses.slice(0, lastContentItemColumnIndex + 1).every(status => status.key.startsWith(`${contentItemType}/`)), "other record kinds come after the story columns");
assert.deepEqual(contentItemColumnOrder(["draft", "published", "copywriting", "draft"]), ["idea", "assignment", "research", "report", "editor_select", "copywriting", "draft", "published"], "an unrecognized stage never lands to the right of the final stage");
assert.deepEqual(config.hierarchy, []);
assert.equal(canReadNewsroomBoard("ready"), true);
for (const phase of [undefined, "signedOut", "forbidden", "error", "checkingAccess", "loadingDesk", "refreshing"]) assert.equal(canReadNewsroomBoard(phase), false);
console.log("PASS one card per content item by stage, native record identity, canonical source links and board access gate");
