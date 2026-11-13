import assert from "node:assert/strict";
import test from "node:test";
import { SITE_DOCUMENT } from "./fixtures/writing-guidelines-fixture";
import {
  addExemplar, derivedChecks, describeChange, diffDocuments, documentFromForm, formFromDocument, isLocked, matchStories, reasonProblem, sourceWords, writingSlug,
} from "../lib/guidelines/writing-guidelines-admin";

test("a form made from a document and turned back gives the same document", () => {
  assert.deepEqual(documentFromForm(formFromDocument(SITE_DOCUMENT), SITE_DOCUMENT, "publication"), SITE_DOCUMENT);
});

test("an empty field is left out, and fields the form does not edit are carried over", () => {
  const form = { ...formFromDocument(SITE_DOCUMENT), lists: { ...formFromDocument(SITE_DOCUMENT).lists, tone: "" } };
  const saved = documentFromForm(form, SITE_DOCUMENT, "publication");
  assert.equal("tone" in saved, false);
  assert.deepEqual(saved.constraints, SITE_DOCUMENT.constraints);
});

test("a section's document never carries the site-only fields", () => {
  const saved = documentFromForm(formFromDocument({ schemaVersion: 1, tone: ["Warm."] }), { schemaVersion: 1, tone: ["Warm."], locked: ["audience"], constraints: [{ id: "x", text: "y" }] }, "section");
  assert.deepEqual(saved, { schemaVersion: 1, tone: ["Warm."] });
});

test("a reason is required and blank spaces are not one", () => {
  assert.match(reasonProblem("  ") ?? "", /Say why/);
  assert.equal(reasonProblem("Because"), null);
});

test("each field says where it came from in words, and a locked field says so", () => {
  const sources = { tone: [{ layer: "publication" }, { layer: "section" }], voice: [{ layer: "publication" }], editorialAim: [{ layer: "section" }] } as any;
  assert.equal(sourceWords("tone", sources, SITE_DOCUMENT, true), "Site and this section");
  assert.equal(sourceWords("voice", sources, SITE_DOCUMENT, true), "Site");
  assert.equal(sourceWords("editorialAim", sources, SITE_DOCUMENT, true), "This section");
  assert.equal(sourceWords("audience", sources, SITE_DOCUMENT, true), "Locked by site");
  assert.equal(sourceWords("audience", sources, SITE_DOCUMENT, false), "Site");
  assert.equal(isLocked(SITE_DOCUMENT, "audience"), true);
});

test("changes between two versions are described in plain words", () => {
  const changes = diffDocuments({ schemaVersion: 1, tone: ["a"], audience: "x" }, { schemaVersion: 1, tone: ["b"], bodyMarkus: "Lead." });
  assert.deepEqual(changes.map((change) => change.path), ["audience", "bodyMarkus", "tone"]);
  assert.deepEqual(changes.map(describeChange), ['Audience: removed "x"', 'Guidance in your own words: added "Lead."', 'Tone: changed from ["a"] to ["b"]']);
});

test("derived checks are the ones whose source names this document, never a hand-written one", () => {
  const policies = [
    { source: "writing-guidelines:editorial-doctrine-writing:v3" }, { source: "writing-guidelines:desk-doctrine-ai-writing:v1" }, { source: "custom" }, { source: "starter:x" },
  ];
  assert.equal(derivedChecks(policies, null).length, 1);
  assert.equal(derivedChecks(policies, "AI").length, 1);
  assert.equal(writingSlug("Culture & Arts"), "desk-doctrine-culture-arts-writing");
});

test("the Story picker narrows by title and never picks a Story twice", () => {
  const stories = [{ lineageId: "a", title: "A good headline" }, { lineageId: "b", title: "Agent mistakes" }];
  assert.deepEqual(matchStories(stories, "HEADLINE").map((story) => story.lineageId), ["a"]);
  const once = addExemplar([], stories[0]);
  assert.equal(addExemplar(once, stories[0]).length, 1);
});
