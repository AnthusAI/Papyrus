import {
  type ArticleFrameBlockSpec,
  type ArticleFrameCompositionSlotSpec,
  type EditorialPriorityId,
  type FrontResponsiveLayoutOrder,
  type FrontResponsiveLayoutSpec,
  type FrontResponsiveSlotSpec,
  type LayoutPageSpec,
  type LayoutRegionSpec,
  type ResponsivePlacementSpec,
} from "./layout-plan";
import {
  type ArticlePublicationItem,
  getPublicationItemImageAssets,
  type PublicationItem,
} from "./publication-items";
import {
  clampRhythmHeight,
  reserveRhythmRows,
  snapDownToRhythm,
  snapPreferredHeightToRhythm,
  snapPreservedImageHeightToRhythm,
  type VerticalRhythm,
} from "./blog-rhythm";
import { toPublicReaderPath } from "./reader-base-path";
import { layoutTextLines, type TextObstacle } from "./pretext-layout";
import {
  type ArticleFlow,
  type FrontArticlePlacement,
  type FrontArticleSolveOptions,
  type FrontCompositionFlowMode,
  type FrontRow,
  type LayoutConfig,
  type PlacementVariant,
  type SolvedBlock,
  type SolvedChromeBox,
  type SolvedFrontFooter,
  type SolvedFrontFooterEntry,
  type SolvedFrontFooterUtilityEntry,
  type SolvedFrontGridPlacement,
  type SolvedFurniture,
  type SolvedImageFurniture,
  type SolvedPage,
} from "./layout-types";
import {
  IMAGE_CAPTION_FONT_SIZE,
  SERIF_TEXT_FONT,
  clamp,
  getMinimumTextFrameHeight,
  getSpanWidth,
  pageIdFor,
} from "./layout-config";
import {
  commitTextRange,
  commitUsedImageFurniture,
  createTextRange,
  getOrCreateFlow,
  requireArticleItem,
  resetArticleFlow,
} from "./article-flow";
import {
  getStoryChromeHeight,
  getStoryChromeMetrics,
  getStoryJumpReserveHeight,
  isTextCompositionSlot,
  resolveFrontStoryRole,
  resolveHeadlineScale,
  solveCompositionChromeBox,
} from "./chrome-text";
import { getLineLimitHeight, getPrepared, layoutTextColumns } from "./text-columns";
import { formatContinuationJumpLabel } from "./labels";
import { getLocalColumnCountCandidates } from "./article-frame-solver";
import {
  createImageFurniture,
  getImageAspectRatio,
  getImageCaption,
  getImageCaptionHeight,
  getObjectPosition,
  getPreferredImage,
  resolvePreferredPlacementVariant,
} from "./furniture";

export function solveFrontMosaicPage(
  pageSpec: LayoutPageSpec,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  config: LayoutConfig,
): SolvedPage {
  const regionSpec = pageSpec.regions[0];
  const frontBlockSpecs = regionSpec.blocks.filter((block): block is ArticleFrameBlockSpec => block.type === "articleFrame");
  const activeResponsiveLayout = getActiveFrontResponsiveLayout(regionSpec, config);
  const placements = activeResponsiveLayout
    ? resolveResponsiveFrontArticlePlacements(frontBlockSpecs, activeResponsiveLayout, config)
    : resolveDefaultFrontArticlePlacements(frontBlockSpecs, config);
  const baseRowHeights = getResponsiveFrontRowHeights(config, placements);
  const solvedPlacements = placements.map((placement) => ({
    ...placement,
    rowHeight: getResponsiveFrontPlacementHeight(placement, baseRowHeights, config.rowGap),
  }));
  const previewFlows = new Map<string, ArticleFlow>();
  const provisionalBlocks = solvedPlacements.map((placement) => (
    solveFrontArticleFrame(placement, itemsBySlug, previewFlows, config, pageSpec.pageNumber)
  ));
  const rowHeights = getSolvedResponsiveFrontRowHeights(baseRowHeights, provisionalBlocks, config);
  const finalPlacements = solvedPlacements.map((placement) => ({
    ...placement,
    rowHeight: getResponsiveFrontPlacementHeight(placement, rowHeights, config.rowGap),
  }));
  const flowKeysResolvedAgain = new Set<string>();
  const blocks = finalPlacements.map((placement, index) => {
    const flowKey = placement.block.flowKey ?? placement.block.itemId;
    const provisionalBlock = provisionalBlocks[index];
    const provisionalRowHeightStillHolds = placement.rowHeight === solvedPlacements[index].rowHeight;
    if (provisionalRowHeightStillHolds && !flowKeysResolvedAgain.has(flowKey)) {
      return adoptProvisionalFrontBlock(provisionalBlock, placement, itemsBySlug, flows);
    }
    flowKeysResolvedAgain.add(flowKey);
    return solveFrontArticleFrame(placement, itemsBySlug, flows, config, pageSpec.pageNumber, {
      enforcePlacementHeight: true,
    });
  });
  const gridHeight = getFrontPageGridHeightFromRowHeights(rowHeights, config.rowGap);
  const frontFooter = solveFrontFooter(blocks, config, pageSpec.pageNumber);
  const regionY = config.pageChrome.pagePaddingTop + config.pageChrome.mastheadHeight + config.pageChrome.frontGridMarginTop;
  const pageHeight = getFrontPageHeightForRegion(config, regionY, gridHeight, frontFooter);

  return {
    id: pageSpec.id ?? pageIdFor(pageSpec.pageNumber),
    pageNumber: pageSpec.pageNumber,
    presetId: pageSpec.presetId,
    kind: "front",
    height: pageHeight,
    columnCount: config.columnCount,
    frontFooter,
    regions: [
      {
        id: regionSpec.id,
        type: regionSpec.type,
        role: regionSpec.role,
        x: 0,
        y: regionY,
        width: config.contentWidth,
        height: gridHeight,
        rowHeights,
        columnCount: config.columnCount,
        blocks,
      },
    ],
  };
}

