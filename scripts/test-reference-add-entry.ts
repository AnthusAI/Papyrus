import assert from "node:assert/strict";
import test from "node:test";
import * as React from "react";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { PrimingPanelProps } from "cyclotron/components/priming-panel";
import { DEFAULT_RELEVANCE_CYCLOTRON } from "../lib/relevance-status";
import type { CurationBootstrap } from "../lib/curation-client";

const ENGINE_WORDS = /priming|cyclotron|classifier|calibration|sweep|onboarding|version/i;
const labels = DEFAULT_RELEVANCE_CYCLOTRON.labels;
const url = { labels, requests: [], onRequest: () => undefined };
const scope = { accountId: "account-a", publicationId: "publication-a", bindingRevision: "binding-1" };
const bootstrap = (overrides: Partial<CurationBootstrap>): CurationBootstrap => ({
  scope, mode: "embedded", bindingRef: null, capabilities: ["read", "review"],
  priming: { listId: "examples", classifiers: [{ id: "editor", revision: 1 }] }, ...overrides,
});

function text(html: string) {
  return html.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
}

async function modules() {
  (globalThis as { React?: typeof React }).React = React;
  return {
    ...(await import("../components/reference-add-entry")),
    ...(await import("../components/reference-curation-controls")),
    ...(await import("../components/newsroom-curation-provider")),
    ...(await import("../components/newsroom-references-view")),
  };
}

const panel = { client: {} as PrimingPanelProps["client"], listId: "examples", classifiers: [{ id: "editor", revision: 1 }] };

test("With no curation session only the URL option renders", async () => {
  const { ReferenceAddEntry, NewsroomReferencesView } = await modules();
  const urlOnly = renderToStaticMarkup(createElement(ReferenceAddEntry, { url, importOptions: null }));
  assert.ok(urlOnly.includes('aria-label="Add a reference"'));
  assert.ok(urlOnly.includes("Reference URL"));
  assert.ok(!urlOnly.includes("Import a file"));
  assert.ok(!urlOnly.includes("Paste a URL"));
  assert.ok(!urlOnly.includes("data-cyclotron-priming"));

  const view = renderToStaticMarkup(createElement(NewsroomReferencesView, {
    references: [], onReview: () => undefined, cyclotronPriming: { labels, requests: [], onRequest: () => undefined },
  }));
  assert.ok(view.includes("Reference URL"));
  assert.ok(!view.includes("Import a file"));
  assert.ok(!view.includes("Publication curation"));
  assert.ok(!view.includes("Add example references"));
  assert.equal((view.match(/aria-label="Add a reference"/g) ?? []).length, 1);
});

test("The import option exists only for a session that may review examples", async () => {
  const { NewsroomCurationProvider, useReferenceImport } = await modules();
  const Probe = () => {
    const found = useReferenceImport();
    return createElement("p", { "data-import": found ? found.sessionKey : "none" });
  };
  const Provider = NewsroomCurationProvider as React.ComponentType<{ bootstrap: CurationBootstrap | null; children?: React.ReactNode }>;
  const probe = (value: CurationBootstrap | null) =>
    renderToStaticMarkup(createElement(Provider, { bootstrap: value }, createElement(Probe)));
  assert.ok(probe(null).includes('data-import="none"'));
  assert.ok(probe(bootstrap({ priming: null })).includes('data-import="none"'));
  assert.ok(probe(bootstrap({ capabilities: ["read"] })).includes('data-import="none"'));
  assert.ok(!probe(bootstrap({})).includes('data-import="none"'));
});

test("A session adds Import a file to the same Add a reference area", async () => {
  const { ReferenceAddEntry } = await modules();
  const both = renderToStaticMarkup(createElement(ReferenceAddEntry, { url, importOptions: panel }));
  assert.ok(both.includes("Paste a URL") && both.includes("Import a file"));
  assert.equal((both.match(/aria-label="Add a reference"/g) ?? []).length, 1);
  assert.ok(!both.includes("data-cyclotron-priming"), "the import panel loads only once chosen");
  const importOnly = renderToStaticMarkup(createElement(ReferenceAddEntry, { url: null, importOptions: panel }));
  assert.ok(importOnly.includes("data-cyclotron-priming") && !importOnly.includes("Reference URL"));
});

test("Editor-facing copy never exposes engine concepts", async () => {
  const { ReferenceAddEntry, NewsroomReferencesView } = await modules();
  const pages = [
    renderToStaticMarkup(createElement(ReferenceAddEntry, { url, importOptions: null })),
    renderToStaticMarkup(createElement(ReferenceAddEntry, { url, importOptions: panel })),
    renderToStaticMarkup(createElement(NewsroomReferencesView, {
      references: [], onReview: () => undefined, cyclotronPriming: { labels, requests: [], onRequest: () => undefined },
    })),
  ];
  for (const html of pages) {
    const visible = text(html.replace(/(aria-label|data-[a-z-]+|class|placeholder)="[^"]*"/g, ""));
    assert.ok(!ENGINE_WORDS.test(visible), `engine word in editor-facing copy: ${visible.match(ENGINE_WORDS)?.[0]}`);
  }
});
