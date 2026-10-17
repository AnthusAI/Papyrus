import {
  type ArticleFrameBlockSpec,
  type HeadlineScaleId,
  type LayoutBlockSpec,
  type LayoutPageSpec,
  type LayoutRegionSpec,
  type ResponsiveSpanPolicy,
} from "./layout-plan";
import { type ArticlePublicationItem, type PublicationItem } from "./publication-items";
import { clampRhythmHeight, reserveRhythmRows, snapDownToRhythm } from "./blog-rhythm";
import { type LayoutCursor } from "./pretext-layout";
import {
  type ArticleFlow,
  type ArticleFrameCandidate,
  type ContinuationTitleMetrics,
  type LayoutConfig,
  type PlacedTextRange,
  type SolvedBlock,
  type SolvedFurniture,
  type SolvedPage,
  type SolvedRegion,
} from "./layout-types";
import {
  EMPTY_CURSOR,
  clamp,
  getBlockSpan,
  getBlockWidth,
  getMinimumTextFrameHeight,
  getResponsiveColumnCount,
  pageIdFor,
} from "./layout-config";
import {
  commitTextRange,
  commitUsedImageFurniture,
  createTextRange,
  getOrCreateFlow,
  requireArticleItem,
  requireKnownItem,
  resetArticleFlow,
} from "./article-flow";
import { formatContinuationJumpLabel, getArticleFrameLabel } from "./labels";
import { getContinuationTitleMetrics } from "./chrome-text";
import {
  createImageFurniture,
  createPullQuoteFurniture,
  getMediaVariants,
  getNoMediaVariant,
  getPullQuoteVariants,
  hasAvailablePreferredImage,
} from "./furniture";
import {
  getColumnWhitespace,
  getDeadColumnCount,
  getFurnitureBottom,
  getFurnitureSufficiencyReport,
  getLinesHeight,
  layoutTextColumns,
} from "./text-columns";

const ARTICLE_FRAME_SCORE_WEIGHTS = {
  baseScore: 50_000,
  whitespacePerPixel: 1.1,
  deadColumnPenalty: 8_000,
  imageHeightDeviationPerPixel: 0.35,
  missingImagePenalty: 50_000,
  missingPullQuotePenalty: 2_800,
  narrowedColumnPenaltyPerColumn: 240,
} as const;

export function solveStackedEditorialPage(
  pageSpec: LayoutPageSpec,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  config: LayoutConfig,
): SolvedPage {
  const pageStartY = config.pageChrome.insideHeaderHeight;
  const regions: SolvedRegion[] = [];
  let currentY = pageStartY;
  const ratios = pageSpec.regions.map((region) => region.size?.ratio ?? 1 / pageSpec.regions.length);
  const ratioTotal = ratios.reduce((total, ratio) => total + ratio, 0) || 1;

  for (let index = 0; index < pageSpec.regions.length; index += 1) {
    const regionSpec = pageSpec.regions[index];
    const allocatedHeight = Math.max(
      getMinimumTextFrameHeight(config),
      snapDownToRhythm(
        Math.floor((config.continuationHeight * ratios[index]) / ratioTotal) -
          (index > 0 ? config.pageChrome.continuationSectionSeparatorHeight : 0),
        config.rhythm,
      ),
    );
    const region = solveRegion(regionSpec, pageSpec, allocatedHeight, itemsBySlug, flows, config, currentY);
    regions.push(region);
    currentY += region.height + (index < pageSpec.regions.length - 1 ? config.pageChrome.continuationSectionSeparatorHeight : 0);
  }

  const contentBottom = Math.max(...regions.map((region) => region.y + region.height), pageStartY);
  const height = reserveRhythmRows(
    config.pageChrome.pagePaddingTop +
      contentBottom +
      config.pageChrome.pagePaddingBottom,
    config.rhythm,
  );

  return {
    id: pageSpec.id ?? pageIdFor(pageSpec.pageNumber),
    pageNumber: pageSpec.pageNumber,
    presetId: pageSpec.presetId,
    kind: getPageKind(pageSpec),
    height,
    columnCount: config.columnCount,
    regions,
  };
}

