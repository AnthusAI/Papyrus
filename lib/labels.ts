import { type ArticlePublicationItem } from "./publication-items";
import { type ArticleFrameBlockSpec } from "./layout-plan";
import { type ArticleFlow } from "./layout-types";

export function formatContinuationJumpLabel(article: ArticlePublicationItem, pageNumber: number): string {
  return `SEE ${getShortSlug(article) ?? "MORE"} ON ${formatSectionPage(pageNumber)}`;
}

export function getArticleFrameLabel(blockSpec: ArticleFrameBlockSpec, article: ArticlePublicationItem, flow: ArticleFlow): string {
  if (blockSpec.startCursor !== "current") return article.section;
  const previousRange = flow.placedRanges[flow.placedRanges.length - 1];
  if (!previousRange) throw new Error(`Continuation block ${blockSpec.id} has no earlier text range to continue from`);
  return formatContinuationSourceLabel(article, getPageNumberFromPageId(previousRange.pageId));
}

function getPageNumberFromPageId(pageId: string): number {
  return Number(pageId.replace(/^page-/, ""));
}

function formatContinuationSourceLabel(article: ArticlePublicationItem, sourcePageNumber: number): string {
  const shortSlug = getShortSlug(article);
  const source = `FROM ${formatSectionPage(sourcePageNumber)}`;
  return shortSlug ? `${shortSlug} ${source}` : source;
}

function getShortSlug(article: ArticlePublicationItem): string | null {
  const shortSlug = article.shortSlug?.trim().toUpperCase();
  return shortSlug || null;
}

function formatSectionPage(pageNumber: number): string {
  return `A${pageNumber}`;
}

export function formatByline(article: ArticlePublicationItem): string {
  return `${article.byline} / ${article.dateline}`.toUpperCase();
}
