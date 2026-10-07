import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Article } from "../lib/articles";
import type { EditionContent } from "../lib/content-types";

const SNAPSHOT_DIRECTORY = path.resolve(__dirname, "fixtures/brand-render-snapshots");
const BRAND_IDS_WITHOUT_RHYTHM_LAYOUT = ["papyrus", "pilobol-us", "anth-us", "threat-intelligence"];
const PROBE_FLAG = "--probe";
const UPDATE_FLAG = "--update";

function buildSampleEditionContent(): EditionContent {
  const featuredImage = {
    src: "/sample/feature.png",
    alt: "A sample feature image",
    caption: "Sample caption",
    credit: "Sample credit",
  };
  const featuredArticle = {
    slug: "sample-featured-article",
    section: "Lead",
    headline: "A featured article with an image",
    deck: "A deck for the featured article",
    byline: "Sample Byline",
    dateline: "Sample City",
    image: featuredImage,
    body: ["First paragraph of the featured article.", "Second paragraph of the featured article."],
  };
  const plainArticle = {
    slug: "sample-plain-article",
    section: "Lead",
    headline: "A plain article without an image",
    deck: "A deck for the plain article",
    byline: "Sample Byline",
    dateline: "Sample City",
    body: ["Only paragraph of the plain article."],
  };
  const items = [featuredArticle, plainArticle].map((article) => ({ type: "article" as const, ...article }));
  return {
    id: "sample-edition",
    source: "fixture",
    title: "Sample Edition",
    editionDate: "2026-07-04",
    description: "A sample edition used for render snapshots",
    items,
    sections: [{ key: "lead", label: "Lead", description: "Lead stories", itemIds: items.map((item) => item.slug) }],
    layoutPlan: { pages: [] },
  } as unknown as EditionContent;
}

async function renderSnapshotsForActiveBrand(): Promise<Record<string, string>> {
  const { PresentationShell, ArticlePageView, ItemPageView } = await import("../renderers/pretext");
  const content = buildSampleEditionContent();
  const article = content.items[0] as Article;
  const footer = {
    editionBasePath: "/2026/july/04",
    entries: [],
    sections: content.sections.map((section) => ({ key: section.key, label: section.label })),
    subtitle: "Sample subtitle",
  };
  return {
    blogEdition: renderToStaticMarkup(
      createElement(PresentationShell, { content, editionBasePath: "/2026/july/04", lockedPresentation: "blog" }),
    ),
    magazineEdition: renderToStaticMarkup(
      createElement(PresentationShell, { content, editionBasePath: "/2026/july/04", lockedPresentation: "magazine" }),
    ),
    articlePage: renderToStaticMarkup(
      createElement(ArticlePageView, { article, backHref: "/back", editionFooter: footer, editionDate: "2026-07-04" }),
    ),
    itemPage: renderToStaticMarkup(
      createElement(ItemPageView, { item: content.items[0], backHref: "/back", editionFooter: footer, editionDate: "2026-07-04" }),
    ),
  };
}

function probeBrand(brandId: string): Record<string, string> {
  const probe = spawnSync("npx", ["tsx", "--tsconfig", path.resolve(__dirname, "tsconfig.render-snapshots.json"), __filename, PROBE_FLAG], {
    env: { ...process.env, PAPYRUS_SITE_BRAND: brandId, NEXT_PUBLIC_PAPYRUS_SITE_BRAND: brandId },
    encoding: "utf8",
    maxBuffer: 64 * 1024 * 1024,
  });
  assert.equal(probe.status, 0, `${brandId} render probe failed: ${probe.stderr}`);
  return JSON.parse(probe.stdout.trim().split("\n").pop() ?? "{}");
}

async function main() {
  if (process.argv.includes(PROBE_FLAG)) {
    process.stdout.write(`${JSON.stringify(await renderSnapshotsForActiveBrand())}\n`);
    return;
  }
  const shouldUpdate = process.argv.includes(UPDATE_FLAG);
  fs.mkdirSync(SNAPSHOT_DIRECTORY, { recursive: true });
  for (const brandId of BRAND_IDS_WITHOUT_RHYTHM_LAYOUT) {
    const rendered = probeBrand(brandId);
    const snapshotPath = path.join(SNAPSHOT_DIRECTORY, `${brandId}.json`);
    if (shouldUpdate) {
      fs.writeFileSync(snapshotPath, `${JSON.stringify(rendered, null, 2)}\n`);
      continue;
    }
    const expected = JSON.parse(fs.readFileSync(snapshotPath, "utf8"));
    assert.deepEqual(rendered, expected, `${brandId} rendered output must stay byte-identical to the recorded snapshot`);
  }
  console.log(shouldUpdate ? "brand render snapshots updated" : "brand render snapshots ok");
}

void main();
