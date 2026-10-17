import assert from "node:assert/strict";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import type { Article } from "../lib/articles";
import type { EditionContent } from "../lib/content-types";

const PROBE_FLAG = "--probe";

function buildSampleEditionContent(): EditionContent {
  const featuredImage = { src: "/sample/feature.png", alt: "A sample feature image", caption: "Sample caption", credit: "Sample credit" };
  const items = [
    {
      type: "article" as const,
      slug: "featured-article",
      section: "Lead",
      headline: "A featured article",
      deck: "Featured deck",
      byline: "Byline",
      dateline: "City",
      image: featuredImage,
      body: ["Featured body paragraph."],
    },
    { type: "article" as const, slug: "plain-article", section: "Lead", headline: "A plain article", deck: "Plain deck", byline: "Byline", dateline: "City", body: ["Plain body."] },
    { type: "article" as const, slug: "third-article", section: "Lead", headline: "A third article", deck: "Third deck", byline: "Byline", dateline: "City", body: ["Third body."] },
  ];
  return {
    id: "sample-edition",
    source: "fixture",
    title: "Sample Edition",
    editionDate: "2026-07-04",
    description: "Sample description",
    items,
    sections: [{ key: "lead", label: "Lead", description: "Lead stories", itemIds: items.map((item) => item.slug) }],
    layoutPlan: { pages: [] },
  } as unknown as EditionContent;
}

async function renderRhythmMarkup(): Promise<Record<string, string>> {
  const { SITE_BRAND } = await import("../lib/site-brand");
  Object.assign(SITE_BRAND, {
    blogLayout: "rhythm",
    mastheadEyebrow: "Acme Research",
    mastheadTagline: "Sharp analysis. Plain words.",
    mastheadTaglineLines: [
      { emphasis: "Sharp analysis.", tail: "Every week." },
      { emphasis: "Plain words.", tail: "Always." },
    ],
  });
  const { PresentationShell, ArticlePageView, ItemPageView } = await import("../renderers/pretext");
  const content = buildSampleEditionContent();
  const footer = {
    editionBasePath: "/2026/july/04",
    entries: [],
    sections: content.sections.map((section) => ({ key: section.key, label: section.label })),
    subtitle: "Sample subtitle",
  };
  return {
    edition: renderToStaticMarkup(createElement(PresentationShell, { content, editionBasePath: "/2026/july/04", lockedPresentation: "blog" })),
    article: renderToStaticMarkup(
      createElement(ArticlePageView, { article: content.items[0] as Article, backHref: "/back", editionFooter: footer, editionDate: "2026-07-04" }),
    ),
    plainArticle: renderToStaticMarkup(
      createElement(ArticlePageView, { article: content.items[1] as Article, backHref: "/back", editionFooter: footer, editionDate: "2026-07-04" }),
    ),
    item: renderToStaticMarkup(
      createElement(ItemPageView, { item: { type: "brief" as const, slug: "a-brief", title: "A brief", section: "Lead", body: ["Brief body."], image: { src: "/sample/brief.png", alt: "Brief", credit: "Credit" } }, backHref: "/back", editionFooter: footer }),
    ),
  };
}

async function main() {
  if (process.argv.includes(PROBE_FLAG)) {
    process.stdout.write(`${JSON.stringify(await renderRhythmMarkup())}\n`);
    return;
  }
  const probe = spawnSync(
    "npx",
    ["tsx", "--tsconfig", path.resolve(__dirname, "tsconfig.render-snapshots.json"), __filename, PROBE_FLAG],
    { env: { ...process.env, PAPYRUS_SITE_BRAND: "papyrus", NEXT_PUBLIC_PAPYRUS_SITE_BRAND: "papyrus" }, encoding: "utf8", maxBuffer: 64 * 1024 * 1024 },
  );
  assert.equal(probe.status, 0, `rhythm render probe failed: ${probe.stderr}`);
  const markup: Record<string, string> = JSON.parse(probe.stdout.trim().split("\n").pop() ?? "{}");

  const { edition, article, plainArticle, item } = markup;

  assert.match(edition, /class="presentation-page presentation-page--blog blog-rhythm-shell"/);
  assert.match(edition, /data-rhythm-overlay="false"/);
  assert.match(edition, /--blog-rhythm:4px/);
  assert.match(edition, /--blog-row-height:16px/);
  assert.match(edition, /class="presentation-header__eyebrow-strong">Acme</);
  assert.match(edition, /class="presentation-header__eyebrow-muted">Research</);
  assert.equal((edition.match(/presentation-header__tagline-line"/g) ?? []).length, 2);
  assert.match(edition, /presentation-header__tagline-emphasis">Sharp analysis\./);
  assert.match(edition, /class="presentation-section-header__band"><p>Lead<\/p>/);
  assert.equal((edition.match(/class="presentation-rhythm-hrule"/g) ?? []).length, 2);
  assert.match(edition, /data-hide-in-secondary-pair="true"/);
  assert.match(edition, /class="presentation-item__body"/);
  assert.match(edition, /data-item-id="featured-article"[^>]*>|data-item-id="featured-article"/);

  assert.match(article, /class="article-shell article-shell--edition blog-rhythm-shell"/);
  assert.match(article, /class="article-page article-float-grid"/);
  assert.match(article, /class="article-float-grid__header"/);
  assert.match(article, /class="presentation-item__media article-float-grid__media"/);
  assert.match(article, /class="presentation-section-nav"/);
  assert.doesNotMatch(article, /class="article-nav"/);

  assert.match(plainArticle, /class="article-page"/);
  assert.doesNotMatch(plainArticle, /article-float-grid/);

  assert.match(item, /data-item-type="brief"/);

  for (const rendered of Object.values(markup)) {
    assert.doesNotMatch(rendered, /threat|--ti-|\bti-/i, "rhythm layout markup carries no brand-specific names");
  }

  console.log("rhythm blog layout ok");
}

void main();
