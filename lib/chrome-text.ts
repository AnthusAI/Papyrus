import {
  type ArticleFrameBlockSpec,
  type ArticleFrameChromeSpec,
  type ArticleFrameCompositionSlotSpec,
  type ChromeTextSlotSpec,
  type HeadlineScaleId,
} from "./layout-plan";
import { type ArticlePublicationItem } from "./publication-items";
import { getLineStackHeight, reserveRhythmRows, snapUpToRhythm, type VerticalRhythm } from "./blog-rhythm";
import { layoutNextLine, prepareWithSegmentsCached } from "./pretext-layout";
import { resolvePreferredPlacementVariant } from "./furniture";
import {
  type ChromeBoxTreatment,
  type ChromeTextBoxMetrics,
  type ChromeTextStyle,
  type ContinuationTitleMetrics,
  type FrontStoryRole,
  type LayoutConfig,
  type PlacementVariant,
  type SolvedChromeBox,
  type StoryChromeMetrics,
} from "./layout-types";
import {
  CONTINUED_TITLE_BORDER_BOTTOM,
  CONTINUED_TITLE_HEADING_MARGIN_TOP,
  CONTINUED_TITLE_MARGIN_BOTTOM,
  CONTINUED_TITLE_PADDING_BOTTOM,
  EMPTY_CURSOR,
  SANS_TEXT_FONT,
  SERIF_TEXT_FONT,
  clamp,
  getSpanRect,
} from "./layout-config";
import { formatByline } from "./labels";

const KICKER_BASE_FONT_SIZE = 11.5;

const KICKER_BASE_ROW_HEIGHT = 19;

function getKickerFontSize(rhythmRowHeight: number): number {
  return Math.round((KICKER_BASE_FONT_SIZE * rhythmRowHeight / KICKER_BASE_ROW_HEIGHT) * 10) / 10;
}

export function solveCompositionChromeBox({
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

export function isTextCompositionSlot(slot: ArticleFrameCompositionSlotSpec["slot"]): slot is SolvedChromeBox["slot"] {
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

export function getStoryChromeMetrics(
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

export function resolveFrontStoryRole(blockSpec: ArticleFrameBlockSpec, span: number, hasFeatureCue: boolean): FrontStoryRole {
  if (blockSpec.role === "feature" || blockSpec.role === "primary") return "feature";
  if (blockSpec.role === "rail") return "rail";
  if (span >= 4 || hasFeatureCue) return "feature";
  return "standard";
}

export function resolveHeadlineScale(blockSpec: ArticleFrameBlockSpec, storyRole: FrontStoryRole): HeadlineScaleId {
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

export function buildChromeFont(style: ChromeTextStyle): string {
  const pieces: string[] = [];
  if (style.fontStyle && style.fontStyle !== "normal") pieces.push(style.fontStyle);
  if (style.fontWeight) pieces.push(String(style.fontWeight));
  pieces.push(`${style.fontSize}px`);
  pieces.push(style.fontFamily);
  return pieces.join(" ");
}

export function parseEmOverride(value: ChromeTextSlotSpec[keyof ChromeTextSlotSpec] | undefined, fallback: number): number {
  if (!value) return fallback;
  return parseEmValue(value);
}

function parseEmValue(value: string): number {
  return Number(value.slice(0, -2));
}

export function emToPx(value: number, fontSize: number): number {
  return value * fontSize;
}

export function getStoryChromeHeight(chrome: StoryChromeMetrics): number {
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

export function getStoryJumpReserveHeight(chrome: StoryChromeMetrics): number {
  return chrome.jumpBorderTopHeight + chrome.jumpPaddingTop + chrome.jumpHeight + chrome.jumpPaddingBottom;
}

export function getContinuationTitleMetrics(
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

export function measureWrappedTextBlock(
  text: string,
  font: string,
  maxWidth: number,
  lineHeight: number,
  paintHeight = lineHeight,
): { lineCount: number; height: number } {
  const prepared = prepareWithSegmentsCached(text, font);
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
