import {
  type ArticlePublicationItem,
  getArticlePublicationItems,
  type PublicationItem,
} from "./publication-items";
import { type LayoutCursor } from "./pretext-layout";
import { type ArticleFlow, type PlacedTextRange, type SolvedFurniture } from "./layout-types";
import { EMPTY_CURSOR } from "./layout-config";

export function createArticleFlows(items: PublicationItem[]): Map<string, ArticleFlow> {
  return new Map(
    getArticlePublicationItems(items).map((article) => [
      article.slug,
      {
        article,
        currentCursor: { ...EMPTY_CURSOR },
        placedRanges: [],
        usedImageAssetIds: new Set<string>(),
      },
    ]),
  );
}

export function getOrCreateFlow(flows: Map<string, ArticleFlow>, flowKey: string, article: ArticlePublicationItem): ArticleFlow {
  const existing = flows.get(flowKey);
  if (existing) return existing;
  const flow = {
    article,
    currentCursor: { ...EMPTY_CURSOR },
    placedRanges: [],
    usedImageAssetIds: new Set<string>(),
  };
  flows.set(flowKey, flow);
  return flow;
}

export function resetArticleFlow(flow: ArticleFlow): void {
  flow.currentCursor = { ...EMPTY_CURSOR };
  flow.placedRanges = [];
  flow.usedImageAssetIds.clear();
}

export function requireKnownItem(itemId: string, itemsBySlug: Map<string, PublicationItem>): PublicationItem {
  const item = itemsBySlug.get(itemId);
  if (!item) throw new Error(`Layout references missing item ${itemId}`);
  return item;
}

export function requireArticleItem(itemId: string, itemsBySlug: Map<string, PublicationItem>): ArticlePublicationItem {
  const item = requireKnownItem(itemId, itemsBySlug);
  if (item.type !== "article") throw new Error(`Layout articleFrame requires article item ${itemId}`);
  return item;
}

export function createTextRange({
  flow,
  pageId,
  blockId,
  startCursor,
  endCursor,
  exhausted,
}: {
  flow: ArticleFlow;
  pageId: string;
  blockId: string;
  startCursor: LayoutCursor;
  endCursor: LayoutCursor;
  exhausted: boolean;
}): PlacedTextRange {
  return {
    articleId: flow.article.slug,
    pageId,
    blockId,
    startCursor,
    endCursor,
    exhausted,
  };
}

export function commitTextRange(flow: ArticleFlow, range: PlacedTextRange): void {
  flow.currentCursor = { ...range.endCursor };
  flow.placedRanges.push(range);
}

export function commitUsedImageFurniture(flow: ArticleFlow, furniture: SolvedFurniture[]): void {
  for (const item of furniture) {
    if (item.kind === "image") {
      flow.usedImageAssetIds.add(item.assetId);
      continue;
    }
    if (item.kind === "mediaCluster") {
      for (const image of item.images) flow.usedImageAssetIds.add(image.assetId);
    }
  }
}