function adoptProvisionalFrontBlock(
  provisionalBlock: SolvedBlock,
  placement: FrontArticlePlacement,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
): SolvedBlock {
  const { block: blockSpec } = placement;
  const flow = getOrCreateFlow(flows, blockSpec.flowKey ?? blockSpec.itemId, requireArticleItem(blockSpec.itemId, itemsBySlug));
  if (blockSpec.startCursor === "beginning") resetArticleFlow(flow);
  if (provisionalBlock.textRange) commitTextRange(flow, provisionalBlock.textRange);
  commitUsedImageFurniture(flow, provisionalBlock.furniture ?? []);
  return provisionalBlock;
}

function getActiveFrontResponsiveLayout(regionSpec: LayoutRegionSpec, config: LayoutConfig): FrontResponsiveLayoutSpec | null {
  return regionSpec.responsiveLayouts?.find((layout) => (
    config.columnCount >= layout.minColumns && config.columnCount <= layout.maxColumns
  )) ?? null;
}

function resolveResponsiveFrontArticlePlacements(
  blocks: ArticleFrameBlockSpec[],
  layout: FrontResponsiveLayoutSpec,
  config: LayoutConfig,
): FrontArticlePlacement[] {
  const orderedBlocks = orderFrontArticleBlocks(blocks, layout.order);
  const placements: FrontArticlePlacement[] = [];
  const assignedBlockIds = new Set<string>();

  for (const slot of layout.slots) {
    const block = findFrontSlotBlock(slot, blocks, orderedBlocks);
    if (!block || assignedBlockIds.has(block.id)) continue;
    assignedBlockIds.add(block.id);
    placements.push({
      block,
      originalIndex: blocks.indexOf(block),
      solveIndex: placements.length,
      gridPlacement: resolveFrontSlotGridPlacement(slot, config),
    });
  }

  const overflowBlocks = orderedBlocks.filter((block) => !assignedBlockIds.has(block.id));
  const overflowPlacements = resolveFrontOverflowPlacements(
    overflowBlocks,
    blocks,
    placements.length,
    getNextFrontOverflowRow(placements),
    layout.overflow.columnSpan,
    layout.overflow.rowSpan,
    config,
  );

  return [...placements, ...overflowPlacements]
    .sort((left, right) => (
      (left.gridPlacement?.rowStart ?? 0) - (right.gridPlacement?.rowStart ?? 0) ||
      (left.gridPlacement?.columnStart ?? 0) - (right.gridPlacement?.columnStart ?? 0) ||
      left.solveIndex - right.solveIndex
    ))
    .map((placement, solveIndex) => ({ ...placement, solveIndex }));
}

function resolveDefaultFrontArticlePlacements(blocks: ArticleFrameBlockSpec[], config: LayoutConfig): FrontArticlePlacement[] {
  let columnStart = 0;
  let rowStart = 0;
  return blocks.map((block, index) => {
    const columnSpan = getDefaultFrontArticlePlacementSpan(block, config);
    if (columnStart + columnSpan > config.columnCount) {
      rowStart += 1;
      columnStart = 0;
    }
    const placement: FrontArticlePlacement = {
      block,
      originalIndex: index,
      solveIndex: index,
      gridPlacement: {
        columnStart,
        columnSpan,
        rowStart,
        rowSpan: 1,
      },
    };
    columnStart += columnSpan;
    return placement;
  });
}

function getDefaultFrontArticlePlacementSpan(block: ArticleFrameBlockSpec, config: LayoutConfig): number {
  return clamp(block.span?.preferred ?? 1, 1, config.columnCount);
}

function orderFrontArticleBlocks(blocks: ArticleFrameBlockSpec[], order: FrontResponsiveLayoutOrder): ArticleFrameBlockSpec[] {
  if (order !== "editorialPriority") return blocks;
  return blocks
    .map((block, index) => ({ block, index }))
    .sort((left, right) => (
      getEditorialPriorityRank(left.block.editorialPriority) - getEditorialPriorityRank(right.block.editorialPriority) ||
      left.index - right.index
    ))
    .map(({ block }) => block);
}

function findFrontSlotBlock(
  slot: FrontResponsiveSlotSpec,
  blocks: ArticleFrameBlockSpec[],
  orderedBlocks: ArticleFrameBlockSpec[],
): ArticleFrameBlockSpec | null {
  if (slot.blockId) return blocks.find((block) => block.id === slot.blockId) ?? null;
  if (!slot.editorialPriority) return null;
  const occurrence = slot.priorityOccurrence ?? 1;
  return orderedBlocks.filter((block) => block.editorialPriority === slot.editorialPriority)[occurrence - 1] ?? null;
}

function resolveFrontSlotGridPlacement(slot: FrontResponsiveSlotSpec, config: LayoutConfig): SolvedFrontGridPlacement {
  const columnStart = clamp(slot.columnStart - 1, 0, Math.max(0, config.columnCount - 1));
  return {
    columnStart,
    columnSpan: clamp(slot.columnSpan, 1, Math.max(1, config.columnCount - columnStart)),
    rowStart: slot.rowStart - 1,
    rowSpan: slot.rowSpan,
  };
}

function resolveFrontOverflowPlacements(
  overflowBlocks: ArticleFrameBlockSpec[],
  allBlocks: ArticleFrameBlockSpec[],
  solveIndexStart: number,
  rowStart: number,
  requestedColumnSpan: number | "full",
  rowSpan: number,
  config: LayoutConfig,
): FrontArticlePlacement[] {
  const columnSpan = requestedColumnSpan === "full"
    ? config.columnCount
    : clamp(requestedColumnSpan, 1, config.columnCount);
  let columnStart = 0;
  let currentRow = rowStart;
  return overflowBlocks.map((block, index) => {
    if (columnStart + columnSpan > config.columnCount) {
      currentRow += rowSpan;
      columnStart = 0;
    }
    const placement: FrontArticlePlacement = {
      block,
      originalIndex: allBlocks.indexOf(block),
      solveIndex: solveIndexStart + index,
      gridPlacement: {
        columnStart,
        columnSpan,
        rowStart: currentRow,
        rowSpan,
      },
    };
    columnStart += columnSpan;
    return placement;
  });
}

