import { type LayoutCursor } from "./pretext-layout";
import {
  createVerticalRhythm,
  reserveRhythmRows,
  snapDownToRhythm,
  type VerticalRhythm,
} from "./blog-rhythm";
import { type ResponsiveSpanPolicy } from "./layout-plan";
import { type LayoutConfig, type PageChromeMetrics } from "./layout-types";
import { getFrontGridHeight, getFrontRows } from "./front-mosaic";

export const EMPTY_CURSOR: LayoutCursor = { segmentIndex: 0, graphemeIndex: 0 };

export const SERIF_TEXT_FONT = 'Georgia, "Times New Roman", serif';

export const SANS_TEXT_FONT = "Arial, Helvetica, sans-serif";

export const IMAGE_CAPTION_FONT_SIZE = 12;

export const IMAGE_CAPTION_HORIZONTAL_PADDING_EM = 0.3;

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

export const CONTINUED_TITLE_HEADING_MARGIN_TOP = 5;

export const CONTINUED_TITLE_PADDING_BOTTOM = 0;

export const CONTINUED_TITLE_BORDER_BOTTOM = 0;

export const CONTINUED_TITLE_MARGIN_BOTTOM = 0;

export const FURNITURE_COLLISION_GUTTER = 14;

export const PULL_QUOTE_VERTICAL_PADDING = 24;

const NEWSPAPER_PAINT_BUFFER_PX = 4;

export function getMinimumTextFrameHeight(config: LayoutConfig): number {
  return reserveRhythmRows(config.linePaintHeight, config.rhythm);
}

export function pageIdFor(pageNumber: number): string {
  return `page-${pageNumber}`;
}

export function getLayoutConfig(pageWidth: number, viewportHeight: number): LayoutConfig {
  const narrow = pageWidth < 560;
  const medium = pageWidth >= 560 && pageWidth < 1040;
  const bodyFontSize = narrow ? 14 : 15;
  const bodyLineHeight = Math.ceil(bodyFontSize * 1.4);
  const rhythm = createVerticalRhythm(bodyLineHeight, NEWSPAPER_PAINT_BUFFER_PX);
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

export function getResponsiveColumnCount(pageWidth: number, contentWidth: number, gap: number): number {
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

export function getBlockSpan(config: LayoutConfig, span: ResponsiveSpanPolicy | undefined): number {
  if (config.columnCount === 1) return 1;
  return clamp(span?.preferred ?? config.columnCount, span?.min ?? 1, Math.min(span?.max ?? config.columnCount, config.columnCount));
}

export function getBlockWidth(config: LayoutConfig, span: ResponsiveSpanPolicy | undefined): number {
  return getSpanWidth(config, getBlockSpan(config, span));
}

export function getSpanWidth(config: LayoutConfig, span: number): number {
  const safeSpan = clamp(span, 1, config.columnCount);
  const singleColumn = (config.contentWidth - config.gap * (config.columnCount - 1)) / config.columnCount;
  return singleColumn * safeSpan + config.gap * (safeSpan - 1);
}

export function getSpanRect(config: LayoutConfig, columnStart: number, columnSpan: number): { x: number; width: number } {
  const safeStart = clamp(columnStart, 0, Math.max(0, config.columnCount - 1));
  const safeSpan = clamp(columnSpan, 1, config.columnCount - safeStart);
  const columnWidth = getSpanWidth(config, 1);
  const rawX = safeStart * (columnWidth + config.gap);
  const rawRight = rawX + getSpanWidth(config, safeSpan);
  const x = Math.round(rawX);
  const right = Math.min(Math.round(rawRight), Math.floor(config.contentWidth));
  return { x, width: Math.max(1, right - x) };
}

export function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}
