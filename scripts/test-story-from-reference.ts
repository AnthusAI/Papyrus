import assert from "node:assert/strict";
import * as React from "react";
import test from "node:test";
import { createContentActionsClient } from "../lib/content-actions-client";
import { createStoryCaption, readSeededFrom, seededImageLine, sourceAttribution, startBody } from "../lib/story-from-reference";
import { renderToStaticMarkup } from "react-dom/server";
import { createElement } from "react";
import { SeededFromReferenceNote } from "../components/seeded-from-reference-note";

// The component is compiled with the classic JSX transform under tsx.
(globalThis as { React?: unknown }).React = React;

test("the body starts from the summary and ends with the source line, or is the source line alone", () => {
  const line = sourceAttribution("Clef [decision] models", "https://blog.example.com/clef", "Example Blog");
  assert.equal(line, "Source: [Clef (decision) models](https://blog.example.com/clef), Example Blog.");
  assert.equal(startBody("A router picks the cheapest model.", line), `A router picks the cheapest model.\n\n${line}\n`);
  assert.equal(startBody(null, line), `${line}\n`);
  assert.equal(startBody("   ", line), `${line}\n`);
});

test("the seeded image is the source's own address, credited to its site", () => {
  assert.equal(seededImageLine("https://blog.example.com/og.png", 'A "quoted" title', "Example Blog"), `::image{src="https://blog.example.com/og.png" alt="A 'quoted' title" credit="Image: Example Blog"}`);
});

test("a rejected Reference says its vote stays and a pending one says it is also accepted", () => {
  assert.match(createStoryCaption("rejected").note ?? "", /vote stays/);
  assert.match(createStoryCaption("pending").note ?? "", /Also accepts/);
  assert.equal(createStoryCaption("accepted").note, null);
});

const FRONT = 'title: "T"\nseededFrom:\n  kind: reference\n  summary: included\nseededImage:\n  url: "https://blog.example.com/og.png"\n  credit: "Image: Example Blog"\n';

test("the editor reads whether a Story was started from a Reference, and says what needs checking", () => {
  assert.deepEqual(readSeededFrom(FRONT), { summary: "included", imageCredit: "Image: Example Blog", imageUrl: "https://blog.example.com/og.png" });
  assert.equal(readSeededFrom('title: "T"\n'), null);
  const html = renderToStaticMarkup(createElement(SeededFromReferenceNote, { frontMatterYaml: FRONT }));
  assert.match(html, /starting draft/);
  assert.match(html, /right to publish it/);
  assert.match(html, /Example Blog/);
  assert.equal(renderToStaticMarkup(createElement(SeededFromReferenceNote, { frontMatterYaml: 'title: "T"\n' })), "");
  assert.match(renderToStaticMarkup(createElement(SeededFromReferenceNote, { frontMatterYaml: FRONT.replace("included", "withheld") })), /left out/);
  assert.match(renderToStaticMarkup(createElement(SeededFromReferenceNote, { frontMatterYaml: FRONT.replace("included", "none") })), /no summary/);
});

test("the client sends the Reference and the type, and never the preview hint", async () => {
  const seen: string[] = [];
  const client = createContentActionsClient({
    queries: { deriveMarkus: async () => ({}) },
    mutations: {
      saveItemDraft: async () => ({}), publishItem: async () => ({}), unpublishItem: async () => ({}), moveStoryStage: async () => ({}), setStoryStep: async () => ({}), correctReferenceCapture: async () => ({}),
      createStoryFromReference: async (args) => { seen.push(args.input); return { data: JSON.stringify({ ok: true, created: false, existing: [], referenceLineageId: "r" }) }; },
    },
  });
  const result = await client.createStoryFromReference({ referenceId: "r1", itemType: "post", preview: { title: "T", url: null, summary: null, imageUrl: null, site: null } });
  assert.deepEqual(JSON.parse(seen[0]!), { referenceId: "r1", itemType: "post" });
  assert.equal(result.created, false);
});