function getNextFrontOverflowRow(placements: FrontArticlePlacement[]): number {
  return placements.reduce((nextRow, placement) => {
    const gridPlacement = placement.gridPlacement;
    if (!gridPlacement) return nextRow;
    return Math.max(nextRow, gridPlacement.rowStart + gridPlacement.rowSpan);
  }, 0);
}

function getResponsiveFrontRowHeights(config: LayoutConfig, placements: FrontArticlePlacement[]): number[] {
  const rowCount = placements.reduce((count, placement) => {
    const gridPlacement = placement.gridPlacement;
    if (!gridPlacement) return count;
    return Math.max(count, gridPlacement.rowStart + gridPlacement.rowSpan);
  }, 0);
  const baseHeights = config.frontRows.map((row) => row.height);
  const fallbackHeight = baseHeights[1] ?? baseHeights[0] ?? reserveRhythmRows(420, config.rhythm);
  return Array.from({ length: rowCount }, (_, index) => baseHeights[index] ?? fallbackHeight);
}

function getResponsiveFrontPlacementHeight(placement: FrontArticlePlacement, rowHeights: number[], rowGap: number): number {
  const gridPlacement = placement.gridPlacement;
  if (!gridPlacement) return getFrontRowHeightFallback(rowHeights);
  return getResponsiveFrontGridPlacementHeight(gridPlacement, rowHeights, rowGap);
}

function getResponsiveFrontGridPlacementHeight(gridPlacement: SolvedFrontGridPlacement, rowHeights: number[], rowGap: number): number {
  return rowHeights
    .slice(gridPlacement.rowStart, gridPlacement.rowStart + gridPlacement.rowSpan)
    .reduce((total, height) => total + height, 0) + rowGap * Math.max(0, gridPlacement.rowSpan - 1);
}

function getFrontRowHeightFallback(rowHeights: number[]): number {
  return rowHeights[0] ?? 0;
}

function solveFrontFooter(blocks: SolvedBlock[], config: LayoutConfig, pageNumber: number): SolvedFrontFooter {
  const entries: SolvedFrontFooterEntry[] = [];
  const seenSections = new Set<string>();
  for (const block of blocks) {
    const section = block.section ?? block.article?.section;
    const articleSlug = block.article?.slug;
    const articleTitle = block.title ?? block.article?.headline;
    if (!section || !articleSlug || !articleTitle) continue;
    const sectionKey = section.trim().toLowerCase();
    if (!sectionKey || seenSections.has(sectionKey)) continue;
    seenSections.add(sectionKey);
    entries.push({
      section,
      articleSlug,
      articleTitle,
      blockId: block.id,
      pageNumber,
    });
  }

  const sectionColumns = entries.length === 0
    ? 1
    : Math.min(entries.length, Math.max(1, config.columnCount <= 1 ? 1 : config.columnCount <= 3 ? 2 : 4));
  const sectionRows = entries.length === 0 ? 0 : Math.ceil(entries.length / sectionColumns);
  const utilityEntries: SolvedFrontFooterUtilityEntry[] = [
    { id: "archive", label: "Archive", href: toPublicReaderPath("/archive"), disabled: false },
    { id: "newsDesk", label: "Newsroom", href: "/newsroom", disabled: false },
    { id: "settings", label: "Settings", href: toPublicReaderPath("/settings"), disabled: false },
    { id: "login", label: "LOGIN", disabled: true },
  ];
  const rowCount = 1 + Math.max(sectionRows, utilityEntries.length);
  return {
    rowHeight: config.rhythm.rowHeight,
    marginTop: config.rhythm.rowHeight,
    height: reserveRhythmRows(rowCount * config.rhythm.rowHeight, config.rhythm),
    sectionRows,
    sectionColumns,
    entries,
    utilityEntries,
  };
}

function getSolvedResponsiveFrontRowHeights(baseRowHeights: number[], blocks: SolvedBlock[], config: LayoutConfig): number[] {
  const rowHeights = [...baseRowHeights];
  for (const block of blocks) {
    const placement = block.front?.gridPlacement;
    if (!placement) continue;
    while (rowHeights.length < placement.rowStart + placement.rowSpan) {
      rowHeights.push(baseRowHeights[baseRowHeights.length - 1] ?? reserveRhythmRows(420, config.rhythm));
    }
    const currentHeight = getResponsiveFrontGridPlacementHeight(placement, rowHeights, config.rowGap);
    if (block.height <= currentHeight) continue;
    const lastRowIndex = placement.rowStart + placement.rowSpan - 1;
    rowHeights[lastRowIndex] = reserveRhythmRows(rowHeights[lastRowIndex] + block.height - currentHeight, config.rhythm);
  }
  return rowHeights;
}

function getEditorialPriorityRank(priority: EditorialPriorityId): number {
  if (priority === "primary") return 0;
  if (priority === "secondary") return 1;
  if (priority === "tertiary") return 2;
  return 3;
}

