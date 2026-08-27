import type { ArticleImageAsset, ArticleImageThemeVariants } from "./articles";
import {
  type ArticleFrameBlockSpec,
  type ArticleFrameCompositionSlotSpec,
  type ArticleFrameChromeSpec,
  type ChromeTextSlotSpec,
  type EditionLayoutPlan,
  type EditorialPriorityId,
  type FrontResponsiveLayoutOrder,
  type FrontResponsiveLayoutSpec,
  type FrontResponsiveSlotSpec,
  type HeadlineScaleId,
  type LayoutBlockSpec,
  type LayoutMediaSpec,
  type LayoutPageSpec,
  type LayoutPullQuoteSpec,
  type LayoutRegionSpec,
  type ResponsivePlacementAnchor,
  type ResponsivePlacementSpec,
  type ResponsiveSpanPolicy,
  type ResponsiveVerticalPlacement,
} from "./layout-plan";
import {
  type ArticlePublicationItem,
  type PublicationItem,
  getArticlePublicationItems,
  getPublicationItemImageAssets,
  getPublicationItemText,
} from "./publication-items";
import {
  layoutNextLine,
  layoutTextLines,
  prepareWithSegments,
  type LayoutCursor,
  type PreparedTextWithSegments,
  type TextLine,
  type TextObstacle,
} from "./pretext-layout";

export type { TextLine };

export type SolvedTextLine = TextLine;

export type SolvedFurniture = SolvedImageFurniture | SolvedPullQuoteFurniture | SolvedMediaClusterFurniture | SolvedAdFurniture;

export type SolvedImageFurniture = {
  kind: "image";
  id: string;
  assetId: string;
  src: string;
  themeVariants?: ArticleImageThemeVariants;
  alt: string;
  caption: string;
  credit: string;
  templateId: string;
  columnStart: number;
  columnSpan: number;
  x: number;
  y: number;
  width: number;
  height: number;
  imageHeight: number;
  captionHeight: number;
  captionFontSize: number;
  captionLineHeight: number;
  aspectRatio: number;
  objectFit: "contain" | "cover";
  objectPosition: string;
  wrapsText: boolean;
  preferredHeight: number;
};

export type SolvedPullQuoteFurniture = {
  kind: "pullQuote";
  id: string;
  text: string;
  templateId: string;
  columnStart: number;
  columnSpan: number;
  x: number;
  y: number;
  width: number;
  height: number;
  fontSize: number;
  lineHeight: number;
  wrapsText: boolean;
};

export type SolvedMediaClusterFurniture = {
  kind: "mediaCluster";
  id: string;
  templateId: string;
  images: SolvedImageFurniture[];
  caption: string;
  x: number;
  y: number;
  width: number;
  height: number;
  wrapsText: false;
};

export type SolvedAdFurniture = {
  kind: "ad";
  id: string;
  src?: string;
  label: string;
  x: number;
  y: number;
  width: number;
  height: number;
  wrapsText: false;
};

export type SolvedChromeBox = {
  id: string;
  slot: "label" | "headline" | "deck" | "byline";
  text: string;
  columnStart: number;
  columnSpan: number;
  x: number;
  y: number;
  width: number;
  height: number;
  fontSize: number;
  lineHeight: number;
  paintBuffer: number;
  paddingTop?: number;
  paddingBottom?: number;
  ruleTopHeight?: number;
  ruleBottomHeight?: number;
  fontFamily: "serif" | "sans";
  fontWeight?: number | string;
  fontStyle?: "normal" | "italic";
  textTransform?: "uppercase";
};

export type SolvedBlock = {
  id: string;
  type: LayoutBlockSpec["type"];
  presetId?: string;
  headlineScale?: HeadlineScaleId;
  editorialPriority?: EditorialPriorityId;
  item?: PublicationItem;
  items?: PublicationItem[];
  article?: ArticlePublicationItem;
  pageNumber: number;
  jumpTargetPage?: number;
  jumpLabel?: string;
  label?: string;
  title?: string;
  deck?: string;
  byline?: string;
  dateline?: string;
  section?: string;
  x: number;
  y: number;
  width: number;
  height: number;
  span: number;
  columnCount: number;
  columns: TextLine[][];
  chromeBoxes?: SolvedChromeBox[];
  furniture: SolvedFurniture[];
  textRange?: PlacedTextRange;
  hasMore?: boolean;
  front?: SolvedFrontStoryMetrics;
  titleChrome?: ContinuationTitleMetrics;
  titleHeight?: number;
  bodyHeight?: number;
  furnitureSufficiency?: FurnitureSufficiencyReport;
};

export type SolvedFrontStoryMetrics = {
  rowHeight: number;
  bodySlotHeight: number;
  chromeHeight: number;
  jumpReserveHeight: number;
  chrome: StoryChromeMetrics;
  gridPlacement?: SolvedFrontGridPlacement;
  composition?: {
    mode: FrontCompositionFlowMode;
    bodyTop: number;
    bodyHeight: number;
    columnCount: number;
    copyBandTop: number;
    copyBandTops: number[];
  };
};

export type SolvedFrontGridPlacement = {
  columnStart: number;
  columnSpan: number;
  rowStart: number;
  rowSpan: number;
};

export type SolvedRegion = {
  id: string;
  type: LayoutRegionSpec["type"];
  role?: string;
  x: number;
  y: number;
  width: number;
  height: number;
  rowHeights?: number[];
  columnCount: number;
  blocks: SolvedBlock[];
};

export type SolvedFrontFooterEntry = {
  section: string;
  articleSlug: string;
  articleTitle: string;
  blockId: string;
  pageNumber: number;
};

export type SolvedFrontFooterUtilityEntry =
  | {
      id: "archive";
      label: string;
      href: string;
      disabled: false;
    }
  | {
      id: "newsDesk";
      label: string;
      href: string;
      disabled: false;
    }
  | {
      id: "settings";
      label: string;
      href: string;
      disabled: false;
    }
  | {
      id: "login";
      label: string;
      disabled: true;
    };

export type SolvedFrontFooter = {
  rowHeight: number;
  marginTop: number;
  height: number;
  sectionRows: number;
  sectionColumns: number;
  entries: SolvedFrontFooterEntry[];
  utilityEntries: SolvedFrontFooterUtilityEntry[];
};

export type SolvedPage = {
  id: string;
  pageNumber: number;
  presetId: LayoutPageSpec["presetId"];
  kind: string;
  height: number;
  columnCount: number;
  regions: SolvedRegion[];
  frontFooter?: SolvedFrontFooter;
};

export type NewspaperLayout = {
  columnCount: number;
  contentWidth: number;
  gap: number;
  rowGap: number;
  rhythm: VerticalRhythm;
  pageHeight: number;
  frontPageHeight: number;
  pageHeights: Record<number, number>;
  pageChrome: PageChromeMetrics;
  pages: SolvedPage[];
  textRanges: PlacedTextRange[];
};

export type VerticalRhythm = {
  rowHeight: number;
  paintHeight: number;
  paintBuffer: number;
};

export type PageChromeMetrics = {
  pagePaddingTop: number;
  pagePaddingX: number;
  pagePaddingBottom: number;
  mastheadHeight: number;
  mastheadKickerLineHeight: number;
  mastheadTitleFontSize: number;
  mastheadTitleLineHeight: number;
  mastheadTitleMarginTop: number;
  mastheadTitleMarginBottom: number;
  mastheadTitleOpticalShift: number;
  mastheadMetaLineHeight: number;
  mastheadMetaGap: number;
  mastheadMetaPaddingTop: number;
  frontGridMarginTop: number;
  insideHeaderHeight: number;
  continuedTitleHeight: number;
  continuedTitleChromeHeight: number;
  continuedTitleFontSize: number;
  continuedTitleLineHeight: number;
  continuationSectionSeparatorHeight: number;
};

export type ChromeTextBoxMetrics = {
  fontSize: number;
  lineHeight: number;
  paintHeight: number;
  paintBuffer: number;
  contentHeight: number;
  paddingTop: number;
  paddingBottom: number;
  ruleTopHeight: number;
  ruleBottomHeight: number;
  height: number;
  lineCount: number;
  marginBefore: number;
  marginAfter: number;
  totalHeight: number;
};

export type StoryChromeMetrics = {
  borderTopHeight: number;
  paddingTop: number;
  mediaPreludeHeight: number;
  mediaPreludeMarginBottom: number;
  labelFontSize: number;
  labelLineHeight: number;
  labelPaintHeight: number;
  labelPaintBuffer: number;
  labelHeight: number;
  headlineFontSize: number;
  headlineLineHeight: number;
  headlinePaintHeight: number;
  headlinePaintBuffer: number;
  headlineHeight: number;
  headlineLineCount: number;
  headlineMarginTop: number;
  headlineMarginBottom: number;
  deckFontSize: number;
  deckLineHeight: number;
  deckPaintHeight: number;
  deckPaintBuffer: number;
  deckPaddingTop: number;
  deckPaddingBottom: number;
  deckRuleTopHeight: number;
  deckRuleBottomHeight: number;
  deckHeight: number;
  deckLineCount: number;
  deckMarginBottom: number;
  bylineFontSize: number;
  bylineLineHeight: number;
  bylinePaintHeight: number;
  bylinePaintBuffer: number;
  bylinePaddingTop: number;
  bylinePaddingBottom: number;
  bylineHeight: number;
  bylineLineCount: number;
  bylineMarginBottom: number;
  measureChromeHeight: number;
  jumpFontSize: number;
  jumpLineHeight: number;
  jumpPaintHeight: number;
  jumpPaintBuffer: number;
  jumpHeight: number;
  jumpPaddingTop: number;
  jumpPaddingBottom: number;
  jumpBorderTopHeight: number;
};

export type ContinuationTitleMetrics = {
  label: ChromeTextBoxMetrics;
  heading: ChromeTextBoxMetrics;
  chromeHeight: number;
  totalHeight: number;
};

type FrontStoryRole = "feature" | "rail" | "standard";