function solveRegion(
  regionSpec: LayoutRegionSpec,
  pageSpec: LayoutPageSpec,
  allocatedHeight: number,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  config: LayoutConfig,
  y: number,
): SolvedRegion {
  const blocks: SolvedBlock[] = [];
  let currentY = 0;

  for (const blockSpec of regionSpec.blocks) {
    const remainingHeight = Math.max(getMinimumTextFrameHeight(config), snapDownToRhythm(allocatedHeight - currentY, config.rhythm));
    const block = solveBlock(blockSpec, pageSpec, remainingHeight, itemsBySlug, flows, config);
    blocks.push({ ...block, y: currentY });
    currentY += block.height;
  }

  return {
    id: regionSpec.id,
    type: regionSpec.type,
    role: regionSpec.role,
    x: 0,
    y,
    width: config.contentWidth,
    height: reserveRhythmRows(
      regionSpec.size?.shrinkToContent
        ? Math.max(currentY, getMinimumTextFrameHeight(config))
        : Math.max(currentY, allocatedHeight),
      config.rhythm,
    ),
    columnCount: config.columnCount,
    blocks,
  };
}

function solveBlock(
  blockSpec: LayoutBlockSpec,
  pageSpec: LayoutPageSpec,
  allocatedHeight: number,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  config: LayoutConfig,
): SolvedBlock {
  if (blockSpec.type === "articleFrame") {
    return solveArticleFrameBlock(blockSpec, pageSpec, allocatedHeight, itemsBySlug, flows, config);
  }
  return solveStaticBlock(blockSpec, pageSpec, allocatedHeight, itemsBySlug, config);
}

function solveArticleFrameBlock(
  blockSpec: ArticleFrameBlockSpec,
  pageSpec: LayoutPageSpec,
  allocatedHeight: number,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  config: LayoutConfig,
): SolvedBlock {
  const item = requireArticleItem(blockSpec.itemId, itemsBySlug);
  const flow = getOrCreateFlow(flows, blockSpec.flowKey ?? blockSpec.itemId, item);
  if (blockSpec.startCursor === "beginning") resetArticleFlow(flow);
  const startCursor = blockSpec.startCursor === "beginning" ? { ...EMPTY_CURSOR } : { ...flow.currentCursor };
  const blockWidth = getBlockWidth(config, blockSpec.span);
  const label = getArticleFrameLabel(blockSpec, item, flow);
  const headlineScale = blockSpec.typography?.headlineScale ?? "standard";
  const title = getContinuationTitleMetrics(
    config,
    item,
    blockWidth,
    label,
    headlineScale,
    Boolean(blockSpec.typography?.headlineScale),
    blockSpec.chrome,
  );
  const offeredHeight = getArticleFrameOfferedHeight(blockSpec, allocatedHeight, config);
  const bodyBudget = Math.max(getMinimumTextFrameHeight(config), snapDownToRhythm(offeredHeight - title.totalHeight, config.rhythm));
  const mustExhaust = !blockSpec.cutPolicy?.maxBodyLines && !blockSpec.cutPolicy?.jumpTargetPage;
  const candidates = solveArticleFrameCandidates({
    blockSpec,
    pageSpec,
    item,
    flow,
    startCursor,
    blockWidth,
    label,
    headlineScale,
    title,
    bodyBudget,
    offeredHeight,
    mustExhaust,
    config,
  });
  const best = chooseBestCandidate(candidates, blockSpec.id);
  commitTextRange(flow, best.range);
  commitUsedImageFurniture(flow, best.block.furniture);
  return best.block;
}

function getArticleFrameOfferedHeight(
  blockSpec: ArticleFrameBlockSpec,
  allocatedHeight: number,
  config: LayoutConfig,
): number {
  if (!blockSpec.size?.defaultRows) return allocatedHeight;
  return Math.max(getMinimumTextFrameHeight(config), reserveRhythmRows(blockSpec.size.defaultRows * config.rhythm.rowHeight, config.rhythm));
}

