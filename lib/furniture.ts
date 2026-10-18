import {
  type ArticleFrameChromeSpec,
  type ChromeTextSlotSpec,
  type LayoutMediaSpec,
  type LayoutPullQuoteSpec,
  type ResponsivePlacementAnchor,
  type ResponsivePlacementSpec,
  type ResponsiveSpanPolicy,
  type ResponsiveVerticalPlacement,
} from "./layout-plan";
import { type ArticlePublicationItem, getPublicationItemImageAssets } from "./publication-items";
import {
  reserveRhythmRows,
  snapDownToRhythm,
  snapPreferredHeightToRhythm,
  snapPreservedImageHeightToRhythm,
  snapToNearestRhythm,
  type VerticalRhythm,
} from "./blog-rhythm";
import { type ArticleImageAsset } from "./articles";
import {
  type LayoutConfig,
  type MediaVariant,
  type PlacementVariant,
  type PullQuoteVariant,
  type SolvedImageFurniture,
  type SolvedPullQuoteFurniture,
} from "./layout-types";
import {
  FURNITURE_COLLISION_GUTTER,
  IMAGE_CAPTION_FONT_SIZE,
  IMAGE_CAPTION_HORIZONTAL_PADDING_EM,
  PULL_QUOTE_VERTICAL_PADDING,
  SERIF_TEXT_FONT,
  clamp,
  getSpanRect,
} from "./layout-config";
import { buildChromeFont, emToPx, measureWrappedTextBlock, parseEmOverride } from "./chrome-text";

export function getMediaVariants(media: LayoutMediaSpec | undefined, config: LayoutConfig): MediaVariant[] {
  if (!media) return [getNoMediaVariant(900)];
  const variants = resolvePlacementVariants(media.placement, config).map((variant) => ({
    ...variant,
    assetRole: media.assetRole,
    fallbackPenalty: variant.fallbackPenalty + Math.abs(variant.columnSpan - media.placement.span.preferred) * 900,
  }));
  if (media.required) return variants;
  return [...variants, getNoMediaVariant(24_000)];
}

export function getNoMediaVariant(fallbackPenalty: number): MediaVariant {
  return { id: "none", placement: null, columnStart: 0, columnSpan: 0, fallbackPenalty };
}

export function getPullQuoteVariants(
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

export function resolvePreferredPlacementVariant(placement: ResponsivePlacementSpec, config: LayoutConfig): PlacementVariant | null {
  return resolvePlacementVariants(placement, config)[0] ?? null;
}

export function createImageFurniture(
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

export function createPullQuoteFurniture(
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

export function getPreferredImage(
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

export function hasAvailablePreferredImage(
  article: ArticlePublicationItem,
  placement: ResponsivePlacementSpec,
  assetRole: string | undefined,
  usedImageAssetIds: ReadonlySet<string>,
): boolean {
  return getPreferredImage(article, placement, assetRole, usedImageAssetIds) !== null;
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

export function rectsOverlap(
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

export function getImageAspectRatio(asset: Pick<ArticleImageAsset, "layout">): number {
  return asset.layout?.aspectRatio ?? 1.5;
}

export function getImageCaption(asset: Pick<ArticleImageAsset, "caption" | "credit">): string {
  return (asset.caption ?? asset.credit).trim();
}

export function getImageCaptionHeight(caption: string, width: number, rhythm: VerticalRhythm): number {
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

export function getObjectPosition(asset: Pick<ArticleImageAsset, "layout">): string {
  const focalPoint = asset.layout?.focalPoint ?? { x: 0.5, y: 0.5 };
  return `${Math.round(focalPoint.x * 100)}% ${Math.round(focalPoint.y * 100)}%`;
}