type ChromeTextStyle = {
  fontSize: number;
  fontFamily: string;
  fontWeight?: number | string;
  fontStyle?: "normal" | "italic";
  lineHeightEm: number;
  paintHeightEm: number;
  marginBeforeEm?: number;
  marginAfterEm?: number;
  minHeightEm?: number;
};

type ChromeBoxTreatment = {
  paddingTop: number;
  paddingBottom: number;
  ruleTopHeight?: number;
  ruleBottomHeight?: number;
};

export type PlacedTextRange = {
  articleId: string;
  pageId: string;
  blockId: string;
  startCursor: LayoutCursor;
  endCursor: LayoutCursor;
  exhausted: boolean;
};

export type ArticleFlow = {
  article: ArticlePublicationItem;
  currentCursor: LayoutCursor;
  placedRanges: PlacedTextRange[];
  usedImageAssetIds: Set<string>;
};

type LayoutConfig = {
  columnCount: number;
  contentWidth: number;
  gap: number;
  rowGap: number;
  rhythm: VerticalRhythm;
  pageChrome: PageChromeMetrics;
  lineHeight: number;
  linePaintHeight: number;
  bodyFontSize: number;
  bodyFont: string;
  frontRows: FrontRow[];
  continuationHeight: number;
};

type FrontRow = {
  startIndex: number;
  endIndex: number;
  height: number;
};

type FrontArticlePlacement = {
  block: ArticleFrameBlockSpec;
  originalIndex: number;
  solveIndex: number;
  gridPlacement?: SolvedFrontGridPlacement;
  rowHeight?: number;
};

type FrontArticleSolveOptions = {
  enforcePlacementHeight?: boolean;
};

type FrontCompositionFlowMode = "offsetBody" | "integrated" | "titleStackedMedia" | "stackedMedia";

type PreparedTextCache = Map<string, PreparedTextWithSegments>;

type ArticleFrameCandidate = {
  block: SolvedBlock;
  range: PlacedTextRange;
  score: number;
  whitespace: number;
  furnitureSufficiency?: FurnitureSufficiencyReport;
};

export type FurnitureSufficiencyReport = {
  accepted: boolean;
  reason?: string;
  visibleRows: number;
  furnitureRows: number;
};

type MediaVariant = {
  id: string;
  placement: ResponsivePlacementSpec | null;
  assetRole?: string;
  columnStart: number;
  columnSpan: number;
  fallbackPenalty: number;
};

type PlacementVariant = {
  id: string;
  placement: ResponsivePlacementSpec;
  columnStart: number;
  columnSpan: number;
  fallbackPenalty: number;
};

type PullQuoteVariant = {
  id: string;
  placement: ResponsivePlacementSpec | null;
  columnStart: number;
  columnSpan: number;
  fallbackPenalty: number;
};

const EMPTY_CURSOR: LayoutCursor = { segmentIndex: 0, graphemeIndex: 0 };
const SERIF_TEXT_FONT = 'Georgia, "Times New Roman", serif';
const SANS_TEXT_FONT = "Arial, Helvetica, sans-serif";
const IMAGE_CAPTION_FONT_SIZE = 12;
const IMAGE_CAPTION_HORIZONTAL_PADDING_EM = 0.3;
const MASTHEAD_TITLE_GLYPH_HEIGHT_RATIO = 0.736;
const MASTHEAD_RULE_HEIGHT = 0;
const MASTHEAD_RULE_MARGIN_BOTTOM = 0;
const MASTHEAD_TITLE_MARGIN_TOP = 0;
const MASTHEAD_PADDING_BOTTOM = 0;
const MASTHEAD_BORDER_BOTTOM = 0;
const MASTHEAD_MARGIN_BOTTOM = 0;
const MASTHEAD_META_BORDER_TOP = 0;
const MASTHEAD_META_PADDING_TOP = 0;
const MASTHEAD_META_PADDING_BOTTOM = 0;
const MASTHEAD_META_BORDER_BOTTOM = 0;
const INSIDE_HEADER_PADDING_BOTTOM = 8;
const INSIDE_HEADER_BORDER_BOTTOM = 2;
const INSIDE_HEADER_MARGIN_BOTTOM = 14;
const CONTINUED_TITLE_KICKER_LINE_HEIGHT = 14;
const CONTINUED_TITLE_HEADING_MARGIN_TOP = 5;
const CONTINUED_TITLE_PADDING_BOTTOM = 0;
const CONTINUED_TITLE_BORDER_BOTTOM = 0;
const CONTINUED_TITLE_MARGIN_BOTTOM = 0;
const FURNITURE_COLLISION_GUTTER = 14;
const PULL_QUOTE_VERTICAL_PADDING = 24;
const KICKER_BASE_FONT_SIZE = 11.5;
const KICKER_BASE_ROW_HEIGHT = 19;

function getKickerFontSize(rhythmRowHeight: number): number {
  return Math.round((KICKER_BASE_FONT_SIZE * rhythmRowHeight / KICKER_BASE_ROW_HEIGHT) * 10) / 10;
}

function createVerticalRhythm(rowHeight: number): VerticalRhythm {
  const paintHeight = rowHeight + 4;
  return {
    rowHeight,
    paintHeight,
    paintBuffer: paintHeight - rowHeight,
  };
}

function snapUpToRhythm(value: number, rhythm: VerticalRhythm): number {
  if (value <= 0) return 0;
  return Math.ceil(value / rhythm.rowHeight) * rhythm.rowHeight;
}

function snapDownToRhythm(value: number, rhythm: VerticalRhythm): number {
  if (value <= 0) return 0;
  return Math.floor(value / rhythm.rowHeight) * rhythm.rowHeight;
}

function snapToNearestRhythm(value: number, rhythm: VerticalRhythm): number {
  if (value <= 0) return 0;
  return Math.round(value / rhythm.rowHeight) * rhythm.rowHeight;
}

function reserveRhythmRows(value: number, rhythm: VerticalRhythm): number {
  return snapUpToRhythm(value, rhythm);
}

function clampRhythmHeight(value: number, minimum: number, maximum: number, rhythm: VerticalRhythm): number {
  const snappedMinimum = reserveRhythmRows(minimum, rhythm);
  const snappedMaximum = Math.max(snappedMinimum, snapDownToRhythm(maximum, rhythm));
  return clamp(reserveRhythmRows(value, rhythm), snappedMinimum, snappedMaximum);
}

function snapPreferredHeightToRhythm(value: number, rhythm: VerticalRhythm, minimum = rhythm.rowHeight, maximum = Number.POSITIVE_INFINITY): number {
  const snappedMinimum = reserveRhythmRows(minimum, rhythm);
  const snappedMaximum = Number.isFinite(maximum) ? Math.max(snappedMinimum, snapDownToRhythm(maximum, rhythm)) : Number.POSITIVE_INFINITY;
  const down = snapDownToRhythm(value, rhythm);
  const up = reserveRhythmRows(value, rhythm);
  const candidates = [down, up].filter((candidate) => candidate >= snappedMinimum && candidate <= snappedMaximum);
  if (candidates.length === 0) return snappedMinimum;
  return candidates.sort((left, right) => Math.abs(left - value) - Math.abs(right - value) || left - right)[0];
}

function snapPreservedImageHeightToRhythm(value: number, rhythm: VerticalRhythm, minimum = rhythm.rowHeight, maximum = Number.POSITIVE_INFINITY): number {
  const snappedMinimum = reserveRhythmRows(minimum, rhythm);
  const snappedMaximum = Number.isFinite(maximum) ? Math.max(snappedMinimum, snapDownToRhythm(maximum, rhythm)) : Number.POSITIVE_INFINITY;
  return clamp(reserveRhythmRows(value, rhythm), snappedMinimum, snappedMaximum);
}

function getMinimumTextFrameHeight(config: LayoutConfig): number {
  return reserveRhythmRows(config.linePaintHeight, config.rhythm);
}

export function buildNewspaperLayout(
  items: PublicationItem[],
  pageWidth: number,
  viewportHeight: number,
  layoutPlan: EditionLayoutPlan,
): NewspaperLayout {
  const config = getLayoutConfig(pageWidth, viewportHeight);
  const itemsBySlug = new Map(items.map((item) => [item.slug, item]));
  const flows = createArticleFlows(items);
  const prepared: PreparedTextCache = new Map();
  const pages: SolvedPage[] = [];
  const textRanges: PlacedTextRange[] = [];

  for (const pageSpec of layoutPlan.pages) {
    const page = solvePage(pageSpec, itemsBySlug, flows, prepared, config);
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
  prepared: PreparedTextCache,
  config: LayoutConfig,
): SolvedPage {
  if (pageSpec.presetId === "front.mosaic") {
    return solveFrontMosaicPage(pageSpec, itemsBySlug, flows, prepared, config);
  }
  return solveStackedEditorialPage(pageSpec, itemsBySlug, flows, prepared, config);
}

function solveFrontMosaicPage(
  pageSpec: LayoutPageSpec,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  prepared: PreparedTextCache,
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
    solveFrontArticleFrame(placement, itemsBySlug, previewFlows, prepared, config, pageSpec.pageNumber)
  ));
  const rowHeights = getSolvedResponsiveFrontRowHeights(baseRowHeights, provisionalBlocks, config);
  const finalPlacements = solvedPlacements.map((placement) => ({
    ...placement,
    rowHeight: getResponsiveFrontPlacementHeight(placement, rowHeights, config.rowGap),
  }));
  const blocks = finalPlacements.map((placement) => (
    solveFrontArticleFrame(placement, itemsBySlug, flows, prepared, config, pageSpec.pageNumber, {
      enforcePlacementHeight: true,
    })
  ));
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
    { id: "archive", label: "Archive", href: "/archive", disabled: false },
    { id: "newsDesk", label: "Newsroom", href: "/newsroom", disabled: false },
    { id: "settings", label: "Settings", href: "/settings", disabled: false },
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
  prepared: PreparedTextCache,
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
    return solveComposedFrontArticleFrame(placement, item, flow, prepared, config, pageNumber, span, blockWidth, options);
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
  const text = getPrepared(prepared, item, config.bodyFont);
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
  prepared: PreparedTextCache,
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
    prepared,
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