function solveArticleFrameCandidates({
  blockSpec,
  pageSpec,
  item,
  flow,
  startCursor,
  blockWidth,
  label,
  headlineScale,
  title,
  bodyBudget,
  offeredHeight,
  mustExhaust,
  config,
}: {
  blockSpec: ArticleFrameBlockSpec;
  pageSpec: LayoutPageSpec;
  item: ArticlePublicationItem;
  flow: ArticleFlow;
  startCursor: LayoutCursor;
  blockWidth: number;
  label: string;
  headlineScale: HeadlineScaleId;
  title: ContinuationTitleMetrics;
  bodyBudget: number;
  offeredHeight: number;
  mustExhaust: boolean;
  config: LayoutConfig;
}): ArticleFrameCandidate[] {
  const localColumnCounts = getLocalColumnCountCandidates(blockSpec.localGrid?.columns, config, blockWidth);
  const candidates: ArticleFrameCandidate[] = [];

  for (const columnCount of localColumnCounts) {
    const localConfig = { ...config, columnCount, contentWidth: blockWidth };
    const mediaSpec = blockSpec.media[0];
    const hasReusableMedia = mediaSpec
      ? hasAvailablePreferredImage(item, mediaSpec.placement, mediaSpec.assetRole, flow.usedImageAssetIds)
      : false;
    const mediaVariants = getMediaVariants(
      mediaSpec?.required && !hasReusableMedia ? { ...mediaSpec, required: false } : mediaSpec,
      localConfig,
    );
    const effectiveMediaVariants = mediaSpec?.required && hasReusableMedia
      ? [...mediaVariants, getNoMediaVariant(12_000)]
      : mediaVariants;
    const pullQuoteVariants = getPullQuoteVariants(item, blockSpec.pullQuote, localConfig);

    for (const mediaVariant of effectiveMediaVariants) {
      const image = createImageFurniture(item, mediaVariant, localConfig, bodyBudget, flow.usedImageAssetIds);
      if (mediaSpec?.required && hasReusableMedia && !image) continue;

      const minimumHeight = reserveRhythmRows(Math.max(config.linePaintHeight, image ? image.y + image.height : 0), config.rhythm);
      const textHeights = mustExhaust
        ? getExhaustiveTextHeightVariants(Math.max(minimumHeight, bodyBudget), minimumHeight, localConfig)
        : getTextHeightVariants(Math.max(minimumHeight, bodyBudget), minimumHeight, localConfig);
      const furnitureLayoutsAlreadyExhausted = new Set<string>();
      for (const textHeight of textHeights) {
        for (const pullQuoteVariant of pullQuoteVariants) {
          const pullQuote = createPullQuoteFurniture(item, pullQuoteVariant, localConfig, textHeight, image, blockSpec.chrome);
          if (blockSpec.pullQuote?.required && !pullQuote) continue;
          const furnitureLayoutKey = JSON.stringify(pullQuote);
          if (furnitureLayoutsAlreadyExhausted.has(furnitureLayoutKey)) continue;

          const furniture: SolvedFurniture[] = [];
          if (image) furniture.push(image);
          if (pullQuote) furniture.push(pullQuote);
          const textResult = layoutTextColumns({
            item,
            cursor: startCursor,
            columnCount,
            textHeight,
            localConfig,
            furniture,
            furnitureObstacleMarginBottom: config.rhythm.rowHeight,
          });
          if (mustExhaust && textResult.hasMore) continue;
          if (!mustExhaust && textResult.hasMore && textHeight < bodyBudget - 0.75) continue;
          const furnitureSufficiency = getFurnitureSufficiencyReport({
            columns: textResult.columns,
            textHeight,
            furniture,
            hasMore: textResult.hasMore,
            config: localConfig,
          });
          if (!furnitureSufficiency.accepted) continue;
          if (mustExhaust) furnitureLayoutsAlreadyExhausted.add(furnitureLayoutKey);
          const range = createTextRange({
            flow,
            pageId: pageIdFor(pageSpec.pageNumber),
            blockId: blockSpec.id,
            startCursor,
            endCursor: textResult.cursor,
            exhausted: !textResult.hasMore,
          });
          const linesHeight = Math.max(...textResult.columns.map(getLinesHeight), 0);
          const furnitureBottom = getFurnitureBottom(furniture);
          const contentBodyHeight = reserveRhythmRows(Math.max(furnitureBottom, textResult.hasMore ? textHeight : linesHeight, config.linePaintHeight), config.rhythm);
          const reservedBodyHeight = blockSpec.size?.defaultRows && !blockSpec.size.shrinkToContent
            ? Math.max(contentBodyHeight, snapDownToRhythm(offeredHeight - title.totalHeight, config.rhythm))
            : contentBodyHeight;
          const bodyHeight = reserveRhythmRows(reservedBodyHeight, config.rhythm);
          const blockHeight = title.totalHeight + bodyHeight;
          const whitespace = getColumnWhitespace(textResult.columns, bodyHeight, furniture);
          const deadColumns = getDeadColumnCount(textResult.columns, bodyHeight, furniture);
          const score =
            ARTICLE_FRAME_SCORE_WEIGHTS.baseScore -
            whitespace * ARTICLE_FRAME_SCORE_WEIGHTS.whitespacePerPixel -
            deadColumns * ARTICLE_FRAME_SCORE_WEIGHTS.deadColumnPenalty -
            (image
              ? Math.abs(image.height - image.preferredHeight) * ARTICLE_FRAME_SCORE_WEIGHTS.imageHeightDeviationPerPixel
              : ARTICLE_FRAME_SCORE_WEIGHTS.missingImagePenalty) -
            (pullQuote ? 0 : ARTICLE_FRAME_SCORE_WEIGHTS.missingPullQuotePenalty) -
            mediaVariant.fallbackPenalty -
            pullQuoteVariant.fallbackPenalty -
            Math.max(0, config.columnCount - columnCount) * ARTICLE_FRAME_SCORE_WEIGHTS.narrowedColumnPenaltyPerColumn;

          candidates.push({
            block: {
              id: blockSpec.id,
              type: "articleFrame",
              presetId: blockSpec.presetId,
              headlineScale,
              item,
              article: item,
              pageNumber: pageSpec.pageNumber,
              jumpTargetPage: textResult.hasMore ? blockSpec.cutPolicy?.jumpTargetPage : undefined,
              jumpLabel:
                textResult.hasMore && blockSpec.cutPolicy?.jumpTargetPage
                  ? formatContinuationJumpLabel(item, blockSpec.cutPolicy.jumpTargetPage)
                  : undefined,
              label,
              title: item.headline,
              deck: item.deck,
              byline: item.byline,
              dateline: item.dateline,
              section: item.section,
              x: 0,
              y: 0,
              width: blockWidth,
              height: blockHeight,
              span: getBlockSpan(config, blockSpec.span),
              columnCount,
              columns: textResult.columns,
              furniture,
              textRange: range,
              hasMore: textResult.hasMore,
              titleChrome: title,
              titleHeight: title.heading.height,
              bodyHeight,
              furnitureSufficiency,
            },
            range,
            score,
            whitespace,
            furnitureSufficiency,
          });
        }
      }
    }
  }

  return candidates;
}

