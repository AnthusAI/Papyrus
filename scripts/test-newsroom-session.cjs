#!/usr/bin/env node

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

require("./register-papyrus-aliases.cjs");
registerTypeScriptRequire();

const {
  beginAccessCheck,
  beginDeskLoad,
  createInitialNewsDeskShellState,
  patchDashboard,
  resolveDashboardReady,
  resolveSignedOut,
} = require("../lib/news-desk-session.ts");
const {
  buildCategoryDrilldownContext,
  referencesForCategoryContext,
  semanticNodesForCategoryContext,
  topicHref,
} = require("../lib/newsroom-category-drilldown.ts");
const {
  createSemanticGraphSnapshot,
} = require("../lib/semantic-graph.ts");

const initial = createInitialNewsDeskShellState();
assert.equal(initial.phase, "checkingAccess");
assert.equal(initial.dashboard, null);

const signedOut = resolveSignedOut(initial, { status: "signedOut", label: "Signed out" });
assert.equal(signedOut.phase, "signedOut");
assert.equal(signedOut.dashboard, null);

const readyAuth = { status: "signedIn", label: "editor@example.com" };
const loadingDesk = beginDeskLoad(initial, readyAuth);
assert.equal(loadingDesk.phase, "loadingDesk");
assert.equal(loadingDesk.auth.label, "editor@example.com");

const dashboard = createDashboard();
const ready = resolveDashboardReady(loadingDesk, dashboard, readyAuth, "2026-05-17T21:00:00.000Z");
assert.equal(ready.phase, "ready");
assert.equal(ready.dashboard?.references.length, 1);
assert.equal(ready.lastRefreshedAt, "2026-05-17T21:00:00.000Z");

const refreshing = beginAccessCheck(ready);
assert.equal(refreshing.phase, "refreshing");
assert.equal(refreshing.dashboard?.references[0].id, "reference-1");

const patched = patchDashboard(
  ready,
  (current) => ({
    ...current,
    assignments: [{ ...current.assignments[0], status: "claimed" }],
  }),
  "2026-05-17T21:05:00.000Z",
);
assert.equal(patched.phase, "ready");
assert.equal(patched.dashboard?.assignments[0].status, "claimed");
assert.equal(patched.dashboard?.references[0].id, "reference-1");
assert.equal(patched.lastRefreshedAt, "2026-05-17T21:05:00.000Z");

const invalidated = resolveSignedOut(ready, { status: "signedOut", label: "Signed out" });
assert.equal(invalidated.phase, "signedOut");
assert.equal(invalidated.dashboard, null);

const drilldownCategories = [
  { id: "flat-root", lineageId: "flat-root-lineage", categoryKey: "topic.root", displayName: "Root", categorySetId: "set", corpusId: "corpus", status: "accepted", parentCategoryKey: null },
  { id: "tree-root", lineageId: "tree-root-lineage", categoryKey: "topic.root", displayName: "Root", categorySetId: "set", corpusId: "corpus", status: "accepted", parentCategoryKey: null },
  { id: "tree-child", lineageId: "tree-child-lineage", categoryKey: "topic.child", displayName: "Child", categorySetId: "set", corpusId: "corpus", status: "accepted", parentCategoryKey: "topic.root" },
];
const rootReference = { kind: "reference", id: "reference-root", lineageId: "reference-root", label: "Root Reference", href: "/newsroom/references?reference=reference-root" };
const childReference = { kind: "reference", id: "reference-child", lineageId: "reference-child", label: "Child Reference", href: "/newsroom/references?reference=reference-child" };
const rootConcept = { kind: "semanticNode", id: "concept-root", lineageId: "concept-root", label: "Root Concept", href: "/newsroom/concepts?node=concept-root" };
const childConcept = { kind: "semanticNode", id: "concept-child", lineageId: "concept-child", label: "Child Concept", href: "/newsroom/concepts?node=concept-child" };
const drilldownGraph = {
  referencesForCategory(lineageId) {
    if (lineageId === "flat-root-lineage") return [rootReference];
    if (lineageId === "tree-root-lineage") return [rootReference];
    if (lineageId === "tree-child-lineage") return [childReference];
    return [];
  },
  neighbors(kind, lineageId) {
    assert.equal(kind, "category");
    if (lineageId === "flat-root-lineage") return [{ predicate: "mentions", label: "mentioned by", direction: "incoming", relations: [{ id: "relation-root" }], objects: [rootConcept] }];
    if (lineageId === "tree-child-lineage") return [{ predicate: "mentions", label: "mentioned by", direction: "incoming", relations: [{ id: "relation-child" }], objects: [childConcept] }];
    return [];
  },
};

const rootDrilldown = buildCategoryDrilldownContext(drilldownCategories, "topic.root");
assert.equal(rootDrilldown.includeDescendants, true);
assert.deepEqual(referencesForCategoryContext(drilldownGraph, rootDrilldown).map((reference) => reference.lineageId).sort(), ["reference-child", "reference-root"]);
assert.deepEqual(semanticNodesForCategoryContext(drilldownGraph, rootDrilldown).map((node) => node.lineageId).sort(), ["concept-child", "concept-root"]);

