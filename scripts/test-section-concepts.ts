import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import * as React from "react";
import { createElement, type ComponentType, type ReactNode } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createMemoryReferenceLinksStore, ReferenceLinksStoreProvider } from "../components/reference-links-context";
import { SectionConceptsEditor } from "../components/section-concepts-editor";
import { CoreConceptOf } from "../components/wiki-concepts-view";
import {
  addCoreConcept, fallbackConceptName, parseCoreConcepts, removeCoreConcept, sectionsWithCoreConcept, serializeCoreConcepts, setCoreConceptNote,
} from "../lib/section-concepts";

(globalThis as { React?: unknown }).React = React;

const NOW = "2026-11-04T12:00:00Z";
const stored = JSON.stringify([
  { conceptLineageId: "semantic-node-editor_concept--containment-problem", note: "Why we care", addedBy: "An Editor", addedAt: NOW },
  { conceptLineageId: "semantic-node-editor_concept--containment-problem", note: "a duplicate", addedBy: null, addedAt: null },
  { conceptLineageId: "  ", note: "no id" },
  "not an entry",
]);

test("core concepts are read from the stored JSON string or list, once each, and a site without the field has none", () => {
  const list = parseCoreConcepts(stored);
  assert.deepEqual(list.map(entry => [entry.conceptLineageId, entry.note, entry.addedBy]), [["semantic-node-editor_concept--containment-problem", "Why we care", "An Editor"]]);
  assert.deepEqual(parseCoreConcepts(list), list);
  assert.deepEqual(parseCoreConcepts(undefined), []);
  assert.deepEqual(parseCoreConcepts("not json"), []);
  assert.deepEqual(parseCoreConcepts("{}"), []);
  assert.deepEqual(parseCoreConcepts(serializeCoreConcepts(list)), list);
});

test("adding keeps the order and never twice, removing and the note work on one concept", () => {
  const first = addCoreConcept([], "concept-a", "editor", NOW);
  const both = addCoreConcept(first, "concept-b", "editor", NOW);
  assert.deepEqual(addCoreConcept(both, "concept-a", "someone else", NOW), both);
  assert.deepEqual(both.map(entry => entry.conceptLineageId), ["concept-a", "concept-b"]);
  assert.equal(setCoreConceptNote(both, "concept-b", "  Because  ")[1].note, "  Because  ");
  assert.equal(setCoreConceptNote(both, "concept-b", "   ")[1].note, null);
  assert.deepEqual(removeCoreConcept(both, "concept-a").map(entry => entry.conceptLineageId), ["concept-b"]);
});

test("the sections that have a concept are found, and a concept with no node is named from its lineage id", () => {
  const sections = [{ id: "security", coreConcepts: stored }, { id: "culture", coreConcepts: null }, { id: "law" }];
  assert.deepEqual(sectionsWithCoreConcept(sections, "semantic-node-editor_concept--containment-problem").map(section => section.id), ["security"]);
  assert.deepEqual(sectionsWithCoreConcept(sections, "concept-none"), []);
  assert.equal(fallbackConceptName("semantic-node-editor_concept--containment-problem"), "containment problem");
});

const store = createMemoryReferenceLinksStore({ items: [] });
const StoreProvider = ReferenceLinksStoreProvider as ComponentType<{ store: typeof store; children?: ReactNode }>;
const render = (node: ReturnType<typeof createElement>) => renderToStaticMarkup(createElement(StoreProvider, { store }, node));

test("section settings show 'Core concepts', the help sentence, and a row with a note box and a Remove button for each concept", () => {
  const html = render(createElement(SectionConceptsEditor, { entries: parseCoreConcepts(stored), names: { "semantic-node-editor_concept--containment-problem": "containment problem" }, onChange: () => undefined }));
  assert.match(html, />Core concepts</);
  assert.match(html, /Every agent working in this section is told about these concepts, with the note you write here\./);
  assert.match(html, /data-section-concept="semantic-node-editor_concept--containment-problem"/);
  assert.match(html, /containment problem/);
  assert.match(html, /Why we care/);
  assert.match(html, /data-section-concept-remove=/);
  assert.match(html, />Remove</);
  assert.doesNotMatch(html, /\btrack(s|ed)?\b/i);
});

test("with none, the section says it has no core concepts", () => {
  assert.match(render(createElement(SectionConceptsEditor, { entries: [], onChange: () => undefined })), /This section has no core concepts yet\./);
});

test("the concept page lists only the sections that have it, each with a remove control, and one 'Add to a section' button", () => {
  const sections = [{ id: "security", title: "Security", coreConcepts: stored }, { id: "culture", title: "Culture" }, { id: "law", title: "Law" }] as never;
  const html = renderToStaticMarkup(createElement(CoreConceptOf, { disabled: false, lineage: "semantic-node-editor_concept--containment-problem", onChange: () => undefined, sections }));
  assert.match(html, /<h2>Core concept of<\/h2>/);
  assert.match(html, /data-core-concept-of-section="security"/);
  assert.match(html, /Remove from Security/);
  assert.doesNotMatch(html, /data-core-concept-of-section="culture"/);
  assert.match(html, /Add to a section/);
  assert.doesNotMatch(html, /Add to Culture|Add to Law/);
  assert.doesNotMatch(html, /\btrack(s|ed)?\b/i);
});

test("the concept page says so when no section has the concept", () => {
  const html = renderToStaticMarkup(createElement(CoreConceptOf, { disabled: false, lineage: "concept-x", onChange: () => undefined, sections: [{ id: "security", title: "Security" }] as never }));
  assert.match(html, /This is not a core concept of any section yet\./);
});

test("the field and the backend mutation exist in both schema files, and only editors and admins can make a concept", () => {
  for (const file of ["amplify/data/resource.ts", "amplify/data/schema.ts"]) {
    const source = readFileSync(file, "utf8");
    assert.match(source, /coreConcepts: a\.json\(\)/, file);
    const mutation = source.slice(source.indexOf("createEditorConcept: a"));
    const block = mutation.slice(0, mutation.indexOf(".handler("));
    assert.match(block, /arguments\(\{ name: a\.string\(\)\.required\(\) \}\)/, file);
    assert.match(block, /allow\.groups\(categoryWriteGroups\)/, file);
  }
  assert.match(readFileSync("amplify/functions/category-action/handler.ts", "utf8"), /fieldName === "createEditorConcept"/);
});
