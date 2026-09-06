import type { Article } from "./articles";
import type { EditionContent } from "./content-types";
import { createDefaultEditionLayoutPlan } from "./layout-plan";
import { parseMarkusDocument } from "./markus-ir";
import { markusDocumentToArticle } from "./markus-to-article";
import { articleToPublicationItem } from "./publication-items";
import pilobolSampleAst from "../scripts/fixtures/pilobol-sample.ast.json";

export const PILOBOL_SAMPLE_SCENARIO_ID = "pilobol-sample";
export const PILOBOL_SAMPLE_SLUG = "sample";
export const PILOBOL_SAMPLE_MARKDOWN_PATH = "web/content/articles/sample.md";

let cachedArticle: Article | null = null;

/** Lazy singleton — parses the committed AST fixture once per process, never spawns `markus ast`. */
export function getPilobolSampleArticle(): Article {
  if (!cachedArticle) {
    const document = parseMarkusDocument(pilobolSampleAst);
    cachedArticle = markusDocumentToArticle(document, {
      slug: PILOBOL_SAMPLE_SLUG,
      markdownDir: "web/content/articles",
      assetUrlPrefix: "/pilobol-sample-assets",
      section: "Pilobol.us",
    });
  }
  return cachedArticle;
}

export function createPilobolSampleEditionContent(): Pick<
  EditionContent,
  "title" | "editionDate" | "description" | "layoutPlan" | "items"
> {
  const article = getPilobolSampleArticle();
  return {
    title: "Pilobol.us Dual Renderer PoC",
    editionDate: article.dateline || "Sunday, September 6, 2026",
    description:
      "PPY-10e4cd: one Markus Markdown article projected into Pretext newsprint via lib/markus-projection.ts.",
    layoutPlan: createDefaultEditionLayoutPlan([article.slug]),
    items: [articleToPublicationItem(article)],
  };
}