function solveStaticBlock(
  blockSpec: LayoutBlockSpec,
  pageSpec: LayoutPageSpec,
  allocatedHeight: number,
  itemsBySlug: Map<string, PublicationItem>,
  config: LayoutConfig,
): SolvedBlock {
  const width = config.contentWidth;
  if (blockSpec.type === "itemStack") {
    const items = blockSpec.itemIds.map((itemId) => requireKnownItem(itemId, itemsBySlug));
    const gridColumnCount = Math.max(1, Math.min(config.columnCount, 4));
    const rowCount = Math.ceil(items.length / gridColumnCount);
    const stackHeight = reserveRhythmRows(
      Math.max(getMinimumTextFrameHeight(config), 220 + rowCount * 170),
      config.rhythm,
    );
    return {
      id: blockSpec.id,
      type: blockSpec.type,
      pageNumber: pageSpec.pageNumber,
      title: blockSpec.title,
      items,
      x: 0,
      y: 0,
      width,
      height: stackHeight,
      span: config.columnCount,
      columnCount: gridColumnCount,
      columns: [],
      furniture: [],
    };
  }
  if (blockSpec.type === "adBlock") {
    const adHeight = clampRhythmHeight(allocatedHeight, 260, 720, config.rhythm);
    return {
      id: blockSpec.id,
      type: blockSpec.type,
      presetId: blockSpec.presetId,
      item: blockSpec.itemId ? requireKnownItem(blockSpec.itemId, itemsBySlug) : undefined,
      pageNumber: pageSpec.pageNumber,
      title: "Advertisement",
      x: 0,
      y: 0,
      width,
      height: adHeight,
      span: config.columnCount,
      columnCount: config.columnCount,
      columns: [],
      furniture: [
        {
          kind: "ad",
          id: `${blockSpec.id}-ad`,
          src: blockSpec.imageUrl,
          label: blockSpec.label?.trim() || "Advertisement",
          x: 0,
          y: 0,
          width,
          height: adHeight,
          wrapsText: false,
        },
      ],
    };
  }
  const staticHeight = blockSpec.type === "rule"
    ? config.rhythm.rowHeight
    : clampRhythmHeight(120, getMinimumTextFrameHeight(config), allocatedHeight, config.rhythm);
  return {
    id: blockSpec.id,
    type: blockSpec.type,
    pageNumber: pageSpec.pageNumber,
    x: 0,
    y: 0,
    width,
    height: staticHeight,
    span: config.columnCount,
    columnCount: config.columnCount,
    columns: [],
    furniture: [],
  };
}