function solveFrontArticleFrame(
  placement: FrontArticlePlacement,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  config: LayoutConfig,
  pageNumber: number,
  options: FrontArticleSolveOptions = {},
): SolvedBlock {
  const { block: blockSpec } = placement;
  const item = requireArticleItem(blockSpec.itemId, itemsBySlug);
  const flow = getOrCreateFlow(flows, blockSpec.flowKey ?? blockSpec.itemId, item);
  if (blockSpec.startCursor === "beginning") resetArticleFlow(flow);

  const span = placement.gridPlacement?.columnSpan ?? Math.min(blockSpec.span?.preferred ?? 1, config.columnCount);
  const blockWidth = getSpanWidth(config, span);
  if (blockSpec.composition) {
    return solveComposedFrontArticleFrame(placement, item, flow, config, pageNumber, span, blockWidth, options);
  }
  const preludeImage = createFrontPreludeImage(item, blockSpec, blockWidth, config, flow.usedImageAssetIds);
  const storyRole = resolveFrontStoryRole(blockSpec, span, preludeImage !== null);
  const headlineScale = resolveHeadlineScale(blockSpec, storyRole);
  const chrome = getStoryChromeMetrics(config, item, storyRole, headlineScale, blockWidth, preludeImage?.height ?? 0, blockSpec.chrome);
  const chromeHeight = getStoryChromeHeight(chrome);
  const jumpReserveHeight = getStoryJumpReserveHeight(chrome);
  const rowHeight = getFrontArticleRowHeight(placement, config);
  const baseBodySlotHeight = Math.max(getMinimumTextFrameHeight(config), snapDownToRhythm(rowHeight - chromeHeight - jumpReserveHeight, config.rhythm));
  const imageWrap = !preludeImage && storyRole === "feature" ? getLeadImageWrap(item, blockWidth, config) : null;
  let bodySlotHeight = imageWrap
    ? Math.max(baseBodySlotHeight, reserveRhythmRows(imageWrap.height, config.rhythm))
    : baseBodySlotHeight;
  const textLimit = getFrontTeaserTextLimit(blockSpec, config);
  if (textLimit?.mode === "bodyDepth") {
    bodySlotHeight = Math.max(bodySlotHeight, textLimit.height);
  }
  const startCursor = { ...flow.currentCursor };
  const text = getPrepared(item, config.bodyFont);
  let maxHeight = getFrontTeaserMeasureHeight(textLimit, bodySlotHeight);
  let result = layoutTextLines({
    prepared: text,
    cursor: startCursor,
    maxHeight,
    maxWidth: blockWidth,
    lineHeight: config.lineHeight,
    linePaintHeight: config.linePaintHeight,
    fontSize: config.bodyFontSize,
    fontFamily: SERIF_TEXT_FONT,
    obstacles: imageWrap ? [imageWrap] : [],
  });
  while (shouldGrowFrontArticleToContent(blockSpec) && result.hasMore) {
    bodySlotHeight = reserveRhythmRows(bodySlotHeight + config.rhythm.rowHeight, config.rhythm);
    maxHeight = bodySlotHeight;
    result = layoutTextLines({
      prepared: text,
      cursor: startCursor,
      maxHeight,
      maxWidth: blockWidth,
      lineHeight: config.lineHeight,
      linePaintHeight: config.linePaintHeight,
      fontSize: config.bodyFontSize,
      fontFamily: SERIF_TEXT_FONT,
      obstacles: imageWrap ? [imageWrap] : [],
    });
  }
  const requiredBlockHeight = Math.max(rowHeight, reserveRhythmRows(chromeHeight + bodySlotHeight + jumpReserveHeight, config.rhythm));
  const blockHeight = options.enforcePlacementHeight ? rowHeight : requiredBlockHeight;
  const range = createTextRange({
    flow,
    pageId: pageIdFor(pageNumber),
    blockId: blockSpec.id,
    startCursor,
    endCursor: result.cursor,
    exhausted: !result.hasMore,
  });
  const furniture = [preludeImage, imageWrap ? leadImageToFurniture(item, imageWrap, config) : null].filter(
    (furniture): furniture is SolvedImageFurniture => furniture !== null,
  );
  commitTextRange(flow, range);
  commitUsedImageFurniture(flow, furniture);

  return {
    id: blockSpec.id,
    type: "articleFrame",
    presetId: blockSpec.presetId,
    headlineScale,
    editorialPriority: blockSpec.editorialPriority,
    item,
    article: item,
    pageNumber,
    jumpTargetPage: result.hasMore ? blockSpec.cutPolicy?.jumpTargetPage : undefined,
    jumpLabel:
      result.hasMore && blockSpec.cutPolicy?.jumpTargetPage
        ? formatContinuationJumpLabel(item, blockSpec.cutPolicy.jumpTargetPage)
        : undefined,
    label: item.section,
    title: item.headline,
    deck: item.deck,
    byline: item.byline,
    dateline: item.dateline,
    section: item.section,
    x: 0,
    y: 0,
    width: blockWidth,
    height: blockHeight,
    span,
    columnCount: 1,
    columns: [result.lines],
    furniture,
    textRange: range,
    hasMore: result.hasMore,
    front: {
      rowHeight: blockHeight,
      bodySlotHeight,
      chromeHeight,
      jumpReserveHeight,
      chrome,
      gridPlacement: placement.gridPlacement,
    },
    bodyHeight: bodySlotHeight,
  };
}

