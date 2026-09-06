import type { Article } from "./articles";
import type { EditionContent } from "./content-types";
import { normalizeEditionLayoutPlan, type EditionLayoutPlan } from "./layout-plan";
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

/**
 * Newsprint layout for the single-article pilobol-sample scenario. Cannot use
 * `createDefaultEditionLayoutPlan` — that helper hardcodes continuation frames
 * for fixture slugs (`agent-procedure-patterns`, etc.) on pages 2–3.
 */
export function createPilobolSampleLayoutPlan(): EditionLayoutPlan {
  const slug = PILOBOL_SAMPLE_SLUG;
  return normalizeEditionLayoutPlan(
    {
      pages: [
        {
          id: "page-1",
          pageNumber: 1,
          presetId: "front.mosaic",
          grid: { columns: { min: 1, preferred: 6, max: 6 } },
          regions: [
            {
              id: "pilobol-sample-front",
              type: "fullPage",
              localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
              blocks: [
                {
                  id: `front-${slug}`,
                  type: "articleFrame",
                  presetId: "front.teaser",
                  itemId: slug,
                  flowKey: slug,
                  startCursor: "beginning",
                  role: "primary",
                  editorialPriority: "primary",
                  typography: { headlineScale: "feature" },
                  span: { min: 1, preferred: 6, max: 6 },
                  localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
                  cutPolicy: { maxBodyLines: 16, jumpTargetPage: 2 },
                  media: [
                    {
                      required: false,
                      assetRole: "lead",
                      placement: {
                        anchor: "right",
                        span: { min: 1, preferred: 2, max: 2 },
                        vertical: "top",
                        collapse: "inline",
                        crop: "preserve",
                        wrapsText: true,
                      },
                    },
                  ],
                  pullQuote: {
                    required: false,
                    placements: [
                      {
                        anchor: "right",
                        span: { min: 1, preferred: 1, max: 2 },
                        vertical: "middle",
                        collapse: "omit",
                        crop: "preserve",
                        wrapsText: true,
                      },
                    ],
                  },
                },
              ],
            },
          ],
        },
        {
          id: "page-2",
          pageNumber: 2,
          presetId: "page.full",
          grid: { columns: { min: 1, preferred: 6, max: 6 } },
          regions: [
            {
              id: "pilobol-sample-continuation",
              type: "fullPage",
              size: { shrinkToContent: true },
              localGrid: { columns: { min: 1, preferred: 6, max: 6 } },
              blocks: [
                {
                  id: `${slug}-page-2`,
                  type: "articleFrame",
                  presetId: "article.mediaInset",
                  itemId: slug,
                  flowKey: slug,
                  startCursor: "current",
                  role: "primary",
                  localGrid: { columns: { min: 2, preferred: 6, max: 6 } },
                  media: [
                    {
                      required: false,
                      assetRole: "continuationInset",
                      placement: {
                        anchor: "center",
                        span: { min: 1, preferred: 2, max: 3 },
                        vertical: "upperThird",
                        collapse: "inline",
                        crop: "preserve",
                        wrapsText: true,
                      },
                    },
                  ],
                  pullQuote: {
                    required: false,
                    placements: [
                      {
                        anchor: "right",
                        span: { min: 1, preferred: 1, max: 2 },
                        vertical: "middle",
                        collapse: "omit",
                        crop: "preserve",
                        wrapsText: true,
                      },
                    ],
                  },
                },
              ],
            },
          ],
        },
      ],
    },
    "pilobol-sample layoutPlan",
  );
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
    layoutPlan: createPilobolSampleLayoutPlan(),
    items: [articleToPublicationItem(article)],
  };
}