function chooseBestCandidate(candidates: ArticleFrameCandidate[], blockId: string): ArticleFrameCandidate {
  const best = candidates.reduce<ArticleFrameCandidate | null>(
    (winner, candidate) => (!winner || candidate.score > winner.score ? candidate : winner),
    null,
  );
  if (!best) throw new Error(`No valid articleFrame candidate solved for ${blockId}`);
  return best;
}

export function getLocalColumnCountCandidates(
  policy: ResponsiveSpanPolicy | undefined,
  config: LayoutConfig,
  blockWidth: number,
): number[] {
  const maxByWidth = getResponsiveColumnCount(blockWidth + config.pageChrome.pagePaddingX * 2, blockWidth, config.gap);
  const min = Math.min(policy?.min ?? 1, maxByWidth, config.columnCount);
  const max = Math.min(policy?.max ?? config.columnCount, maxByWidth, config.columnCount);
  const preferred = clamp(policy?.preferred ?? max, min, max);
  const candidates = [preferred, min, max];
  return Array.from(new Set(candidates)).sort((left, right) => (
    Math.abs(left - preferred) - Math.abs(right - preferred) || right - left
  ));
}

function getTextHeightVariants(maxHeight: number, minHeight: number, config: LayoutConfig): number[] {
  const snappedMinimum = reserveRhythmRows(minHeight, config.rhythm);
  const snappedMaximum = Math.max(snappedMinimum, snapDownToRhythm(maxHeight, config.rhythm));
  if (config.columnCount === 1) return [snappedMaximum];
  const candidates = [snappedMaximum, snappedMinimum].map((height) => clamp(snapDownToRhythm(height, config.rhythm), snappedMinimum, snappedMaximum));
  return Array.from(new Set(candidates)).sort((leftHeight, rightHeight) => rightHeight - leftHeight);
}

function getExhaustiveTextHeightVariants(startHeight: number, minHeight: number, config: LayoutConfig): number[] {
  const snappedMinimum = reserveRhythmRows(minHeight, config.rhythm);
  const snappedBudget = Math.max(snappedMinimum, reserveRhythmRows(startHeight, config.rhythm));
  const step = config.rhythm.rowHeight * 4;
  const maximum = snappedBudget + config.rhythm.rowHeight * 240;
  const heights: number[] = [];
  for (let height = snappedMinimum; height <= maximum; height += step) heights.push(height);
  return heights;
}

function getPageKind(pageSpec: LayoutPageSpec): string {
  if (pageSpec.presetId === "page.regionStack" && pageSpec.regions.length > 1) return "regionStack";
  if (pageSpec.presetId === "page.railMain") return "railMain";
  return "articlePage";
}

export function collectPageTextRanges(page: SolvedPage): PlacedTextRange[] {
  return page.regions.flatMap((region) => region.blocks.flatMap((block) => (block.textRange ? [block.textRange] : [])));
}