function solveComposedFrontArticleFrame(
  placement: FrontArticlePlacement,
  item: ArticlePublicationItem,
  flow: ArticleFlow,
  config: LayoutConfig,
  pageNumber: number,
  span: number,
  blockWidth: number,
  options: FrontArticleSolveOptions = {},
): SolvedBlock {
  const { block: blockSpec } = placement;
  const storyRole = resolveFrontStoryRole(blockSpec, span, false);
  const headlineScale = resolveHeadlineScale(blockSpec, storyRole);
  const localColumnCount = getLocalColumnCountCandidates(blockSpec.localGrid?.columns, config, blockWidth)[0] ?? 1;
  const localConfig = { ...config, columnCount: localColumnCount, contentWidth: blockWidth };
  const chrome = getStoryChromeMetrics(config, item, storyRole, headlineScale, blockWidth, 0, blockSpec.chrome);

  const rowHeight = getFrontArticleRowHeight(placement, config);
  const jumpReserveHeight = getStoryJumpReserveHeight(chrome);
  const topMediaVariant = resolveTopMediaCompositionVariant(blockSpec, localConfig);
  const compositionMode = getFrontCompositionFlowMode(placement, config, localConfig, topMediaVariant);
  const titleBoxes: SolvedChromeBox[] = [];
  let titleBottom = reserveRhythmRows(chrome.paddingTop + chrome.borderTopHeight, config.rhythm);

  for (const slot of blockSpec.composition?.title ?? []) {
    const variant = resolveCompositionChromeSlotVariant(slot, localConfig, compositionMode, topMediaVariant);
    const box = solveCompositionChromeBox({
      slot,
      item,
      storyRole,
      headlineScale,
      localConfig,
      y: titleBottom,
      globalYOffset: 0,
      chromeOverrides: blockSpec.chrome,
      variant,
    });
    if (!box) continue;
    titleBoxes.push(box.globalBox);
    titleBottom = Math.max(titleBottom, box.localReserveBottom);
  }

  const bodyTop = compositionMode === "offsetBody" ? reserveRhythmRows(titleBottom, config.rhythm) : 0;
  let bodySlotHeight = Math.max(getMinimumTextFrameHeight(config), snapDownToRhythm(rowHeight - bodyTop - jumpReserveHeight, config.rhythm));
  const textLimit = getFrontTeaserTextLimit(blockSpec, config);
  const leadBoxes: SolvedChromeBox[] = [];
  const renderLeadBoxes: SolvedChromeBox[] = [];
  const furniture: SolvedFurniture[] = [];
  const columnBottoms = Array.from({ length: localColumnCount }, () => 0);
  if (compositionMode !== "offsetBody") {
    for (const box of titleBoxes) {
      updateOccupiedColumnBottoms(columnBottoms, box.columnStart, box.columnSpan, box.y + box.height);
    }
  }

  for (const slot of getOrderedCompositionLeadSlots(blockSpec, compositionMode)) {
    const slotVariant = slot.slot === "media"
      ? resolveCompositionMediaSlotVariant(slot.placement, localConfig, compositionMode)
      : resolveCompositionChromeSlotVariant(slot, localConfig, compositionMode, topMediaVariant);
    if (!slotVariant) continue;

    if (slot.slot === "media") {
      const mediaSpec = blockSpec.media[slot.mediaIndex ?? 0];
      const image = createImageFurniture(
        item,
        {
          id: slotVariant.id,
          placement: slot.placement,
          assetRole: mediaSpec?.assetRole,
          columnStart: slotVariant.columnStart,
          columnSpan: slotVariant.columnSpan,
          fallbackPenalty: slotVariant.fallbackPenalty,
        },
        localConfig,
        bodySlotHeight,
        flow.usedImageAssetIds,
      );
      if (!image) {
        if (mediaSpec?.required) throw new Error(`${blockSpec.id} requires media slot ${slot.mediaIndex ?? 0} but no image could be solved`);
        continue;
      }
      const stackTop = getOccupiedColumnBottom(columnBottoms, image.columnStart, image.columnSpan);
      const y = compositionMode === "stackedMedia"
        ? reserveRhythmRows(stackTop, config.rhythm)
        : Math.max(image.y, stackTop);
      const placedImage = { ...image, y };
      furniture.push(placedImage);
      updateOccupiedColumnBottoms(columnBottoms, placedImage.columnStart, placedImage.columnSpan, placedImage.y + placedImage.height);
      continue;
    }

    const stackTop = getOccupiedColumnBottom(columnBottoms, slotVariant.columnStart, slotVariant.columnSpan);
    const box = solveCompositionChromeBox({
      slot,
      item,
      storyRole,
      headlineScale,
      localConfig,
      y: stackTop,
      globalYOffset: bodyTop,
      chromeOverrides: blockSpec.chrome,
      variant: slotVariant,
    });
    if (!box) continue;
    leadBoxes.push(box.localBox);
    renderLeadBoxes.push(box.globalBox);
    updateOccupiedColumnBottoms(columnBottoms, box.localBox.columnStart, box.localBox.columnSpan, box.localReserveBottom);
  }

  const startCursor = { ...flow.currentCursor };
  const textChromeBoxes = compositionMode === "offsetBody" ? leadBoxes : [...titleBoxes, ...leadBoxes];
  const furnitureObstacleOffsetY = compositionMode === "offsetBody" ? -bodyTop : 0;
  const columnCopyBandTops = getColumnCopyBandTops(
    localColumnCount,
    textChromeBoxes,
    furniture,
    furnitureObstacleOffsetY,
    config.rhythm.rowHeight,
    config.rhythm,
  );
  const copyBandTop = Math.max(...columnCopyBandTops, 0);
  if (compositionMode === "stackedMedia" || compositionMode === "titleStackedMedia") {
    bodySlotHeight = Math.max(bodySlotHeight, reserveRhythmRows(copyBandTop + getMinimumTextFrameHeight(config), config.rhythm));
  }
  if (textLimit?.mode === "bodyDepth") {
    bodySlotHeight = Math.max(bodySlotHeight, reserveRhythmRows(copyBandTop + textLimit.height, config.rhythm));
  }
  const maxHeight = getComposedFrontTextMeasureHeight(textLimit, compositionMode, copyBandTop, bodySlotHeight);
  const textResult = layoutTextColumns({
    item,
    cursor: startCursor,
    columnCount: localColumnCount,
    textHeight: maxHeight,
    localConfig,
    furniture,
    furnitureObstacleOffsetY,
    furnitureObstacleMarginBottom: config.rhythm.rowHeight,
    minimumLineStartYByColumn: columnCopyBandTops,
    chromeBoxes: textChromeBoxes,
  });
  const requiredRowHeight = Math.max(rowHeight, reserveRhythmRows(bodyTop + bodySlotHeight + jumpReserveHeight, config.rhythm));
  const solvedRowHeight = options.enforcePlacementHeight ? rowHeight : requiredRowHeight;
  const range = createTextRange({
    flow,
    pageId: pageIdFor(pageNumber),
    blockId: blockSpec.id,
    startCursor,
    endCursor: textResult.cursor,
    exhausted: !textResult.hasMore,
  });
  commitTextRange(flow, range);
  commitUsedImageFurniture(flow, furniture);

  return {
    id: blockSpec.id,
    type: "articleFrame",
    presetId: blockSpec.presetId,
    headlineScale,
    editorialPriority: blockSpec.editorialPriority,
    item,
    article: item,
    pageNumber,
    jumpTargetPage: textResult.hasMore ? blockSpec.cutPolicy?.jumpTargetPage : undefined,
    jumpLabel:
      textResult.hasMore && blockSpec.cutPolicy?.jumpTargetPage
        ? formatContinuationJumpLabel(item, blockSpec.cutPolicy.jumpTargetPage)
        : undefined,
    label: item.section,
    title: item.headline,
    deck: item.deck,
    byline: item.byline,
    dateline: item.dateline,
    section: item.section,
    x: 0,
    y: 0,
    width: blockWidth,
    height: solvedRowHeight,
    span,
    columnCount: localColumnCount,
    columns: textResult.columns,
    chromeBoxes: [...titleBoxes, ...renderLeadBoxes],
    furniture,
    textRange: range,
    hasMore: textResult.hasMore,
    front: {
      rowHeight: solvedRowHeight,
      bodySlotHeight,
      chromeHeight: bodyTop,
      jumpReserveHeight,
      chrome,
      gridPlacement: placement.gridPlacement,
      composition: {
        mode: compositionMode,
        bodyTop,
        bodyHeight: bodySlotHeight,
        columnCount: localColumnCount,
        copyBandTop,
        copyBandTops: columnCopyBandTops,
      },
    },
    bodyHeight: bodySlotHeight,
  };
}

