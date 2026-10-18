import { type PublicationItem } from "./publication-items";
import { type EditionLayoutPlan, type LayoutPageSpec } from "./layout-plan";
import {
  type ArticleFlow,
  type LayoutConfig,
  type NewspaperLayout,
  type PlacedTextRange,
  type SolvedPage,
} from "./layout-types";
import { getLayoutConfig } from "./layout-config";
import { createArticleFlows } from "./article-flow";
import { collectPageTextRanges, solveStackedEditorialPage } from "./article-frame-solver";
import { solveFrontMosaicPage } from "./front-mosaic";

export function buildNewspaperLayout(
  items: PublicationItem[],
  pageWidth: number,
  viewportHeight: number,
  layoutPlan: EditionLayoutPlan,
): NewspaperLayout {
  const config = getLayoutConfig(pageWidth, viewportHeight);
  const itemsBySlug = new Map(items.map((item) => [item.slug, item]));
  const flows = createArticleFlows(items);
  const pages: SolvedPage[] = [];
  const textRanges: PlacedTextRange[] = [];

  for (const pageSpec of layoutPlan.pages) {
    const page = solvePage(pageSpec, itemsBySlug, flows, config);
    pages.push(page);
    textRanges.push(...collectPageTextRanges(page));
  }

  const pageHeights: Record<number, number> = {};
  for (const page of pages) {
    pageHeights[page.pageNumber] = page.height;
  }
  const maxPageHeight = Math.max(...pages.map((page) => page.height), 0);

  return {
    columnCount: config.columnCount,
    contentWidth: config.contentWidth,
    gap: config.gap,
    rowGap: config.rowGap,
    rhythm: config.rhythm,
    pageHeight: maxPageHeight,
    frontPageHeight: pageHeights[1] ?? maxPageHeight,
    pageHeights,
    pageChrome: config.pageChrome,
    pages,
    textRanges,
  };
}

function solvePage(
  pageSpec: LayoutPageSpec,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  config: LayoutConfig,
): SolvedPage {
  if (pageSpec.presetId === "front.mosaic") {
    return solveFrontMosaicPage(pageSpec, itemsBySlug, flows, config);
  }
  return solveStackedEditorialPage(pageSpec, itemsBySlug, flows, config);
}

export * from "./layout-types";
export type { TextLine } from "./pretext-layout";
