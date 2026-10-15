import assert from "node:assert/strict";
import { canReadNewsroomBoard, newsroomBoardConfig, projectNewsroomBoard } from "../lib/newsroom-board";

const issues = projectNewsroomBoard({
  articles: [{ id: "same", type: "article", slug: "draft", title: "Draft", status: "draft", pending: false, updatedAt: "2026-10-15", section: null }],
  references: [
    { id: "same", lineageId: "source/lineage", corpusId: "corpus", externalItemId: "source", versionState: "current", curationStatus: "accepted" },
    { id: "old", corpusId: "corpus", externalItemId: "source", versionState: "superseded", curationStatus: "pending" },
  ],
  assignments: [{ id: "same", title: "Custom work", assignmentTypeKey: "custom", queueKey: "desk", queueStatusKey: "desk/waiting-for-review", status: "waiting-for-review", createdAt: "2026-10-14", updatedAt: "2026-10-15" }],
});
assert.equal(issues.length, 3, "superseded source revisions must not appear as current work");
assert.equal(new Set(issues.map(issue => issue.id)).size, 3, "IDs from separate native models must not collide");
assert(issues.every(issue => issue.nativeId === "same" && !issue.parent), "no invented Story identity or parentage");
assert.equal(issues[1].href, "/newsroom/references/source%2Flineage", "curator selection uses canonical lineage");
assert.equal(issues[2].nativeStatus, "waiting-for-review");
const config = newsroomBoardConfig(issues);
assert(config.statuses.some(status => status.key === "assignment/waiting-for-review"), "unknown native stages stay visible");
assert.deepEqual(config.hierarchy, []);
assert.equal(canReadNewsroomBoard("ready"), true);
for (const phase of [undefined, "signedOut", "forbidden", "error", "checkingAccess", "loadingDesk", "refreshing"]) assert.equal(canReadNewsroomBoard(phase), false);
console.log("PASS native record identity, canonical source links, original statuses and board access gate");