function getFrontCompositionFlowMode(
  placement: FrontArticlePlacement,
  config: LayoutConfig,
  localConfig: LayoutConfig,
  topMediaVariant: PlacementVariant | null,
): FrontCompositionFlowMode {
  if (topMediaVariant && topMediaVariant.placement.vertical === "top" && !hasCompositionSideBesideMedia(localConfig, topMediaVariant)) {
    return "stackedMedia";
  }
  if (
    placement.gridPlacement &&
    placement.gridPlacement.columnSpan === config.columnCount &&
    localConfig.columnCount > 1 &&
    topMediaVariant &&
    topMediaVariant.columnSpan < localConfig.columnCount &&
    topMediaVariant.placement.vertical === "top"
  ) {
    if (localConfig.columnCount <= 3) return "titleStackedMedia";
    return "integrated";
  }
  return "offsetBody";
}

function resolveTopMediaCompositionVariant(blockSpec: ArticleFrameBlockSpec, localConfig: LayoutConfig): PlacementVariant | null {
  const slot = blockSpec.composition?.lead.find((candidate) => (
    candidate.slot === "media" && candidate.placement.vertical === "top"
  ));
  return slot ? resolvePreferredPlacementVariant(slot.placement, localConfig) : null;
}

function resolveCompositionChromeSlotVariant(
  slot: ArticleFrameCompositionSlotSpec,
  localConfig: LayoutConfig,
  compositionMode: FrontCompositionFlowMode,
  topMediaVariant: PlacementVariant | null,
): PlacementVariant | null {
  const variant = resolvePreferredPlacementVariant(slot.placement, localConfig);
  if (!variant || !isTextCompositionSlot(slot.slot)) return variant;
  if (compositionMode === "stackedMedia") return getFullWidthPlacementVariant(variant, localConfig, "stacked");
  if (compositionMode === "titleStackedMedia" && isTitleCompositionSlot(slot.slot)) {
    return getFullWidthPlacementVariant(variant, localConfig, "title-stacked");
  }
  if ((compositionMode !== "integrated" && compositionMode !== "titleStackedMedia") || !topMediaVariant) return variant;
  if (!columnsOverlap(variant.columnStart, variant.columnSpan, topMediaVariant.columnStart, topMediaVariant.columnSpan)) {
    return variant;
  }

  const leftSpan = topMediaVariant.columnStart;
  const rightStart = topMediaVariant.columnStart + topMediaVariant.columnSpan;
  const rightSpan = localConfig.columnCount - rightStart;
  const preferLeft = variant.columnStart <= topMediaVariant.columnStart;
  const side = preferLeft
    ? getAvailableCompositionSide(0, leftSpan, rightStart, rightSpan)
    : getAvailableCompositionSide(rightStart, rightSpan, 0, leftSpan);
  if (!side) return variant;
  return {
    ...variant,
    id: `${variant.id}-beside-media`,
    columnStart: side.columnStart,
    columnSpan: side.columnSpan,
  };
}

function resolveCompositionMediaSlotVariant(
  placement: ResponsivePlacementSpec,
  localConfig: LayoutConfig,
  compositionMode: FrontCompositionFlowMode,
): PlacementVariant | null {
  const variant = resolvePreferredPlacementVariant(placement, localConfig);
  if (!variant) return null;
  return compositionMode === "stackedMedia" ? getFullWidthPlacementVariant(variant, localConfig, "stacked") : variant;
}

function getFullWidthPlacementVariant(variant: PlacementVariant, localConfig: LayoutConfig, suffix: string): PlacementVariant {
  return {
    ...variant,
    id: `${variant.id}-${suffix}`,
    columnStart: 0,
    columnSpan: localConfig.columnCount,
  };
}

function getOrderedCompositionLeadSlots(
  blockSpec: ArticleFrameBlockSpec,
  compositionMode: FrontCompositionFlowMode,
): ArticleFrameCompositionSlotSpec[] {
  const slots = blockSpec.composition?.lead ?? [];
  if (compositionMode !== "stackedMedia") return slots;
  return [
    ...slots.filter((slot) => slot.slot !== "media"),
    ...slots.filter((slot) => slot.slot === "media"),
  ];
}

function hasCompositionSideBesideMedia(localConfig: LayoutConfig, mediaVariant: PlacementVariant): boolean {
  return mediaVariant.columnStart > 0 || mediaVariant.columnStart + mediaVariant.columnSpan < localConfig.columnCount;
}

function isTitleCompositionSlot(slot: SolvedChromeBox["slot"]): boolean {
  return slot === "label" || slot === "headline";
}

function getAvailableCompositionSide(
  primaryStart: number,
  primarySpan: number,
  fallbackStart: number,
  fallbackSpan: number,
): { columnStart: number; columnSpan: number } | null {
  if (primarySpan > 0) return { columnStart: primaryStart, columnSpan: primarySpan };
  if (fallbackSpan > 0) return { columnStart: fallbackStart, columnSpan: fallbackSpan };
  return null;
}

function columnsOverlap(firstStart: number, firstSpan: number, secondStart: number, secondSpan: number): boolean {
  return firstStart < secondStart + secondSpan && secondStart < firstStart + firstSpan;
}

export function getFrontGridHeight(targetPageHeight: number, narrow: boolean, medium: boolean): number {
  const mastheadAllowance = narrow ? 190 : medium ? 230 : 270;
  const bottomPadding = narrow ? 18 : 30;
  return Math.max(420, targetPageHeight - mastheadAllowance - bottomPadding);
}

