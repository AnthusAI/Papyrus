import assert from "node:assert/strict";
import {
  articleStatusLabel,
  emptyArticle,
  errorLine,
  hasPendingChanges,
  loadArticleRows,
  locateError,
  slugify,
  sourceLineOffset,
  stagingPreviewUrl,
  suggestSlug,
  type ArticlesDataClient,
} from "../lib/newsroom-articles";
import { createDemoArticlesBackend } from "../lib/content-actions-demo";
import { ContentActionFailure } from "../lib/content-actions-client";

async function expectFailure(run: () => Promise<unknown>, code: string) {
  await assert.rejects(run, (error: unknown) => {
    assert.ok(error instanceof ContentActionFailure);
    assert.equal(error.errors[0].code, code);
    return true;
  });
}

async function main() {
  assert.equal(slugify("  Forty Billion Dollars! "), "forty-billion-dollars");
  assert.equal(suggestSlug('title: "Forty Billion Dollars"\nsection: x'), "forty-billion-dollars");
  assert.equal(suggestSlug("title: Café Society\n"), "cafe-society");
  assert.equal(suggestSlug("deck: no title here\n"), "");
  assert.equal(suggestSlug("title: \n"), "");

  const draft = { id: "a", type: "article", slug: "a", status: "draft", contentHash: "h1" };
  const published = { id: "published-a", sourceItemId: "a", metadata: JSON.stringify({ sourceContentHash: "h1" }) };
  assert.equal(hasPendingChanges(draft, null), false);
  assert.equal(hasPendingChanges({ ...draft, status: "published" }, published), false);
  assert.equal(hasPendingChanges({ ...draft, status: "published", contentHash: "h2" }, published), true);
  assert.equal(
    hasPendingChanges(
      { ...draft, status: "published", contentHash: "h2" },
      { id: "p", metadata: { sourceContentHash: "h2" } },
    ),
    false,
  );
  assert.equal(articleStatusLabel(draft, null), "Draft");
  assert.equal(articleStatusLabel({ ...draft, status: "published" }, published), "Published");
  assert.equal(
    articleStatusLabel({ ...draft, status: "published", contentHash: "h2" }, published),
    "Published, unpublished changes",
  );

  assert.equal(errorLine([]), null);
  assert.equal(
    errorLine([
      { code: "front-matter", message: "x", line: null },
      { code: "markus-validation", message: "y", line: 7 },
    ]),
    7,
  );

  const empty = emptyArticle();
  assert.equal(empty.frontMatterYaml, "title: \n");
  assert.equal(empty.bodyMarkus, "");
  assert.equal(empty.id, null);
  assert.equal(empty.dirty, false);

  assert.equal(sourceLineOffset(null), 0);
  assert.equal(sourceLineOffset("title: x\n"), 3);
  assert.deepEqual(locateError({ code: "markus-validation", message: "m", line: 6 }, "title: x\n"), {
    field: "bodyMarkus",
    line: 3,
  });
  assert.deepEqual(locateError({ code: "front-matter", message: "m", line: null }, "title: x\n"), {
    field: "frontMatterYaml",
    line: null,
  });
  assert.deepEqual(locateError({ code: "markus-syntax", message: "m", line: null }, "title: x\n"), {
    field: "bodyMarkus",
    line: null,
  });

  assert.equal(stagingPreviewUrl(undefined, "article", "a", false), null);
  assert.equal(stagingPreviewUrl("https://s.example/", "article", "a", false), "https://s.example/articles/a");
  assert.equal(stagingPreviewUrl("https://s.example", "article", "a", true), "https://s.example/articles/a.html");

  const pages: Record<string, unknown[]> = {
    "article#draft": [{ id: "d", lineageId: "d", type: "article", slug: "d", title: null, status: "draft", contentHash: "x", updatedAt: "2026-01-01T00:00:00Z" }],
    "article#published": [
      { id: "p", lineageId: "p", type: "article", slug: "p", title: "P", status: "published", contentHash: "n", updatedAt: "2026-03-01T00:00:00Z" },
    ],
    "page#draft": [],
    "page#published": [],
  };
  const client = {
    models: {
      Item: {
        listItemsByTypeStatusAndPublishedAt: async ({ typeStatus }: { typeStatus: string }) => ({ data: pages[typeStatus] }),
        get: async () => ({ data: null }),
      },
      PublishedItem: {
        listPublishedItemsByTypeStatusAndPublishedAt: async ({ typeStatus }: { typeStatus: string }) => ({
          data: typeStatus === "article#published"
            ? [{ id: "published-p", itemLineageId: "p", metadata: JSON.stringify({ sourceContentHash: "old" }) }]
            : [],
        }),
      },
    },
  } as unknown as ArticlesDataClient;
  const rows = await loadArticleRows(client);
  assert.deepEqual(rows.map((row) => row.id), ["p", "d"]);
  assert.equal(rows[0].pending, true);
  assert.equal(rows[1].title, "d");

  const demo = createDemoArticlesBackend();
  const demoRows = await demo.listRows();
  assert.deepEqual(demoRows.map((row) => [row.status, row.pending]).sort(), [
    ["draft", false],
    ["published", false],
    ["published", true],
  ]);
  await expectFailure(
    () => demo.actions.deriveMarkus({ frontMatterYaml: "title: x\n", bodyMarkus: "ok\n\n:::nope\n" }),
    "markus-validation",
  );
  const saved = await demo.actions.saveItemDraft({
    id: null, type: "article", slug: "new-one", section: null, frontMatterYaml: "title: New One\n",
    bodyMarkus: "Hello.\n", aliases: [], expectedContentHash: null,
  });
  await expectFailure(
    () => demo.actions.saveItemDraft({
      id: saved.item.id, type: "article", slug: "new-one", section: null, frontMatterYaml: "title: New One\n",
      bodyMarkus: "Changed.\n", aliases: [], expectedContentHash: "stale",
    }),
    "conflict",
  );
  const published2 = await demo.actions.publishItem(saved.item.id);
  assert.equal(published2.versionNumber, 1);
  await expectFailure(
    () => demo.actions.saveItemDraft({
      id: saved.item.id, type: "article", slug: "renamed", section: null, frontMatterYaml: "title: New One\n",
      bodyMarkus: "Hello.\n", aliases: [], expectedContentHash: saved.item.contentHash,
    }),
    "slug-locked",
  );
  await demo.actions.unpublishItem(saved.item.id);
  assert.equal((await demo.loadArticle(saved.item.id)).status, "draft");

  console.log("newsroom articles helpers ok");
}

void main();