const childDrilldown = buildCategoryDrilldownContext(drilldownCategories, "topic.child");
assert.equal(childDrilldown.includeDescendants, false);
assert.deepEqual(referencesForCategoryContext(drilldownGraph, childDrilldown).map((reference) => reference.lineageId), ["reference-child"]);
assert.deepEqual(semanticNodesForCategoryContext(drilldownGraph, childDrilldown).map((node) => node.lineageId), ["concept-child"]);
assert.equal(topicHref("topic.root"), "/newsroom/topics/topic.root");
assert.equal(topicHref("topic.root", "topic.child"), "/newsroom/topics/topic.root/topic.child");

const mixedReferenceGraph = createSemanticGraphSnapshot({
  references: [
    { id: "accepted-ref-v1", lineageId: "accepted-ref", versionState: "current", versionNumber: 1, corpusId: "corpus", externalItemId: "accepted", title: "Accepted", curationStatus: "accepted" },
    { id: "pending-ref-v1", lineageId: "pending-ref", versionState: "current", versionNumber: 1, corpusId: "corpus", externalItemId: "pending", title: "Pending", curationStatus: "pending" },
    { id: "rejected-ref-v1", lineageId: "rejected-ref", versionState: "current", versionNumber: 1, corpusId: "corpus", externalItemId: "rejected", title: "Rejected", curationStatus: "rejected" },
  ],
  categories: [{ id: "category-v1", lineageId: "category", versionState: "current", versionNumber: 1, categoryKey: "topic.root", displayName: "Root", categorySetId: "set", corpusId: "corpus", status: "accepted" }],
  semanticNodes: [],
  messages: [],
  semanticRelations: ["accepted-ref", "pending-ref", "rejected-ref"].map((lineageId) => ({
    id: `relation-${lineageId}`,
    relationState: "current",
    predicate: "classified_as",
    relationTypeKey: "classified_as",
    subjectKind: "reference",
    subjectId: `${lineageId}-v1`,
    subjectLineageId: lineageId,
    objectKind: "category",
    objectId: "category-v1",
    objectLineageId: "category",
    subjectStateKey: `reference#${lineageId}#current`,
    objectStateKey: "category#category#current",
  })),
});
assert.deepEqual(mixedReferenceGraph.referencesForCategory("category").map((reference) => reference.lineageId), ["accepted-ref"]);

console.log("newsroom session tests passed");

function createDashboard() {
  return {
    canonicalCorpusId: "corpus-1",
    canonicalCategorySetId: "category-set-1",
    canManageUsers: true,
    userDirectory: [{ userSub: "user-1", email: "editor@example.com", activeRoles: ["admin"] }],
    corpora: [{ id: "corpus-1", name: "Canonical Demo Corpus" }],
    importRuns: [{ id: "import-1", corpusId: "corpus-1", importedAt: "2026-05-17T20:59:00.000Z" }],
    categorySets: [{ id: "category-set-1", corpusId: "corpus-1", displayName: "Category Set" }],
    categorys: [{ id: "category-1", categoryKey: "category.one", categorySetId: "category-set-1", displayName: "Category One", status: "accepted" }],
    categoryTrees: [{ id: "category-set-1", corpusId: "corpus-1", displayName: "Category Set", status: "accepted" }],
    categoryNodes: [{ id: "category-1", categoryKey: "category.one", categorySetId: "category-set-1", parentCategoryKey: null, displayName: "Category One", status: "accepted" }],
    proposals: [{ id: "proposal-1", status: "proposed", title: "Proposal" }],
    artifacts: [{ id: "artifact-1", createdAt: "2026-05-17T20:58:00.000Z" }],
    references: [{ id: "reference-1", importedAt: "2026-05-17T20:57:00.000Z", curationStatus: "accepted" }],
    referenceAttachments: [{ id: "attachment-1", sortKey: "attachment-1" }],
    semanticNodes: [{ id: "semantic-node-1", nodeKey: "node.one", displayName: "Node One" }],
    messages: [{ id: "message-1", messageKind: "reference_curation", messageDomain: "commentary", body: "Looks useful.", status: "active", createdAt: "2026-05-17T20:56:00.000Z", updatedAt: "2026-05-17T20:56:00.000Z" }],
    semanticRelations: [{ id: "relation-1", score: 1 }],
    assignments: [{ id: "assignment-1", queueKey: "queue-1", status: "open" }],
    assignmentEvents: [{ id: "assignment-event-1", createdAt: "2026-05-17T20:55:00.000Z" }],
    doctrineRecords: [{ id: "doctrine-1", slug: "editorial-doctrine-mission" }],
    newsroomSections: [],
    loadError: null,
  };
}

function registerTypeScriptRequire() {
  if (require.extensions[".ts"]) return;
  require.extensions[".ts"] = (module, filename) => {
    const source = fs.readFileSync(filename, "utf8");
    const output = ts.transpileModule(source, {
      compilerOptions: {
        esModuleInterop: true,
        module: ts.ModuleKind.CommonJS,
        moduleResolution: ts.ModuleResolutionKind.Node10,
        target: ts.ScriptTarget.ES2022,
      },
      fileName: filename,
    });
    module._compile(output.outputText, filename);
  };
}
