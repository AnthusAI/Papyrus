import { type LayoutCursor, type TextLine } from "./pretext-layout";
import { type ArticleImageThemeVariants } from "./articles";
import {
  type ArticleFrameBlockSpec,
  type EditorialPriorityId,
  type HeadlineScaleId,
  type LayoutBlockSpec,
  type LayoutPageSpec,
  type LayoutRegionSpec,
  type ResponsivePlacementSpec,
} from "./layout-plan";
import { type ArticlePublicationItem, type PublicationItem } from "./publication-items";
import { type VerticalRhythm } from "./blog-rhythm";

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

export type FrontStoryRole = "feature" | "rail" | "standard";

export type ChromeTextStyle = {
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

export type ChromeBoxTreatment = {
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

export type LayoutConfig = {
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

export type FrontRow = {
  startIndex: number;
  endIndex: number;
  height: number;
};

export type FrontArticlePlacement = {
  block: ArticleFrameBlockSpec;
  originalIndex: number;
  solveIndex: number;
  gridPlacement?: SolvedFrontGridPlacement;
  rowHeight?: number;
};

export type FrontArticleSolveOptions = {
  enforcePlacementHeight?: boolean;
};

export type FrontCompositionFlowMode = "offsetBody" | "integrated" | "titleStackedMedia" | "stackedMedia";

export type ArticleFrameCandidate = {
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

export type MediaVariant = {
  id: string;
  placement: ResponsivePlacementSpec | null;
  assetRole?: string;
  columnStart: number;
  columnSpan: number;
  fallbackPenalty: number;
};

export type PlacementVariant = {
  id: string;
  placement: ResponsivePlacementSpec;
  columnStart: number;
  columnSpan: number;
  fallbackPenalty: number;
};

export type PullQuoteVariant = {
  id: string;
  placement: ResponsivePlacementSpec | null;
  columnStart: number;
  columnSpan: number;
  fallbackPenalty: number;
};
