import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { setStoryReferenceRole, type StoryReferenceRow, type StoryReferenceRoleStore } from "../amplify/functions/category-action/story-reference-role";

const NOW = "2026-11-08T12:00:00.000Z";
const SOURCE_ID = "semantic-relation-story-source";

function storySource(metadata: Record<string, unknown> = {}): StoryReferenceRow {
  return {
    id: SOURCE_ID,
    relationState: "current",
    predicate: "uses_evidence",
    subjectKind: "item",
    subjectLineageId: "item-story",
    objectKind: "reference",
    objectLineageId: "reference-source",
    metadata: JSON.stringify({ kind: "story.reference", role: "consulted", addedBy: "Ada Example", addedAt: "2026-11-01T00:00:00Z", ...metadata }),
  };
}

function fakeStore(rows: StoryReferenceRow[]) {
  const relations = new Map(rows.map((row) => [row.id, { ...row }]));
  const writes: Array<Record<string, unknown>> = [];
  const store: StoryReferenceRoleStore = {
    getRelation: async (id) => relations.get(id) ?? null,
    updateRelation: async (patch) => {
      writes.push(patch);
      relations.set(patch.id, { ...relations.get(patch.id)!, ...patch });
    },
  };
  return { store, relations, writes };
}

const editor = { callerGroups: ["editor"], actor: "Grace Editor", now: NOW };

test("an editor marks a consulted source as cited with its citation key, and only the metadata and time change", async () => {
  const { store, relations, writes } = fakeStore([storySource()]);
  const before = { ...relations.get(SOURCE_ID)! };
  const result = await setStoryReferenceRole(store, { ...editor, relationId: SOURCE_ID, role: "cited", citationKey: "smith2026", origin: "cli" });
  assert.deepEqual(result, { ok: true, relationId: SOURCE_ID, role: "cited", previousRole: "consulted", citationKey: "smith2026" });
  assert.deepEqual(Object.keys(writes[0]).sort(), ["id", "metadata", "updatedAt"]);
  const row = relations.get(SOURCE_ID)!;
  const metadata = JSON.parse(row.metadata as string);
  assert.deepEqual(metadata, { kind: "story.reference", role: "cited", citationKey: "smith2026", addedBy: "Ada Example", addedAt: "2026-11-01T00:00:00Z", updatedBy: "Grace Editor", updatedAt: NOW, updatedVia: "cli" });
  for (const field of ["predicate", "subjectKind", "subjectLineageId", "objectKind", "objectLineageId", "relationState"]) assert.equal(row[field], before[field]);
});

test("an administrator may change a source's role too", async () => {
  const { store } = fakeStore([storySource()]);
  assert.equal((await setStoryReferenceRole(store, { ...editor, callerGroups: ["admin"], relationId: SOURCE_ID, role: "cited" })).role, "cited");
});

test("a source the story is based on stays based on, whatever role a later call asks for", async () => {
  const { store } = fakeStore([storySource({ role: "based_on" })]);
  const result = await setStoryReferenceRole(store, { ...editor, relationId: SOURCE_ID, role: "cited", citationKey: "k1" });
  assert.equal(result.role, "based_on");
  assert.equal(result.citationKey, "k1");
});

test("an editor cannot change any other relation through this route", async () => {
  const others: StoryReferenceRow[] = [
    { ...storySource(), id: "category-note", predicate: "has_note", metadata: JSON.stringify({ kind: "category.note" }) },
    { ...storySource(), id: "reference-link", predicate: "related_to", subjectKind: "reference", metadata: JSON.stringify({ kind: "reference.link" }) },
    { ...storySource(), id: "provenance", metadata: JSON.stringify({ kind: "provenance", role: "consulted" }) },
    { ...storySource(), id: "wrong-subject", subjectKind: "reference" },
    { ...storySource(), id: "wrong-object", objectKind: "semanticNode" },
  ];
  const { store, writes } = fakeStore(others);
  for (const row of others) {
    await assert.rejects(setStoryReferenceRole(store, { ...editor, relationId: row.id, role: "cited" }), /not a source attached to a Story/, row.id);
  }
  assert.equal(writes.length, 0);
});

test("a viewer or a token in no group cannot change a source's role", async () => {
  const { store, writes } = fakeStore([storySource()]);
  for (const callerGroups of [["viewer"], [], ["Google_123"]]) {
    await assert.rejects(setStoryReferenceRole(store, { ...editor, callerGroups, relationId: SOURCE_ID, role: "cited" }), /Only an editor or administrator/);
  }
  assert.equal(writes.length, 0);
});

test("bad input is refused in words and writes nothing", async () => {
  const { store, writes } = fakeStore([storySource()]);
  await assert.rejects(setStoryReferenceRole(store, { ...editor, relationId: SOURCE_ID, role: "quoted" }), /role must be one of consulted, cited, based_on/);
  await assert.rejects(setStoryReferenceRole(store, { ...editor, relationId: "missing", role: "cited" }), /Story source not found/);
  await assert.rejects(setStoryReferenceRole(store, { ...editor, relationId: SOURCE_ID, role: "cited", citationKey: "k".repeat(201) }), /citationKey is at most 200/);
  await assert.rejects(setStoryReferenceRole(store, { ...editor, actor: " ", relationId: SOURCE_ID, role: "cited" }), /Sign in/);
  assert.equal(writes.length, 0);
});

test("the schema keeps SemanticRelation append-only for the groups and opens the role route to editors and admins only", () => {
  for (const file of ["amplify/data/schema.ts", "amplify/data/resource.ts"]) {
    const source = readFileSync(file, "utf8");
    assert.match(source, /const categoryAppendOnlyOperations: \("read" \| "create"\)\[\] = \["read", "create"\];/, file);
    const model = source.slice(source.indexOf("  SemanticRelation: "));
    const rule = model.slice(model.indexOf(".authorization("), model.indexOf("]),", model.indexOf(".authorization(")));
    assert.match(rule, /^\.authorization\(\(allow\) => \[\s*allow\.groups\(categoryWriteGroups\)\.to\(categoryAppendOnlyOperations\),?\s*$/, file);
    const route = source.slice(source.indexOf("  setStoryReferenceRole: a"), source.indexOf("  suggestReferenceLinks: a"));
    assert.match(route, /\.authorization\(\(allow\) => \[allow\.groups\(categoryWriteGroups\)\]\)/, file);
    assert.match(route, /functionHandler\("categoryAction", categoryAction\)/, file);
  }
  const handler = readFileSync("amplify/functions/category-action/handler.ts", "utf8");
  assert.match(handler, /fieldName === "setStoryReferenceRole"/);
});