function solveStackedEditorialPage(
  pageSpec: LayoutPageSpec,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  prepared: PreparedTextCache,
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
    const region = solveRegion(regionSpec, pageSpec, allocatedHeight, itemsBySlug, flows, prepared, config, currentY);
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
  prepared: PreparedTextCache,
  config: LayoutConfig,
  y: number,
): SolvedRegion {
  const blocks: SolvedBlock[] = [];
  let currentY = 0;

  for (const blockSpec of regionSpec.blocks) {
    const remainingHeight = Math.max(getMinimumTextFrameHeight(config), snapDownToRhythm(allocatedHeight - currentY, config.rhythm));
    const block = solveBlock(blockSpec, pageSpec, remainingHeight, itemsBySlug, flows, prepared, config);
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
  prepared: PreparedTextCache,
  config: LayoutConfig,
): SolvedBlock {
  if (blockSpec.type === "articleFrame") {
    return solveArticleFrameBlock(blockSpec, pageSpec, allocatedHeight, itemsBySlug, flows, prepared, config);
  }
  return solveStaticBlock(blockSpec, pageSpec, allocatedHeight, itemsBySlug, config);
}

function solveArticleFrameBlock(
  blockSpec: ArticleFrameBlockSpec,
  pageSpec: LayoutPageSpec,
  allocatedHeight: number,
  itemsBySlug: Map<string, PublicationItem>,
  flows: Map<string, ArticleFlow>,
  prepared: PreparedTextCache,
  config: LayoutConfig,
): SolvedBlock {
  const item = requireArticleItem(blockSpec.itemId, itemsBySlug);
  const flow = getOrCreateFlow(flows, blockSpec.flowKey ?? blockSpec.itemId, item);
  if (blockSpec.startCursor === "beginning") resetArticleFlow(flow);
  const startCursor = blockSpec.startCursor === "beginning" ? { ...EMPTY_CURSOR } : { ...flow.currentCursor };
  const blockWidth = getBlockWidth(config, blockSpec.span);
  const label = getArticleFrameLabel(blockSpec, item);
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
    prepared,
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
  prepared,
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
  prepared: PreparedTextCache;
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
      for (const textHeight of textHeights) {
        for (const pullQuoteVariant of pullQuoteVariants) {
          const pullQuote = createPullQuoteFurniture(item, pullQuoteVariant, localConfig, textHeight, image, blockSpec.chrome);
          if (blockSpec.pullQuote?.required && !pullQuote) continue;

          const furniture: SolvedFurniture[] = [];
          if (image) furniture.push(image);
          if (pullQuote) furniture.push(pullQuote);
          const textResult = layoutTextColumns({
            item,
            prepared,
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
            50_000 -
            whitespace * 1.1 -
            deadColumns * 8_000 -
            (image ? Math.abs(image.height - image.preferredHeight) * 0.35 : 50_000) -
            (pullQuote ? 0 : 2_800) -
            mediaVariant.fallbackPenalty -
            pullQuoteVariant.fallbackPenalty -
            Math.max(0, config.columnCount - columnCount) * 240;

          candidates.push({
            block: {
              id: blockSpec.id,
              type: "articleFrame",
              presetId: blockSpec.presetId,
              headlineScale,
              item,
              article: item,
              pageNumber: pageSpec.pageNumber,
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

function layoutTextColumns({
  item,
  prepared,
  cursor,
  columnCount,
  textHeight,
  maximumTextHeightByColumn = [],
  localConfig,
  furniture,
  chromeBoxes = [],
  furnitureObstacleOffsetY = 0,
  furnitureObstacleMarginBottom = 0,
  minimumLineStartYByColumn = [],
}: {
  item: ArticlePublicationItem;
  prepared: PreparedTextCache;
  cursor: LayoutCursor;
  columnCount: number;
  textHeight: number;
  maximumTextHeightByColumn?: number[];
  localConfig: LayoutConfig;
  furniture: SolvedFurniture[];
  chromeBoxes?: SolvedChromeBox[];
  furnitureObstacleOffsetY?: number;
  furnitureObstacleMarginBottom?: number;
  minimumLineStartYByColumn?: number[];
}): { columns: TextLine[][]; cursor: LayoutCursor; hasMore: boolean } {
  const columns: TextLine[][] = [];
  const preparedText = getPrepared(prepared, item, localConfig.bodyFont);
  const columnWidth = getSpanWidth(localConfig, 1);
  let current = { ...cursor };
  let hasMore = true;

  for (let columnIndex = 0; columnIndex < columnCount; columnIndex += 1) {
    const result = layoutTextLines({
      prepared: preparedText,
      cursor: current,
      maxHeight: maximumTextHeightByColumn[columnIndex] ?? textHeight,
      maxWidth: columnWidth,
      lineHeight: localConfig.lineHeight,
      linePaintHeight: localConfig.linePaintHeight,
      fontSize: localConfig.bodyFontSize,
      fontFamily: SERIF_TEXT_FONT,
      obstacles: getColumnTextObstacles(
        furniture,
        columnIndex,
        chromeBoxes,
        furnitureObstacleOffsetY,
        furnitureObstacleMarginBottom,
        minimumLineStartYByColumn[columnIndex] ?? 0,
      ),
    });
    columns.push(result.lines);
    current = result.cursor;
    hasMore = result.hasMore;
    if (!hasMore) {
      while (columns.length < columnCount) columns.push([]);
      break;
    }
  }

  return { columns, cursor: current, hasMore };
}

function getMediaVariants(media: LayoutMediaSpec | undefined, config: LayoutConfig): MediaVariant[] {
  if (!media) return [getNoMediaVariant(900)];
  const variants = resolvePlacementVariants(media.placement, config).map((variant) => ({
    ...variant,
    assetRole: media.assetRole,
    fallbackPenalty: variant.fallbackPenalty + Math.abs(variant.columnSpan - media.placement.span.preferred) * 900,
  }));
  if (media.required) return variants;
  return [...variants, getNoMediaVariant(24_000)];
}

function getNoMediaVariant(fallbackPenalty: number): MediaVariant {
  return { id: "none", placement: null, columnStart: 0, columnSpan: 0, fallbackPenalty };
}

function getPullQuoteVariants(
  article: ArticlePublicationItem,
  pullQuote: LayoutPullQuoteSpec | undefined,
  config: LayoutConfig,
): PullQuoteVariant[] {
  const none = { id: "none", placement: null, columnStart: 0, columnSpan: 0, fallbackPenalty: 0 };
  if (!pullQuote || !article.pullQuotes?.[0]) return [none];
  const variants = pullQuote.placements.flatMap((placement, placementIndex) =>
    resolvePlacementVariants(placement, config).map((variant) => ({
      ...variant,
      fallbackPenalty: variant.fallbackPenalty + placementIndex * 100,
    })),
  );
  return pullQuote.required ? variants : [none, ...variants];
}

function resolvePlacementVariants(placement: ResponsivePlacementSpec, config: LayoutConfig): PlacementVariant[] {
  const effectiveSpan = getEffectivePlacementSpanPolicy(placement, config.columnCount);
  const collapsed = config.columnCount < effectiveSpan.min;
  if (collapsed && placement.collapse === "omit") return [];
  const spans = collapsed
    ? [placement.collapse === "fullWidth" ? config.columnCount : 1]
    : getSpanCandidates(effectiveSpan, config.columnCount);
  return spans.flatMap((span, index) => {
    const anchor = collapsed && placement.collapse === "inline" ? "inline" : placement.anchor ?? "left";
    const columnStart = getColumnStartForPlacement(placement, resolveAnchor(anchor), span, config.columnCount, collapsed);
    if (columnStart === null) return [];
    return [{
      id: `${resolveAnchor(anchor)}-span${span}-${placement.vertical}`,
      placement,
      columnStart,
      columnSpan: span,
      fallbackPenalty: index * 120 + (collapsed ? 320 : 0),
    }];
  });
}

function getEffectivePlacementSpanPolicy(
  placement: ResponsivePlacementSpec,
  columnCount: number,
): ResponsiveSpanPolicy {
  const override = placement.spanOverrides?.[String(columnCount)];
  if (!override) return placement.span;
  const clamped = clamp(override, placement.span.min, placement.span.max);
  return { min: clamped, preferred: clamped, max: clamped };
}

function resolvePreferredPlacementVariant(placement: ResponsivePlacementSpec, config: LayoutConfig): PlacementVariant | null {
  return resolvePlacementVariants(placement, config)[0] ?? null;
}

function createImageFurniture(
  article: ArticlePublicationItem,
  variant: MediaVariant,
  config: LayoutConfig,
  textHeight: number,
  usedImageAssetIds: ReadonlySet<string> = new Set(),
): SolvedImageFurniture | null {
  if (!variant.placement || variant.columnSpan === 0) return null;
  const asset = getPreferredImage(article, variant.placement, variant.assetRole, usedImageAssetIds);
  if (!asset) return null;
  const { x, width } = getSpanRect(config, variant.columnStart, variant.columnSpan);
  const aspectRatio = getImageAspectRatio(asset);
  const preferredHeight = Math.round(width / aspectRatio);
  const canCropFrame = variant.placement.crop === "cropAllowed";
  const shouldCropToFill = canCropFrame || asset.layout?.crop === "cover";
  const minHeight = canCropFrame ? asset.layout?.minHeight ?? 140 : config.rhythm.rowHeight;
  const maxHeight = canCropFrame ? asset.layout?.maxHeight ?? 420 : Number.POSITIVE_INFINITY;
  const rawHeight = canCropFrame ? clamp(preferredHeight, minHeight, maxHeight) : preferredHeight;
  const imageHeight = canCropFrame
    ? snapPreferredHeightToRhythm(rawHeight, config.rhythm, minHeight, maxHeight)
    : snapPreservedImageHeightToRhythm(rawHeight, config.rhythm, minHeight, maxHeight);
  const caption = getImageCaption(asset);
  const captionHeight = getImageCaptionHeight(caption, width, config.rhythm);
  const height = imageHeight + captionHeight;
  const y = getFurnitureY(variant.placement.vertical, height, textHeight, config);
  const focalPoint = asset.layout?.focalPoint ?? { x: 0.5, y: 0.5 };
  return {
    kind: "image",
    id: `${article.slug}-${variant.id}-image`,
    assetId: asset.id,
    src: asset.src,
    themeVariants: asset.themeVariants,
    alt: asset.alt,
    caption,
    credit: asset.credit,
    templateId: `image-${variant.id}`,
    columnStart: variant.columnStart,
    columnSpan: variant.columnSpan,
    x,
    y,
    width,
    height,
    imageHeight,
    captionHeight,
    captionFontSize: IMAGE_CAPTION_FONT_SIZE,
    captionLineHeight: config.rhythm.rowHeight,
    aspectRatio,
    objectFit: shouldCropToFill ? "cover" : "contain",
    objectPosition: `${Math.round(focalPoint.x * 100)}% ${Math.round(focalPoint.y * 100)}%`,
    wrapsText: variant.placement.wrapsText,
    preferredHeight: preferredHeight + captionHeight,
  };
}

function createPullQuoteFurniture(
  article: ArticlePublicationItem,
  variant: PullQuoteVariant,
  config: LayoutConfig,
  textHeight: number,
  image: SolvedImageFurniture | null,
  chrome?: ArticleFrameChromeSpec,
): SolvedPullQuoteFurniture | null {
  if (!variant.placement || variant.columnSpan === 0) return null;
  const text = article.pullQuotes?.[0];
  if (!text) return null;
  const { x, width } = getSpanRect(config, variant.columnStart, variant.columnSpan);
  const metrics = getPullQuoteMetrics(text, width, config, chrome?.pullQuote);
  const y = getPullQuoteY({
    x,
    width,
    height: metrics.height,
    textHeight,
    anchorRatio: getVerticalAnchorRatio(variant.placement.vertical),
    image,
    config,
  });
  if (y === null) return null;
  return {
    kind: "pullQuote",
    id: `${article.slug}-${variant.id}-pullquote`,
    text,
    templateId: `pullquote-${variant.id}`,
    columnStart: variant.columnStart,
    columnSpan: variant.columnSpan,
    x,
    y,
    width,
    height: metrics.height,
    fontSize: metrics.fontSize,
    lineHeight: metrics.lineHeight,
    wrapsText: true,
  };
}

function getPreferredImage(
  article: ArticlePublicationItem,
  _placement: ResponsivePlacementSpec,
  assetRole: string | undefined,
  usedImageAssetIds: ReadonlySet<string> = new Set(),
): ArticleImageAsset | null {
  const assets = getPublicationItemImageAssets(article).filter((asset) => !usedImageAssetIds.has(asset.id));
  if (assetRole) {
    const roleAsset = assets.find((asset) => asset.roles?.some((role) => role === assetRole));
    if (roleAsset) return roleAsset;
  }
  return (
    assets.find((asset) => asset.roles?.some((role) => role === "continuationInset")) ??
    assets.find((asset) => asset.roles?.some((role) => role === "continuation")) ??
    assets[0] ??
    null
  );
}

function hasAvailablePreferredImage(
  article: ArticlePublicationItem,
  placement: ResponsivePlacementSpec,
  assetRole: string | undefined,
  usedImageAssetIds: ReadonlySet<string>,
): boolean {
  return getPreferredImage(article, placement, assetRole, usedImageAssetIds) !== null;
}

function chooseBestCandidate(candidates: ArticleFrameCandidate[], blockId: string): ArticleFrameCandidate {
  const best = candidates.reduce<ArticleFrameCandidate | null>(
    (winner, candidate) => (!winner || candidate.score > winner.score ? candidate : winner),
    null,
  );
  if (!best) throw new Error(`No valid articleFrame candidate solved for ${blockId}`);
  return best;
}

function getLocalColumnCountCandidates(
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

function collectPageTextRanges(page: SolvedPage): PlacedTextRange[] {
  return page.regions.flatMap((region) => region.blocks.flatMap((block) => (block.textRange ? [block.textRange] : [])));
}

function createArticleFlows(items: PublicationItem[]): Map<string, ArticleFlow> {
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

function getOrCreateFlow(flows: Map<string, ArticleFlow>, flowKey: string, article: ArticlePublicationItem): ArticleFlow {
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

function resetArticleFlow(flow: ArticleFlow): void {
  flow.currentCursor = { ...EMPTY_CURSOR };
  flow.placedRanges = [];
  flow.usedImageAssetIds.clear();
}

function requireKnownItem(itemId: string, itemsBySlug: Map<string, PublicationItem>): PublicationItem {
  const item = itemsBySlug.get(itemId);
  if (!item) throw new Error(`Layout references missing item ${itemId}`);
  return item;
}

function requireArticleItem(itemId: string, itemsBySlug: Map<string, PublicationItem>): ArticlePublicationItem {
  const item = requireKnownItem(itemId, itemsBySlug);
  if (item.type !== "article") throw new Error(`Layout articleFrame requires article item ${itemId}`);
  return item;
}

function createTextRange({
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

function commitTextRange(flow: ArticleFlow, range: PlacedTextRange): void {
  flow.currentCursor = { ...range.endCursor };
  flow.placedRanges.push(range);
}

function commitUsedImageFurniture(flow: ArticleFlow, furniture: SolvedFurniture[]): void {
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

function pageIdFor(pageNumber: number): string {
  return `page-${pageNumber}`;
}

function getLayoutConfig(pageWidth: number, viewportHeight: number): LayoutConfig {
  const narrow = pageWidth < 560;
  const medium = pageWidth >= 560 && pageWidth < 1040;
  const bodyFontSize = narrow ? 14 : 15;
  const bodyLineHeight = Math.ceil(bodyFontSize * 1.4);
  const rhythm = createVerticalRhythm(bodyLineHeight);
  const gap = narrow ? 14 : 18;
  const rowGap = rhythm.rowHeight;
  const sideMargin = narrow ? 18 : 30;
  const contentWidth = Math.max(280, pageWidth - sideMargin * 2);
  const columnCount = getResponsiveColumnCount(pageWidth, contentWidth, gap);
  const pageChrome = getPageChromeMetrics(pageWidth, narrow, rhythm, columnCount);
  const targetPageHeight = reserveRhythmRows(getTargetPageHeight(pageWidth, viewportHeight), rhythm);
  const frontGridHeight = snapDownToRhythm(getFrontGridHeight(targetPageHeight, narrow, medium), rhythm);
  const frontRowMaxHeight = snapDownToRhythm(narrow ? 520 : medium ? 560 : 620, rhythm);
  const continuationChrome =
    pageChrome.pagePaddingTop +
    pageChrome.insideHeaderHeight +
    pageChrome.continuedTitleHeight +
    pageChrome.pagePaddingBottom;
  const continuationHeight = reserveRhythmRows(Math.max(760, targetPageHeight - continuationChrome), rhythm);

  return {
    columnCount,
    contentWidth,
    gap,
    rowGap,
    rhythm,
    pageChrome,
    lineHeight: rhythm.rowHeight,
    linePaintHeight: rhythm.paintHeight,
    bodyFontSize,
    bodyFont: `${bodyFontSize}px ${SERIF_TEXT_FONT}`,
    frontRows: getFrontRows(columnCount, rowGap, frontGridHeight, frontRowMaxHeight, rhythm),
    continuationHeight,
  };
}

function getResponsiveColumnCount(pageWidth: number, contentWidth: number, gap: number): number {
  if (pageWidth < 560) return 1;
  const minimumColumnWidth = 168;
  for (const columnCount of [6, 5, 4, 3, 2] as const) {
    const columnWidth = (contentWidth - gap * (columnCount - 1)) / columnCount;
    if (columnWidth >= minimumColumnWidth) return columnCount;
  }
  return 1;
}

function getTargetPageHeight(pageWidth: number, viewportHeight: number): number {
  if (pageWidth < 720) return Math.max(3000, viewportHeight * 3.25);
  if (pageWidth < 1040) return Math.max(1900, viewportHeight * 2.1);
  return Math.max(1320, viewportHeight * 1.72);
}

function getMastheadRowPolicy(columnCount: number): { totalRows: number; titleRows: number } {
  if (columnCount <= 1) return { totalRows: 4, titleRows: 2 };
  if (columnCount <= 3) return { totalRows: 5, titleRows: 3 };
  return { totalRows: 6, titleRows: 4 };
}

function getPageChromeMetrics(pageWidth: number, narrow: boolean, rhythm: VerticalRhythm, columnCount: number): PageChromeMetrics {
  const pagePaddingTop = rhythm.rowHeight;
  const pagePaddingX = narrow ? 18 : 30;
  const pagePaddingBottom = reserveRhythmRows(narrow ? 18 : 30, rhythm);
  const mastheadRows = getMastheadRowPolicy(columnCount);
  const mastheadKickerLineHeight = 14;
  const mastheadTitleLineHeight = rhythm.rowHeight * mastheadRows.titleRows;
  const mastheadTitleFontSize = mastheadTitleLineHeight / MASTHEAD_TITLE_GLYPH_HEIGHT_RATIO;
  const mastheadTitleMarginTop = rhythm.rowHeight / 2;
  const mastheadTitleMarginBottom = rhythm.rowHeight / 2;
  const mastheadTitleOpticalShift = -3;
  const mastheadMetaLineHeight = rhythm.rowHeight - MASTHEAD_META_BORDER_TOP - MASTHEAD_META_BORDER_BOTTOM;
  const mastheadMetaGap = narrow ? 5 : 0;
  const mastheadMetaContentHeight = mastheadMetaLineHeight;
  const rawMastheadHeight =
    MASTHEAD_RULE_HEIGHT +
    MASTHEAD_RULE_MARGIN_BOTTOM +
    MASTHEAD_TITLE_MARGIN_TOP +
    mastheadTitleMarginTop +
    mastheadTitleLineHeight +
    mastheadTitleMarginBottom +
    MASTHEAD_META_BORDER_TOP +
    MASTHEAD_META_PADDING_TOP +
    mastheadMetaContentHeight +
    MASTHEAD_META_PADDING_BOTTOM +
    MASTHEAD_META_BORDER_BOTTOM +
    MASTHEAD_PADDING_BOTTOM +
    MASTHEAD_BORDER_BOTTOM +
    MASTHEAD_MARGIN_BOTTOM;
  const mastheadHeight = rhythm.rowHeight * mastheadRows.totalRows;
  const mastheadMetaPaddingTop = MASTHEAD_META_PADDING_TOP + Math.max(0, mastheadHeight - rawMastheadHeight);
  const frontGridMarginTop = rhythm.rowHeight;
  const insideHeaderHeight = INSIDE_HEADER_PADDING_BOTTOM + INSIDE_HEADER_BORDER_BOTTOM + INSIDE_HEADER_MARGIN_BOTTOM + 18;
  const continuedTitleFontSize = narrow ? clamp(pageWidth * 0.075, 28, 42) : clamp(pageWidth * 0.035, 32, 56);
  const continuedTitleLineHeight = continuedTitleFontSize * 0.94;
  const continuedTitleHeight = Math.ceil(
    CONTINUED_TITLE_KICKER_LINE_HEIGHT +
      CONTINUED_TITLE_HEADING_MARGIN_TOP +
      continuedTitleLineHeight * 2 +
      CONTINUED_TITLE_PADDING_BOTTOM +
      CONTINUED_TITLE_BORDER_BOTTOM +
      CONTINUED_TITLE_MARGIN_BOTTOM,
  );

  return {
    pagePaddingTop,
    pagePaddingX,
    pagePaddingBottom,
    mastheadHeight,
    mastheadKickerLineHeight,
    mastheadTitleFontSize,
    mastheadTitleLineHeight,
    mastheadTitleMarginTop,
    mastheadTitleMarginBottom,
    mastheadTitleOpticalShift,
    mastheadMetaLineHeight,
    mastheadMetaGap,
    mastheadMetaPaddingTop,
    frontGridMarginTop,
    insideHeaderHeight: reserveRhythmRows(insideHeaderHeight, rhythm),
    continuedTitleHeight: reserveRhythmRows(continuedTitleHeight, rhythm),
    continuedTitleChromeHeight: reserveRhythmRows(
      CONTINUED_TITLE_KICKER_LINE_HEIGHT +
      CONTINUED_TITLE_HEADING_MARGIN_TOP +
      CONTINUED_TITLE_PADDING_BOTTOM +
      CONTINUED_TITLE_BORDER_BOTTOM +
      CONTINUED_TITLE_MARGIN_BOTTOM,
      rhythm,
    ),
    continuedTitleFontSize,
    continuedTitleLineHeight,
    continuationSectionSeparatorHeight: rhythm.rowHeight * 2,
  };
}

function getFrontGridHeight(targetPageHeight: number, narrow: boolean, medium: boolean): number {
  const mastheadAllowance = narrow ? 190 : medium ? 230 : 270;
  const bottomPadding = narrow ? 18 : 30;
  return Math.max(420, targetPageHeight - mastheadAllowance - bottomPadding);
}

function getFrontRows(columnCount: number, rowGap: number, gridHeight: number, rowMaxHeight: number, rhythm: VerticalRhythm): FrontRow[] {
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
  return Boolean(
    blockSpec.size?.shrinkToContent &&
      !blockSpec.cutPolicy?.bodyDepthRows &&
      !blockSpec.cutPolicy?.maxBodyLines &&
      !blockSpec.cutPolicy?.jumpTargetPage,
  );
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

function getBlockSpan(config: LayoutConfig, span: ResponsiveSpanPolicy | undefined): number {
  if (config.columnCount === 1) return 1;
  return clamp(span?.preferred ?? config.columnCount, span?.min ?? 1, Math.min(span?.max ?? config.columnCount, config.columnCount));
}

function getBlockWidth(config: LayoutConfig, span: ResponsiveSpanPolicy | undefined): number {
  return getSpanWidth(config, getBlockSpan(config, span));
}

function getSpanWidth(config: LayoutConfig, span: number): number {
  const safeSpan = clamp(span, 1, config.columnCount);
  const singleColumn = (config.contentWidth - config.gap * (config.columnCount - 1)) / config.columnCount;
  return singleColumn * safeSpan + config.gap * (safeSpan - 1);
}

function getSpanRect(config: LayoutConfig, columnStart: number, columnSpan: number): { x: number; width: number } {
  const safeStart = clamp(columnStart, 0, Math.max(0, config.columnCount - 1));
  const safeSpan = clamp(columnSpan, 1, config.columnCount - safeStart);
  const columnWidth = getSpanWidth(config, 1);
  const rawX = safeStart * (columnWidth + config.gap);
  const rawRight = rawX + getSpanWidth(config, safeSpan);
  const x = Math.round(rawX);
  const right = Math.min(Math.round(rawRight), Math.floor(config.contentWidth));
  return { x, width: Math.max(1, right - x) };
}

function solveCompositionChromeBox({
  slot,
  item,
  storyRole,
  headlineScale,
  localConfig,
  y,
  globalYOffset,
  chromeOverrides,
  variant = resolvePreferredPlacementVariant(slot.placement, localConfig),
}: {
  slot: ArticleFrameCompositionSlotSpec;
  item: ArticlePublicationItem;
  storyRole: FrontStoryRole;
  headlineScale: HeadlineScaleId;
  localConfig: LayoutConfig;
  y: number;
  globalYOffset: number;
  chromeOverrides?: ArticleFrameChromeSpec;
  variant?: PlacementVariant | null;
}): { localBox: SolvedChromeBox; globalBox: SolvedChromeBox; localReserveBottom: number } | null {
  if (!variant || !isTextCompositionSlot(slot.slot)) return null;
  const text = getCompositionSlotText(slot.slot, item);
  if (!text) return null;
  const { x, width } = getSpanRect(localConfig, variant.columnStart, variant.columnSpan);
  const style = getCompositionSlotStyle(slot.slot, localConfig, storyRole, headlineScale, width);
  const metrics = solveChromeTextBox(text, width, style, localConfig.rhythm, chromeOverrides?.[slot.slot]);
  const treatedMetrics = applyFrontChromeTreatment(slot.slot, metrics, localConfig, storyRole);
  const boxY = snapUpToRhythm(y + treatedMetrics.marginBefore, localConfig.rhythm);
  const localBox: SolvedChromeBox = {
    id: `${item.slug}-${slot.slot}-${variant.id}`,
    slot: slot.slot,
    text,
    columnStart: variant.columnStart,
    columnSpan: variant.columnSpan,
    x,
    y: boxY,
    width,
    height: treatedMetrics.height,
    fontSize: treatedMetrics.fontSize,
    lineHeight: treatedMetrics.lineHeight,
    paintBuffer: treatedMetrics.paintBuffer,
    paddingTop: treatedMetrics.paddingTop,
    paddingBottom: treatedMetrics.paddingBottom,
    ruleTopHeight: treatedMetrics.ruleTopHeight,
    ruleBottomHeight: treatedMetrics.ruleBottomHeight,
    fontFamily: style.fontFamily === SANS_TEXT_FONT ? "sans" : "serif",
    fontWeight: style.fontWeight,
    fontStyle: style.fontStyle,
    textTransform: slot.slot === "label" || slot.slot === "byline" ? "uppercase" : undefined,
  };
  return {
    localBox,
    globalBox: { ...localBox, y: localBox.y + globalYOffset },
    localReserveBottom: reserveRhythmRows(boxY + treatedMetrics.height + treatedMetrics.marginAfter, localConfig.rhythm),
  };
}

function isTextCompositionSlot(slot: ArticleFrameCompositionSlotSpec["slot"]): slot is SolvedChromeBox["slot"] {
  return slot === "label" || slot === "headline" || slot === "deck" || slot === "byline";
}

function getCompositionSlotText(slot: SolvedChromeBox["slot"], article: ArticlePublicationItem): string {
  if (slot === "label") return article.section;
  if (slot === "headline") return article.headline;
  if (slot === "deck") return article.deck;
  return formatByline(article);
}

function getCompositionSlotStyle(
  slot: SolvedChromeBox["slot"],
  config: LayoutConfig,
  storyRole: FrontStoryRole,
  headlineScale: HeadlineScaleId,
  slotWidth: number,
): ChromeTextStyle {
  if (slot === "label") {
    const labelFontSize = getKickerFontSize(config.rhythm.rowHeight);
    return {
      fontSize: labelFontSize,
      fontFamily: SANS_TEXT_FONT,
      fontWeight: 800,
      lineHeightEm: config.rhythm.rowHeight / labelFontSize,
      paintHeightEm: config.rhythm.rowHeight / labelFontSize,
    };
  }
  if (slot === "headline") {
    const displayHeadline = isDisplayHeadlineScale(headlineScale);
    const fontSize = getHeadlineFontSize(config, headlineScale, slotWidth);
    return {
      fontSize,
      fontFamily: SERIF_TEXT_FONT,
      fontWeight: 900,
      lineHeightEm: displayHeadline ? 0.96 : 1,
      paintHeightEm: displayHeadline ? 1.1 : 1.12,
    };
  }
  if (slot === "deck") {
    const feature = storyRole === "feature";
    const fontSize = config.columnCount === 1 ? 17 : feature ? 19 : 16;
    const lineHeight = feature ? Math.round(fontSize * 1.16) : config.rhythm.rowHeight;
    return {
      fontSize,
      fontFamily: SERIF_TEXT_FONT,
      fontStyle: "italic",
      lineHeightEm: lineHeight / fontSize,
      paintHeightEm: lineHeight / fontSize,
    };
  }
  return {
    fontSize: 12,
    fontFamily: SANS_TEXT_FONT,
    fontWeight: 800,
    lineHeightEm: config.rhythm.rowHeight / 12,
    paintHeightEm: config.rhythm.rowHeight / 12,
  };
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

function applyFrontChromeTreatment(
  slot: SolvedChromeBox["slot"],
  metrics: ChromeTextBoxMetrics,
  config: LayoutConfig,
  storyRole: FrontStoryRole,
): ChromeTextBoxMetrics {
  if (slot === "deck") {
    const padding = Math.round(config.rhythm.rowHeight * (storyRole === "feature" ? 0.48 : 0.34));
    return applyChromeBoxTreatment(metrics, {
      paddingTop: padding,
      paddingBottom: padding,
      ruleTopHeight: 1,
      ruleBottomHeight: 1,
    }, config.rhythm);
  }

  if (slot === "byline") {
    return applyChromeBoxTreatment(metrics, {
      paddingTop: config.rhythm.rowHeight,
      paddingBottom: config.rhythm.rowHeight,
    }, config.rhythm);
  }

  return metrics;
}

function applyChromeBoxTreatment(
  metrics: ChromeTextBoxMetrics,
  treatment: ChromeBoxTreatment,
  rhythm: VerticalRhythm,
): ChromeTextBoxMetrics {
  const ruleTopHeight = treatment.ruleTopHeight ?? 0;
  const ruleBottomHeight = treatment.ruleBottomHeight ?? 0;
  const rawHeight =
    ruleTopHeight +
    treatment.paddingTop +
    metrics.contentHeight +
    treatment.paddingBottom +
    ruleBottomHeight;
  const height = reserveRhythmRows(rawHeight, rhythm);
  const paddingBottom = treatment.paddingBottom + Math.max(0, height - rawHeight);
  const rawTotalHeight = metrics.marginBefore + height + metrics.marginAfter;
  const totalHeight = reserveRhythmRows(rawTotalHeight, rhythm);

  return {
    ...metrics,
    height,
    paddingTop: treatment.paddingTop,
    paddingBottom,
    ruleTopHeight,
    ruleBottomHeight,
    totalHeight,
    marginAfter: metrics.marginAfter + (totalHeight - rawTotalHeight),
  };
}

function getStoryChromeMetrics(
  config: LayoutConfig,
  article: ArticlePublicationItem,
  storyRole: FrontStoryRole,
  headlineScale: HeadlineScaleId,
  blockWidth: number,
  mediaPreludeHeight = 0,
  overrides?: ArticleFrameChromeSpec,
): StoryChromeMetrics {
  const feature = storyRole === "feature";
  const displayHeadline = isDisplayHeadlineScale(headlineScale);
  const headlineFontSize = getHeadlineFontSize(config, headlineScale, blockWidth);
  const labelFontSize = getKickerFontSize(config.rhythm.rowHeight);
  const label = solveChromeTextBox(article.section, blockWidth, {
    fontSize: labelFontSize,
    fontFamily: SANS_TEXT_FONT,
    fontWeight: 800,
    lineHeightEm: config.rhythm.rowHeight / labelFontSize,
    paintHeightEm: config.rhythm.rowHeight / labelFontSize,
  }, config.rhythm, overrides?.label);
  const headline = solveChromeTextBox(article.headline, blockWidth, {
    fontSize: headlineFontSize,
    fontFamily: SERIF_TEXT_FONT,
    fontWeight: 900,
    lineHeightEm: displayHeadline ? 0.96 : 1,
    paintHeightEm: displayHeadline ? 1.1 : 1.12,
  }, config.rhythm, overrides?.headline);
  const deckFontSize = config.columnCount === 1 ? 17 : feature ? 19 : 16;
  const deckLineHeight = feature ? Math.round(deckFontSize * 1.16) : config.rhythm.rowHeight;
  const deck = applyFrontChromeTreatment("deck", solveChromeTextBox(article.deck, blockWidth, {
    fontSize: deckFontSize,
    fontFamily: SERIF_TEXT_FONT,
    fontStyle: "italic",
    lineHeightEm: deckLineHeight / deckFontSize,
    paintHeightEm: deckLineHeight / deckFontSize,
  }, config.rhythm, overrides?.deck), config, storyRole);
  const bylineFontSize = 12;
  const byline = applyFrontChromeTreatment("byline", solveChromeTextBox(formatByline(article), blockWidth, {
    fontSize: bylineFontSize,
    fontFamily: SANS_TEXT_FONT,
    fontWeight: 800,
    lineHeightEm: config.rhythm.rowHeight / bylineFontSize,
    paintHeightEm: config.rhythm.rowHeight / bylineFontSize,
  }, config.rhythm, overrides?.byline), config, storyRole);
  const jump = solveChromeTextBox("SEE MORE", blockWidth, {
    fontSize: 12.2,
    fontFamily: SANS_TEXT_FONT,
    fontWeight: 800,
    lineHeightEm: config.rhythm.rowHeight / 12.2,
    paintHeightEm: config.rhythm.rowHeight / 12.2,
  }, config.rhythm, overrides?.jumpLine);

  return {
    borderTopHeight: 0,
    paddingTop: 0,
    mediaPreludeHeight,
    mediaPreludeMarginBottom: mediaPreludeHeight > 0 ? config.rhythm.rowHeight : 0,
    labelFontSize: label.fontSize,
    labelLineHeight: label.lineHeight,
    labelPaintHeight: label.paintHeight,
    labelPaintBuffer: label.paintBuffer,
    labelHeight: label.height,
    headlineFontSize: headline.fontSize,
    headlineLineHeight: headline.lineHeight,
    headlinePaintHeight: headline.paintHeight,
    headlinePaintBuffer: headline.paintBuffer,
    headlineHeight: headline.height,
    headlineLineCount: headline.lineCount,
    headlineMarginTop: headline.marginBefore,
    headlineMarginBottom: headline.marginAfter,
    deckFontSize: deck.fontSize,
    deckLineHeight: deck.lineHeight,
    deckPaintHeight: deck.paintHeight,
    deckPaintBuffer: deck.paintBuffer,
    deckPaddingTop: deck.paddingTop,
    deckPaddingBottom: deck.paddingBottom,
    deckRuleTopHeight: deck.ruleTopHeight,
    deckRuleBottomHeight: deck.ruleBottomHeight,
    deckHeight: deck.height,
    deckLineCount: deck.lineCount,
    deckMarginBottom: deck.marginAfter,
    bylineFontSize: byline.fontSize,
    bylineLineHeight: byline.lineHeight,
    bylinePaintHeight: byline.paintHeight,
    bylinePaintBuffer: byline.paintBuffer,
    bylinePaddingTop: byline.paddingTop,
    bylinePaddingBottom: byline.paddingBottom,
    bylineHeight: byline.height,
    bylineLineCount: byline.lineCount,
    bylineMarginBottom: byline.marginAfter,
    measureChromeHeight: 0,
    jumpFontSize: jump.fontSize,
    jumpLineHeight: jump.lineHeight,
    jumpPaintHeight: jump.paintHeight,
    jumpPaintBuffer: jump.paintBuffer,
    jumpHeight: jump.height,
    jumpPaddingTop: 0,
    jumpPaddingBottom: config.rhythm.rowHeight,
    jumpBorderTopHeight: 0,
  };
}

function resolveFrontStoryRole(blockSpec: ArticleFrameBlockSpec, span: number, hasFeatureCue: boolean): FrontStoryRole {
  if (blockSpec.role === "feature" || blockSpec.role === "primary") return "feature";
  if (blockSpec.role === "rail") return "rail";
  if (span >= 4 || hasFeatureCue) return "feature";
  return "standard";
}

function resolveHeadlineScale(blockSpec: ArticleFrameBlockSpec, storyRole: FrontStoryRole): HeadlineScaleId {
  if (blockSpec.typography?.headlineScale) return blockSpec.typography.headlineScale;
  if (storyRole === "feature") return "feature";
  if (storyRole === "rail") return "rail";
  return "standard";
}

function isDisplayHeadlineScale(headlineScale: HeadlineScaleId): boolean {
  return headlineScale === "banner" || headlineScale === "feature";
}

function getHeadlineFontSize(config: LayoutConfig, headlineScale: HeadlineScaleId, blockWidth: number): number {
  const width = Math.max(blockWidth, 1);
  if (config.columnCount === 1) {
    if (headlineScale === "banner") return clamp(width * 0.13, 42, 82);
    if (headlineScale === "feature") return clamp(width * 0.11, 34, 54);
    if (headlineScale === "standard") return clamp(width * 0.095, 29, 46);
    if (headlineScale === "rail") return clamp(width * 0.09, 27, 42);
    return clamp(width * 0.075, 22, 32);
  }

  if (headlineScale === "banner") return clamp(width * 0.105, 54, 112);
  if (headlineScale === "feature") return clamp(width * 0.052, 34, 58);
  if (headlineScale === "standard") return clamp(width * 0.07, 27, 40);
  if (headlineScale === "rail") return clamp(width * 0.15, 24, 34);
  return clamp(width * 0.055, 18, 26);
}

function solveChromeTextBox(
  text: string,
  maxWidth: number,
  defaults: ChromeTextStyle,
  rhythm: VerticalRhythm,
  overrides?: ChromeTextSlotSpec,
): ChromeTextBoxMetrics {
  const fontSize = defaults.fontSize;
  const lineHeight = Math.ceil(emToPx(parseEmOverride(overrides?.lineHeight, defaults.lineHeightEm), fontSize));
  const paintHeight = Math.ceil(emToPx(parseEmOverride(overrides?.paintHeight, defaults.paintHeightEm), fontSize));
  const marginBefore = Math.round(emToPx(parseEmOverride(overrides?.marginBefore, defaults.marginBeforeEm ?? 0), fontSize));
  const rawMarginAfter = Math.round(emToPx(parseEmOverride(overrides?.marginAfter, defaults.marginAfterEm ?? 0), fontSize));
  const minHeight = Math.ceil(emToPx(parseEmOverride(overrides?.minHeight, defaults.minHeightEm ?? 0), fontSize));
  const measured = measureWrappedTextBlock(text, buildChromeFont(defaults), maxWidth, lineHeight, paintHeight);
  const height = reserveRhythmRows(Math.max(measured.height, minHeight), rhythm);
  const rawTotalHeight = marginBefore + height + rawMarginAfter;
  const totalHeight = reserveRhythmRows(rawTotalHeight, rhythm);
  const marginAfter = rawMarginAfter + (totalHeight - rawTotalHeight);

  return {
    fontSize,
    lineHeight,
    paintHeight,
    paintBuffer: Math.max(0, paintHeight - lineHeight),
    contentHeight: measured.height,
    paddingTop: 0,
    paddingBottom: 0,
    ruleTopHeight: 0,
    ruleBottomHeight: 0,
    height,
    lineCount: measured.lineCount,
    marginBefore,
    marginAfter,
    totalHeight,
  };
}

function buildChromeFont(style: ChromeTextStyle): string {
  const pieces: string[] = [];
  if (style.fontStyle && style.fontStyle !== "normal") pieces.push(style.fontStyle);
  if (style.fontWeight) pieces.push(String(style.fontWeight));
  pieces.push(`${style.fontSize}px`);
  pieces.push(style.fontFamily);
  return pieces.join(" ");
}

function parseEmOverride(value: ChromeTextSlotSpec[keyof ChromeTextSlotSpec] | undefined, fallback: number): number {
  if (!value) return fallback;
  return parseEmValue(value);
}

function parseEmValue(value: string): number {
  return Number(value.slice(0, -2));
}

function emToPx(value: number, fontSize: number): number {
  return value * fontSize;
}

function getLineStackHeight(lineCount: number, lineHeight: number, paintHeight: number): number {
  if (lineCount <= 0) return 0;
  return Math.ceil((lineCount - 1) * lineHeight + paintHeight);
}

function getStoryChromeHeight(chrome: StoryChromeMetrics): number {
  return (
    chrome.borderTopHeight +
    chrome.paddingTop +
    chrome.mediaPreludeHeight +
    chrome.mediaPreludeMarginBottom +
    chrome.labelHeight +
    chrome.headlineMarginTop +
    chrome.headlineHeight +
    chrome.headlineMarginBottom +
    chrome.deckHeight +
    chrome.deckMarginBottom +
    chrome.bylineHeight +
    chrome.bylineMarginBottom +
    chrome.measureChromeHeight
  );
}

function getStoryJumpReserveHeight(chrome: StoryChromeMetrics): number {
  return chrome.jumpBorderTopHeight + chrome.jumpPaddingTop + chrome.jumpHeight + chrome.jumpPaddingBottom;
}

function getContinuationTitleMetrics(
  config: LayoutConfig,
  article: ArticlePublicationItem,
  blockWidth: number,
  labelText: string,
  headlineScale: HeadlineScaleId,
  explicitHeadlineScale: boolean,
  overrides?: ArticleFrameChromeSpec,
): ContinuationTitleMetrics {
  const labelFontSize = getKickerFontSize(config.rhythm.rowHeight);
  const label = solveChromeTextBox(labelText, blockWidth, {
    fontSize: labelFontSize,
    fontFamily: SANS_TEXT_FONT,
    fontWeight: 800,
    lineHeightEm: config.rhythm.rowHeight / labelFontSize,
    paintHeightEm: config.rhythm.rowHeight / labelFontSize,
  }, config.rhythm, overrides?.label);
  const headingWidth = Math.min(blockWidth, 980);
  const headingFontSize = explicitHeadlineScale
    ? getHeadlineFontSize(config, headlineScale, headingWidth)
    : config.pageChrome.continuedTitleFontSize;
  const headingLineHeight = explicitHeadlineScale
    ? headingFontSize * (isDisplayHeadlineScale(headlineScale) ? 0.94 : 1)
    : config.pageChrome.continuedTitleLineHeight;
  const heading = solveChromeTextBox(article.headline, headingWidth, {
    fontSize: headingFontSize,
    fontFamily: SERIF_TEXT_FONT,
    fontWeight: 900,
    lineHeightEm: headingLineHeight / headingFontSize,
    paintHeightEm: Math.max(1.08, headingLineHeight / headingFontSize),
    marginBeforeEm: CONTINUED_TITLE_HEADING_MARGIN_TOP / headingFontSize,
  }, config.rhythm, overrides?.headline);
  const chromeHeight = reserveRhythmRows(
    label.totalHeight +
      heading.totalHeight +
      CONTINUED_TITLE_PADDING_BOTTOM +
      CONTINUED_TITLE_BORDER_BOTTOM +
      CONTINUED_TITLE_MARGIN_BOTTOM,
    config.rhythm,
  );
  return {
    label,
    heading,
    chromeHeight,
    totalHeight: chromeHeight,
  };
}

function measureWrappedTextBlock(
  text: string,
  font: string,
  maxWidth: number,
  lineHeight: number,
  paintHeight = lineHeight,
): { lineCount: number; height: number } {
  const prepared = prepareWithSegments(text, font);
  let cursor = { ...EMPTY_CURSOR };
  let lineCount = 0;
  while (lineCount < 20) {
    const line = layoutNextLine(prepared, cursor, maxWidth);
    if (!line) break;
    cursor = line.end;
    lineCount += 1;
  }
  return {
    lineCount,
    height: getLineStackHeight(lineCount, lineHeight, paintHeight),
  };
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

function getPrepared(
  cache: PreparedTextCache,
  article: ArticlePublicationItem,
  font: string,
): PreparedTextWithSegments {
  const key = `${article.slug}:${font}`;
  const cached = cache.get(key);
  if (cached) return cached;
  const prepared = prepareWithSegments(getPublicationItemText(article), font, { whiteSpace: "pre-wrap" });
  cache.set(key, prepared);
  return prepared;
}

function getLineLimitHeight(maxLines: number, lineHeight: number, linePaintHeight: number, rhythm: VerticalRhythm): number {
  if (maxLines <= 0) return 0;
  return reserveRhythmRows((maxLines - 1) * lineHeight + linePaintHeight, rhythm);
}

function getColumnTextObstacles(
  furniture: SolvedFurniture[],
  columnIndex: number,
  chromeBoxes: SolvedChromeBox[] = [],
  furnitureOffsetY = 0,
  furnitureMarginBottom = 0,
  minimumLineStartY = 0,
): TextObstacle[] {
  const topObstacle: TextObstacle[] = minimumLineStartY > 0
    ? [{ x: 0, y: 0, width: Number.POSITIVE_INFINITY, height: minimumLineStartY }]
    : [];
  const furnitureObstacles = furniture
    .filter((item) => item.wrapsText && columnIndex >= item.columnStart && columnIndex < item.columnStart + item.columnSpan)
    .map((item) => ({
      x: 0,
      y: item.y + furnitureOffsetY,
      width: Number.POSITIVE_INFINITY,
      height: item.height + getFurnitureObstacleMarginBottom(item, furnitureMarginBottom),
    }));
  const imageClearanceObstacles = furniture
    .filter((item) => (
      item.kind === "image" &&
      item.wrapsText &&
      furnitureMarginBottom > 0 &&
      columnIndex >= item.columnStart &&
      columnIndex < item.columnStart + item.columnSpan
    ))
    .map((item) => ({
      x: 0,
      y: item.y + furnitureOffsetY + item.height,
      width: Number.POSITIVE_INFINITY,
      height: furnitureMarginBottom,
    }));
  const chromeObstacles = chromeBoxes
    .filter((box) => columnIndex >= box.columnStart && columnIndex < box.columnStart + box.columnSpan)
    .map((box) => ({
      x: 0,
      y: box.y,
      width: Number.POSITIVE_INFINITY,
      height: box.height,
    }));
  return [...topObstacle, ...furnitureObstacles, ...imageClearanceObstacles, ...chromeObstacles];
}

function getFurnitureObstacleMarginBottom(item: SolvedFurniture, marginBottom: number): number {
  return item.kind === "image" || item.kind === "pullQuote" ? marginBottom : 0;
}

function getColumnWhitespace(columns: TextLine[][], textHeight: number, furniture: SolvedFurniture[]): number {
  return columns.reduce(
    (total, column, columnIndex) =>
      total + Math.max(0, textHeight - getLinesHeight(column) - getColumnObstacleHeight(furniture, columnIndex, textHeight)),
    0,
  );
}

function getFurnitureSufficiencyReport({
  columns,
  textHeight,
  furniture,
  hasMore,
  config,
}: {
  columns: TextLine[][];
  textHeight: number;
  furniture: SolvedFurniture[];
  hasMore: boolean;
  config: LayoutConfig;
}): FurnitureSufficiencyReport {
  const visibleRows = columns.reduce((total, column) => total + column.length, 0);
  const furnitureRows = furniture.reduce(
    (total, item) => total + getFurnitureRowBurden(item, config.rhythm.rowHeight),
    0,
  );
  const accepted = (reason?: string): FurnitureSufficiencyReport => ({
    accepted: !reason,
    reason,
    visibleRows,
    furnitureRows,
  });

  if (furniture.length === 0 || furnitureRows === 0) return accepted();
  const overlapReason = getFurnitureOverlapReason(furniture);
  if (overlapReason) return accepted(overlapReason);
  const minimumReadableRows = columns.length * (furniture.some((item) => item.kind === "pullQuote") ? 6 : 3);
  if (visibleRows * 4 < furnitureRows) {
    return accepted("visible-copy-far-below-furniture-burden");
  }
  if (visibleRows < furnitureRows && visibleRows < minimumReadableRows) {
    return accepted("visible-copy-below-furniture-burden");
  }

  const finalTextColumnIndex = columns.reduce((lastIndex, column, columnIndex) => (
    column.length > 0 ? columnIndex : lastIndex
  ), -1);
  const exhausted = !hasMore;
  for (let columnIndex = 0; columnIndex < columns.length; columnIndex += 1) {
    const visibleColumnRows = columns[columnIndex].length;
    const obstacleRows = Math.ceil(getColumnObstacleHeight(furniture, columnIndex, textHeight) / config.rhythm.rowHeight);
    const availableRows = Math.floor(textHeight / config.rhythm.rowHeight) - obstacleRows;
    const hasSubstantialFurniture = obstacleRows >= 6;
    const isAfterExhaustedText = exhausted && columnIndex > finalTextColumnIndex;
    if (!hasSubstantialFurniture && !isAfterExhaustedText && availableRows >= 3 && visibleColumnRows < 3) {
      return accepted("open-column-below-minimum-copy");
    }
    if (!hasSubstantialFurniture && visibleColumnRows === 1 && columnIndex < finalTextColumnIndex) {
      return accepted("non-final-column-single-copy-row");
    }
  }

  return accepted();
}

function getFurnitureRowBurden(item: SolvedFurniture, rowHeight: number): number {
  if (item.kind !== "image" && item.kind !== "pullQuote") return 0;
  return Math.ceil(item.height / rowHeight) * item.columnSpan;
}

function getFurnitureOverlapReason(furniture: SolvedFurniture[]): string | undefined {
  for (let firstIndex = 0; firstIndex < furniture.length; firstIndex += 1) {
    for (let secondIndex = firstIndex + 1; secondIndex < furniture.length; secondIndex += 1) {
      if (rectsOverlap(furniture[firstIndex], furniture[secondIndex])) return "furniture-overlap";
    }
  }
  return undefined;
}

function getColumnObstacleHeight(furniture: SolvedFurniture[], columnIndex: number, textHeight: number): number {
  const intervals = furniture
    .filter((item) => item.wrapsText && columnIndex >= item.columnStart && columnIndex < item.columnStart + item.columnSpan)
    .map((item) => ({
      start: clamp(item.y, 0, textHeight),
      end: clamp(item.y + item.height, 0, textHeight),
    }))
    .filter((interval) => interval.end > interval.start)
    .sort((a, b) => a.start - b.start);

  const merged: Array<{ start: number; end: number }> = [];
  for (const interval of intervals) {
    const previous = merged[merged.length - 1];
    if (previous && interval.start <= previous.end) previous.end = Math.max(previous.end, interval.end);
    else merged.push({ ...interval });
  }
  return merged.reduce((total, interval) => total + interval.end - interval.start, 0);
}

function getDeadColumnCount(columns: TextLine[][], textHeight: number, furniture: SolvedFurniture[]): number {
  return columns.reduce((count, column, columnIndex) => {
    if (column.length > 0) return count;
    const obstacleHeight = getColumnObstacleHeight(furniture, columnIndex, textHeight);
    return obstacleHeight >= Math.min(96, textHeight * 0.18) ? count : count + 1;
  }, 0);
}

function getLinesHeight(lines: TextLine[]): number {
  return lines.length === 0 ? 0 : Math.max(...lines.map((line) => line.y + line.paintHeight));
}

function getFurnitureBottom(furniture: SolvedFurniture[]): number {
  return furniture.reduce((bottom, item) => Math.max(bottom, item.y + item.height), 0);
}

function getSpanCandidates(span: ResponsiveSpanPolicy, columnCount: number): number[] {
  const min = Math.min(span.min, columnCount);
  const max = Math.min(span.max, columnCount);
  const preferred = clamp(span.preferred, min, max);
  const candidates = [preferred, min, max];
  return Array.from(new Set(candidates)).sort((left, right) => (
    Math.abs(left - preferred) - Math.abs(right - preferred) || right - left
  ));
}

function resolveAnchor(anchor: ResponsivePlacementAnchor): "left" | "right" | "center" | "inline" {
  if (anchor === "outer") return "right";
  if (anchor === "inner") return "left";
  if (anchor === "inline") return "left";
  return anchor;
}

function getColumnStart(anchor: "left" | "right" | "center" | "inline", span: number, columnCount: number): number {
  if (anchor === "right") return Math.max(0, columnCount - span);
  if (anchor === "center") return Math.max(0, Math.floor((columnCount - span) / 2));
  return 0;
}

function getColumnStartForPlacement(
  placement: ResponsivePlacementSpec,
  anchor: "left" | "right" | "center" | "inline",
  span: number,
  columnCount: number,
  collapsed: boolean,
): number | null {
  if (!placement.columnStart || collapsed) return getColumnStart(anchor, span, columnCount);
  const requested = placement.columnStart - 1;
  if (requested + span <= columnCount) return requested;
  if (placement.collapse === "omit") return null;
  if (placement.collapse === "fullWidth") return 0;
  return getColumnStart("inline", Math.min(span, columnCount), columnCount);
}

function getFurnitureY(
  verticalAnchor: ResponsiveVerticalPlacement,
  height: number,
  textHeight: number,
  config: LayoutConfig,
): number {
  if (verticalAnchor === "top") return 0;
  const minY = config.lineHeight * 2;
  const maxY = Math.max(0, textHeight - height);
  const ratio = getVerticalAnchorRatio(verticalAnchor);
  const minimumY = Math.min(reserveRhythmRows(minY, config.rhythm), maxY);
  const maximumY = snapDownToRhythm(maxY, config.rhythm);
  if (maximumY < minimumY) return maximumY;
  return clamp(snapToNearestRhythm(textHeight * ratio - height / 2, config.rhythm), minimumY, maximumY);
}

function getVerticalAnchorRatio(verticalAnchor: ResponsiveVerticalPlacement): number {
  if (verticalAnchor === "top") return 0.12;
  if (verticalAnchor === "upperThird") return 0.32;
  if (verticalAnchor === "lowerThird") return 0.66;
  return 0.5;
}

function getPullQuoteMetrics(
  text: string,
  width: number,
  config: LayoutConfig,
  overrides?: ChromeTextSlotSpec,
): { height: number; fontSize: number; lineHeight: number } {
  const narrow = config.columnCount === 1;
  const fontSize = narrow ? 20 : 22;
  const lineHeight = Math.ceil(emToPx(parseEmOverride(overrides?.lineHeight, 1.12), fontSize));
  const paintHeight = Math.ceil(emToPx(parseEmOverride(overrides?.paintHeight, 1.18), fontSize));
  const metrics = measureWrappedTextBlock(text, buildChromeFont({
    fontSize,
    fontFamily: SERIF_TEXT_FONT,
    fontStyle: "italic",
    lineHeightEm: lineHeight / fontSize,
    paintHeightEm: paintHeight / fontSize,
  }), width, lineHeight, paintHeight);
  const marginBefore = Math.round(emToPx(parseEmOverride(overrides?.marginBefore, PULL_QUOTE_VERTICAL_PADDING / 2 / fontSize), fontSize));
  const marginAfter = Math.round(emToPx(parseEmOverride(overrides?.marginAfter, PULL_QUOTE_VERTICAL_PADDING / 2 / fontSize), fontSize));
  const minHeight = Math.ceil(emToPx(parseEmOverride(overrides?.minHeight, 0), fontSize));
  const height = reserveRhythmRows(Math.max(metrics.height + marginBefore + marginAfter, minHeight), config.rhythm);
  return { height, fontSize, lineHeight };
}

function getPullQuoteY({
  x,
  width,
  height,
  textHeight,
  anchorRatio,
  image,
  config,
}: {
  x: number;
  width: number;
  height: number;
  textHeight: number;
  anchorRatio: number;
  image: SolvedImageFurniture | null;
  config: LayoutConfig;
}): number | null {
  const minY = config.lineHeight * 2;
  const maxY = textHeight - height;
  if (maxY < minY) return null;
  const minimumY = reserveRhythmRows(minY, config.rhythm);
  const maximumY = snapDownToRhythm(maxY, config.rhythm);
  if (maximumY < minimumY) return null;
  const preferredY = clamp(snapToNearestRhythm(textHeight * anchorRatio - height / 2, config.rhythm), minimumY, maximumY);
  const preferredRect = { x, y: preferredY, width, height };
  if (!image || !rectsOverlap(preferredRect, image, FURNITURE_COLLISION_GUTTER)) return preferredY;
  const candidateYs = [
    reserveRhythmRows(image.y + image.height + FURNITURE_COLLISION_GUTTER, config.rhythm),
    snapDownToRhythm(image.y - height - FURNITURE_COLLISION_GUTTER, config.rhythm),
  ]
    .filter((candidateY) => candidateY >= minimumY && candidateY <= maximumY)
    .sort((leftY, rightY) => Math.abs(leftY - preferredY) - Math.abs(rightY - preferredY));
  return candidateYs.find((candidateY) => !rectsOverlap({ x, y: candidateY, width, height }, image, FURNITURE_COLLISION_GUTTER)) ?? null;
}

function rectsOverlap(
  a: { x: number; y: number; width: number; height: number },
  b: { x: number; y: number; width: number; height: number },
  gutter = 0,
): boolean {
  return (
    a.x < b.x + b.width + gutter &&
    a.x + a.width + gutter > b.x &&
    a.y < b.y + b.height + gutter &&
    a.y + a.height + gutter > b.y
  );
}

function getImageAspectRatio(asset: Pick<ArticleImageAsset, "layout">): number {
  return asset.layout?.aspectRatio ?? 1.5;
}

function getImageCaption(asset: Pick<ArticleImageAsset, "caption" | "credit">): string {
  return (asset.caption ?? asset.credit).trim();
}

function getImageCaptionHeight(caption: string, width: number, rhythm: VerticalRhythm): number {
  if (!caption) return 0;
  const contentWidth = Math.max(1, width - IMAGE_CAPTION_FONT_SIZE * IMAGE_CAPTION_HORIZONTAL_PADDING_EM);
  const metrics = measureWrappedTextBlock(
    caption,
    `italic ${IMAGE_CAPTION_FONT_SIZE}px ${SERIF_TEXT_FONT}`,
    contentWidth,
    rhythm.rowHeight,
    rhythm.rowHeight,
  );
  return reserveRhythmRows(Math.max(rhythm.rowHeight, metrics.height), rhythm);
}

function getObjectPosition(asset: Pick<ArticleImageAsset, "layout">): string {
  const focalPoint = asset.layout?.focalPoint ?? { x: 0.5, y: 0.5 };
  return `${Math.round(focalPoint.x * 100)}% ${Math.round(focalPoint.y * 100)}%`;
}

function formatContinuationJumpLabel(article: ArticlePublicationItem, pageNumber: number): string {
  return `SEE ${getShortSlug(article) ?? "MORE"} ON ${formatSectionPage(pageNumber)}`;
}

function getArticleFrameLabel(blockSpec: ArticleFrameBlockSpec, article: ArticlePublicationItem): string {
  return blockSpec.startCursor === "current" ? formatContinuationSourceLabel(article, 1) : article.section;
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

function formatByline(article: ArticlePublicationItem): string {
  return `${article.byline} / ${article.dateline}`.toUpperCase();
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