export function getFrontRows(columnCount: number, rowGap: number, gridHeight: number, rowMaxHeight: number, rhythm: VerticalRhythm): FrontRow[] {
  if (columnCount === 1) {
    const rowHeight = snapDownToRhythm((gridHeight - rowGap * 5) / 6, rhythm);
    return Array.from({ length: 6 }, (_, index) => ({
      startIndex: index,
      endIndex: index,
      height: clampRhythmHeight(rowHeight, 360, rowMaxHeight, rhythm),
    }));
  }
  const first = clampRhythmHeight(snapDownToRhythm(gridHeight * 0.52, rhythm), 360, rowMaxHeight, rhythm);
  const second = clampRhythmHeight(gridHeight - first - rowGap, 300, rowMaxHeight, rhythm);
  return [
    { startIndex: 0, endIndex: 2, height: first },
    { startIndex: 3, endIndex: 5, height: second },
  ];
}

function getFrontPageHeight(config: LayoutConfig): number {
  return getFrontPageHeightForRegion(
    config,
    config.pageChrome.pagePaddingTop + config.pageChrome.mastheadHeight + config.pageChrome.frontGridMarginTop,
    getFrontPageGridHeight(config),
  );
}

function getFrontPageHeightForRegion(config: LayoutConfig, regionY: number, regionHeight: number, frontFooter?: SolvedFrontFooter): number {
  return reserveRhythmRows(
    regionY +
      regionHeight +
      (frontFooter ? frontFooter.marginTop + frontFooter.height : 0) +
      config.pageChrome.pagePaddingBottom,
    config.rhythm,
  );
}

function getFrontPageGridHeight(config: LayoutConfig): number {
  if (config.frontRows.length === 0) return 0;
  return getFrontPageGridHeightFromRowHeights(config.frontRows.map((row) => row.height), config.rowGap);
}

function getFrontPageGridHeightFromRowHeights(rowHeights: number[], rowGap: number): number {
  return rowHeights.reduce((total, height) => total + height, 0) + rowGap * Math.max(0, rowHeights.length - 1);
}

function getFrontRowHeight(config: LayoutConfig, articleIndex: number): number {
  return config.frontRows.find((row) => articleIndex >= row.startIndex && articleIndex <= row.endIndex)?.height ?? reserveRhythmRows(420, config.rhythm);
}

function getFrontArticleRowHeight(placement: FrontArticlePlacement, config: LayoutConfig): number {
  const baseHeight = placement.rowHeight ?? getFrontRowHeight(config, placement.solveIndex);
  const requestedRows = placement.block.size?.defaultRows;
  if (!requestedRows) return baseHeight;
  return Math.max(baseHeight, reserveRhythmRows(requestedRows * config.rhythm.rowHeight, config.rhythm));
}

function shouldGrowFrontArticleToContent(blockSpec: ArticleFrameBlockSpec): boolean {
  return !blockSpec.cutPolicy?.bodyDepthRows && !blockSpec.cutPolicy?.maxBodyLines && !blockSpec.cutPolicy?.jumpTargetPage;
}

function getFrontTeaserTextLimit(
  blockSpec: ArticleFrameBlockSpec,
  config: LayoutConfig,
): { mode: "bodyDepth" | "lineCount"; height: number } | null {
  if (blockSpec.cutPolicy?.bodyDepthRows) {
    return {
      mode: "bodyDepth",
      height: getLineLimitHeight(blockSpec.cutPolicy.bodyDepthRows, config.lineHeight, config.linePaintHeight, config.rhythm),
    };
  }
  if (blockSpec.cutPolicy?.maxBodyLines) {
    return {
      mode: "lineCount",
      height: getLineLimitHeight(blockSpec.cutPolicy.maxBodyLines, config.lineHeight, config.linePaintHeight, config.rhythm),
    };
  }
  return null;
}

function getFrontTeaserMeasureHeight(
  textLimit: { mode: "bodyDepth" | "lineCount"; height: number } | null,
  bodySlotHeight: number,
): number {
  if (!textLimit || textLimit.mode === "bodyDepth") return bodySlotHeight;
  return Math.min(bodySlotHeight, textLimit.height);
}

function getComposedFrontTextMeasureHeight(
  textLimit: { mode: "bodyDepth" | "lineCount"; height: number } | null,
  compositionMode: FrontCompositionFlowMode,
  copyBandTop: number,
  bodySlotHeight: number,
): number {
  if (!textLimit || textLimit.mode === "bodyDepth") return bodySlotHeight;
  const lineLimitHeight = compositionMode === "stackedMedia" || compositionMode === "titleStackedMedia"
    ? copyBandTop + textLimit.height
    : textLimit.height;
  return Math.min(bodySlotHeight, lineLimitHeight);
}

function getOccupiedColumnBottom(bottoms: number[], columnStart: number, columnSpan: number): number {
  return Math.max(...bottoms.slice(columnStart, columnStart + columnSpan), 0);
}

function getColumnCopyBandTops(
  columnCount: number,
  chromeBoxes: SolvedChromeBox[],
  furniture: SolvedFurniture[],
  furnitureOffsetY: number,
  furnitureMarginBottom: number,
  rhythm: VerticalRhythm,
): number[] {
  const minimums = Array.from({ length: columnCount }, () => 0);

  for (const box of chromeBoxes) {
    updateOccupiedColumnBottoms(minimums, box.columnStart, box.columnSpan, box.y + box.height);
  }

  for (const item of furniture) {
    if (!item.wrapsText) continue;
    updateOccupiedColumnBottoms(
      minimums,
      item.columnStart,
      item.columnSpan,
      item.y + furnitureOffsetY + item.height + furnitureMarginBottom,
    );
  }

  return minimums.map((minimum) => reserveRhythmRows(Math.max(0, minimum), rhythm));
}

function updateOccupiedColumnBottoms(bottoms: number[], columnStart: number, columnSpan: number, bottom: number): void {
  for (let index = columnStart; index < Math.min(bottoms.length, columnStart + columnSpan); index += 1) {
    bottoms[index] = Math.max(bottoms[index], bottom);
  }
}

