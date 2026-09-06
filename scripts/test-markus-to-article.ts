/**
 * Verifies `markusDocumentToArticle` against the committed pilobol-sample AST
 * fixture (derived from `web/content/articles/sample.md`). Run with:
 *
 *   npx tsx scripts/test-markus-to-article.ts
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseMarkusDocument } from "../lib/markus-ir";
import { markusDocumentToArticle, resolveMarkusAssetSrc } from "../lib/markus-to-article";
import { projectMarkusJsonToPretext } from "../lib/markus-projection";
import { getPilobolSampleArticle, PILOBOL_SAMPLE_SLUG } from "../lib/pilobol-sample";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

function assert(condition: unknown, message: string): asserts condition {
  if (!condition) throw new Error(`FAIL: ${message}`);
}

const fixturePath = path.join(__dirname, "fixtures", "pilobol-sample.ast.json");
const raw = JSON.parse(readFileSync(fixturePath, "utf8"));
const document = parseMarkusDocument(raw);
const article = markusDocumentToArticle(document, {
  slug: PILOBOL_SAMPLE_SLUG,
  markdownDir: "web/content/articles",
  assetUrlPrefix: "/pilobol-sample-assets",
  section: "Pilobol.us",
});

assert(article.slug === "sample", "slug");
assert(article.headline === "Agents work better with less freedom", "headline from front matter");
assert(article.byline === "Ada Lovelace", "byline from authors");
assert(article.section === "Pilobol.us", "section");
assert(article.dateline.includes("2026"), "dateline includes year");

const projection = projectMarkusJsonToPretext(raw);
assert(article.body.length === projection.body.length, "body length matches projection");
assert(
  article.pullQuotes?.[0] === "The practical breakthrough is not giving agents a bigger sandbox.",
  "pull-quote extracted",
);
assert(article.assets?.[0]?.src === "/pilobol-sample-assets/state-diagram.svg", "figure src resolved for Pretext");
assert(article.image?.src === "/pilobol-sample-assets/state-diagram.svg", "primary image set");

assert(
  article.body.includes("Look before you leap.") && article.body.includes("Only after planning."),
  "card-grid content degraded into body",
);
assert(
  article.body.includes("Planning state keeps risk low.") &&
    article.body.includes("Implementation state is where damage happens."),
  "two-up content degraded into body",
);

assert(
  resolveMarkusAssetSrc("../assets/state-diagram.svg", "web/content/articles", "/pilobol-sample-assets") ===
    "/pilobol-sample-assets/state-diagram.svg",
  "resolveMarkusAssetSrc",
);

const lazyArticle = getPilobolSampleArticle();
assert(lazyArticle.slug === article.slug, "lazy singleton matches direct conversion");
assert(lazyArticle.body.length === article.body.length, "lazy singleton body length");

console.log("Markus -> Article adapter tests passed.");