function getLeadImageWrap(article: ArticlePublicationItem, width: number, config: LayoutConfig): TextObstacle | null {
  if (!article.image) return null;
  const layout = article.image.layout;
  const minHeight = layout?.minHeight ?? config.lineHeight * 6;
  const maxHeight = layout?.maxHeight ?? config.lineHeight * 12;
  const targetWidth = getInlineFloatWidth(layout, width, config);
  const imageWidth = clamp(
    Math.round(targetWidth),
    Math.min(layout?.inlineFloat?.minWidth ?? 72, Math.round(width * 0.24)),
    Math.round(width * (layout?.inlineFloat?.maxWidthRatio ?? 0.42)),
  );
  const naturalHeight = layout?.crop === "contain"
    ? Math.round(imageWidth / getImageAspectRatio(article.image))
    : Math.round(layout?.preferredHeight ?? config.lineHeight * 8);
  const height = layout?.crop === "contain"
    ? snapPreservedImageHeightToRhythm(naturalHeight, config.rhythm, minHeight, maxHeight)
    : snapPreferredHeightToRhythm(naturalHeight, config.rhythm, minHeight, maxHeight);
  return {
    x: Math.round(width - imageWidth),
    y: 0,
    width: imageWidth,
    height,
  };
}

function getInlineFloatWidth(
  layout: NonNullable<ArticlePublicationItem["image"]>["layout"],
  width: number,
  config: LayoutConfig,
): number {
  const intent = layout?.inlineFloat;
  if (
    intent &&
    config.columnCount >= (intent.minColumnCount ?? 2) &&
    (intent.columnSpan ?? 0) > 0
  ) {
    return getSpanWidth(config, intent.columnSpan ?? 1);
  }
  const ratio = config.columnCount === 1
    ? intent?.narrowWidthRatio ?? 0.34
    : intent?.widthRatio ?? 0.42;
  return width * ratio;
}

function createFrontPreludeImage(
  article: ArticlePublicationItem,
  blockSpec: ArticleFrameBlockSpec,
  width: number,
  config: LayoutConfig,
  usedImageAssetIds: ReadonlySet<string> = new Set(),
): SolvedImageFurniture | null {
  const mediaSpec = blockSpec.media[0];
  if (!mediaSpec) return null;
  const asset = getPreferredImage(article, mediaSpec.placement, mediaSpec.assetRole, usedImageAssetIds);
  if (!asset) return null;
  const aspectRatio = getImageAspectRatio(asset);
  const layout = asset.layout;
  const canCropFrame = mediaSpec.placement.crop === "cropAllowed";
  const shouldCropToFill = canCropFrame || layout?.crop === "cover";
  const minHeight = canCropFrame ? layout?.minHeight ?? 140 : config.rhythm.rowHeight;
  const maxHeight = canCropFrame ? layout?.maxHeight ?? 320 : Number.POSITIVE_INFINITY;
  const naturalHeight = Math.round(width / aspectRatio);
  const imageHeight = canCropFrame
    ? snapPreferredHeightToRhythm(naturalHeight, config.rhythm, minHeight, maxHeight)
    : snapPreservedImageHeightToRhythm(naturalHeight, config.rhythm, minHeight, maxHeight);
  const caption = getImageCaption(asset);
  const captionHeight = getImageCaptionHeight(caption, width, config.rhythm);
  const height = imageHeight + captionHeight;
  return {
    kind: "image",
    id: `${article.slug}-front-prelude-photo`,
    assetId: asset.id,
    src: asset.src,
    themeVariants: asset.themeVariants,
    alt: asset.alt,
    caption,
    credit: asset.credit,
    templateId: "front-prelude",
    columnStart: 0,
    columnSpan: 1,
    x: 0,
    y: 0,
    width,
    height,
    imageHeight,
    captionHeight,
    captionFontSize: IMAGE_CAPTION_FONT_SIZE,
    captionLineHeight: config.rhythm.rowHeight,
    aspectRatio,
    objectFit: shouldCropToFill ? "cover" : "contain",
    objectPosition: getObjectPosition(asset),
    wrapsText: false,
    preferredHeight: naturalHeight + captionHeight,
  };
}

function leadImageToFurniture(article: ArticlePublicationItem, obstacle: TextObstacle, config: LayoutConfig): SolvedImageFurniture {
  if (!article.image) throw new Error(`Cannot create lead image furniture for ${article.slug} without an image.`);
  const [asset] = getPublicationItemImageAssets(article);
  const aspectRatio = getImageAspectRatio(article.image);
  const caption = getImageCaption(article.image);
  const captionHeight = getImageCaptionHeight(caption, obstacle.width, config.rhythm);
  const preserveImageAspect = article.image.layout?.crop === "contain";
  const naturalHeight = Math.round(obstacle.width / aspectRatio);
  const imageHeight = preserveImageAspect
    ? snapPreservedImageHeightToRhythm(
      naturalHeight,
      config.rhythm,
      article.image.layout?.minHeight ?? config.rhythm.rowHeight,
      article.image.layout?.maxHeight ?? Number.POSITIVE_INFINITY,
    )
    : Math.max(config.rhythm.rowHeight, obstacle.height - captionHeight);
  const height = imageHeight + captionHeight;
  return {
    kind: "image",
    id: `${article.slug}-lead-photo`,
    assetId: asset?.id ?? `${article.slug}-primary-image`,
    src: article.image.src,
    themeVariants: article.image.themeVariants,
    alt: article.image.alt,
    caption,
    credit: article.image.credit,
    templateId: "lead-wrap",
    columnStart: 0,
    columnSpan: 1,
    x: obstacle.x,
    y: obstacle.y,
    width: obstacle.width,
    height,
    imageHeight,
    captionHeight,
    captionFontSize: IMAGE_CAPTION_FONT_SIZE,
    captionLineHeight: config.rhythm.rowHeight,
    aspectRatio,
    objectFit: preserveImageAspect ? "contain" : "cover",
    objectPosition: "50% 50%",
    wrapsText: true,
    preferredHeight: height,
  };
}
