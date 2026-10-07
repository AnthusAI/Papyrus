import type { ArticleImageAsset } from "./articles";
import type { PublicationItem } from "./publication-items";
import {
  createDefaultBlogVerticalRhythm,
  getMeasuredTextHeight,
  reserveRhythmRows,
  snapDownToRhythm,
  snapPreferredHeightToRhythm,
  snapPreservedImageHeightToRhythm,
  type BlogTextStyle,
  type VerticalRhythm,
} from "./blog-rhythm";
import { layoutAllTextLines, layoutTextLines, prepareWithSegments, type TextLine, type TextObstacle } from "./pretext-layout";

export type FeaturedLayoutMode = "obstacle" | "float" | "stacked";

export type SolvedFeaturedItem = {
  mode: FeaturedLayoutMode;
  textLines: TextLine[];
  imageHeight: number;
  imageWidth: number;
  /** Image frame + caption/credit block reserved below the frame. */
  mediaHeight: number;
  captionHeight: number;
  copyWidth: number;
  textFrameHeight: number;
  hasMore: boolean;
  gap: number;
};

export type SolvedFeaturedFloatGeometry = {
  mode: "float";
  imageHeight: number;
  imageWidth: number;
  mediaHeight: number;
  captionHeight: number;
  copyWidth: number;
  gap: number;
};

export type SolveFeaturedItemInput = {
  text: string;
  containerWidth: number;
  viewportWidth: number;
  rhythm?: VerticalRhythm;
  textStyle: BlogTextStyle;
  imageAsset: ArticleImageAsset;
  itemIndex?: number;
};

export type SolveFeaturedFloatGeometryInput = {
  containerWidth: number;
  viewportWidth: number;
  rhythm?: VerticalRhythm;
  imageAsset: Pick<ArticleImageAsset, "layout" | "caption" | "credit">;
  itemIndex?: number;
  /** Fraction of container width for the image. Defaults to the edition-index teaser ratio. */
  imageWidthRatio?: number;
  /** Fraction of viewport width used as a hard image-width cap. Defaults to 1/3. */
  viewportImageCapRatio?: number;
  /** Absolute float width cap in rhythm rows. Stops percentage sizing from outgrowing the rail. */
  maxWidthRows?: number;
};

const FLOAT_IMAGE_WIDTH_RATIO = 0.32;
/** Article pages use a larger float so the pictogram reads as a feature, not a teaser. */
const ARTICLE_FLOAT_IMAGE_WIDTH_RATIO = 0.48;
const ARTICLE_VIEWPORT_IMAGE_CAP_RATIO = 0.5;
/** Edition-index floats track the pictogram maxHeight band (~440px at 16px rows). */
const FLOAT_IMAGE_MAX_WIDTH_ROWS = 27;
/** Article floats read larger than teasers but must not keep growing on wide rails. */
const ARTICLE_FLOAT_IMAGE_MAX_WIDTH_ROWS = 24;
const FLOAT_IMAGE_MIN_PHONE_ROWS = 6;
const FLOAT_IMAGE_MIN_DESKTOP_ROWS = 8;
const FLOAT_COPY_MIN_PHONE_ROWS = 11;
const FLOAT_COPY_MIN_DESKTOP_ROWS = 14;
const LEAD_GAP_ROWS = 2;
const LEAD_GAP_ROWS_NARROW = 1;
const DEFAULT_GAP_ROWS = 4;

export function getFeaturedLayoutMode(viewportWidth: number, hasImage: boolean): FeaturedLayoutMode {
  if (!hasImage) return "stacked";
  return "float";
}

export function solveFeaturedItem(input: SolveFeaturedItemInput): SolvedFeaturedItem {
  const rhythm = input.rhythm ?? createDefaultBlogVerticalRhythm();
  const gap = getFeaturedLayoutGap(input.viewportWidth, input.itemIndex, rhythm);
  const mode = getFeaturedLayoutMode(input.viewportWidth, true);
  const prepared = prepareWithSegments(input.text, `${input.textStyle.fontSize}px ${input.textStyle.fontFamily}`, {
    whiteSpace: "pre-wrap",
  });
  const aspectRatio = getImageAspectRatio(input.imageAsset);

  if (mode === "obstacle") {
    return solveObstacleFeaturedItem({
      prepared,
      containerWidth: input.containerWidth,
      viewportWidth: input.viewportWidth,
      rhythm,
      textStyle: input.textStyle,
      aspectRatio,
      gap,
      imageAsset: input.imageAsset,
    });
  }

  if (mode === "float") {
    return solveFloatFeaturedItem({
      prepared,
      containerWidth: input.containerWidth,
      viewportWidth: input.viewportWidth,
      rhythm,
      textStyle: input.textStyle,
      aspectRatio,
      gap,
      imageAsset: input.imageAsset,
    });
  }

  const lines = layoutAllTextLines({
    prepared,
    maxWidth: input.containerWidth,
    ...input.textStyle,
  });
  const imageWidth = snapDownToRhythm(Math.round(input.containerWidth), rhythm);
  const imageHeight = snapImageHeight(imageWidth / aspectRatio, rhythm, input.imageAsset.layout);
  const captionHeight = getFeatureCaptionHeight(input.imageAsset, imageWidth, rhythm);
  return {
    mode,
    textLines: lines,
    imageHeight,
    imageWidth,
    captionHeight,
    mediaHeight: imageHeight + captionHeight,
    copyWidth: input.containerWidth,
    textFrameHeight: reserveRhythmRows(getMeasuredTextHeight(lines), rhythm),
    hasMore: false,
    gap,
  };
}

type PreparedSolveInput = {
  prepared: ReturnType<typeof prepareWithSegments>;
  containerWidth: number;
  viewportWidth: number;
  rhythm: VerticalRhythm;
  textStyle: BlogTextStyle;
  aspectRatio: number;
  gap: number;
  imageAsset: ArticleImageAsset;
};

function solveObstacleFeaturedItem(input: PreparedSolveInput): SolvedFeaturedItem {
  const maxImageWidth = getFloatImageWidth(input);
  let best: {
    score: number;
    textLines: TextLine[];
    imageHeight: number;
    imageWidth: number;
    captionHeight: number;
    mediaHeight: number;
    copyWidth: number;
    textFrameHeight: number;
    hasMore: boolean;
  } | null = null;

  for (const imageWidth of getObstacleImageWidths(maxImageWidth, input.rhythm)) {
    const copyWidth = Math.max(
      getFloatCopyMinimum(input.viewportWidth, input.rhythm),
      input.containerWidth - imageWidth - input.gap,
    );
    const imageHeight = snapImageHeight(imageWidth / input.aspectRatio, input.rhythm, input.imageAsset.layout);
    const captionHeight = getFeatureCaptionHeight(input.imageAsset, imageWidth, input.rhythm);
    const mediaHeight = imageHeight + captionHeight;
    const obstacle: TextObstacle = {
      x: Math.max(0, copyWidth - imageWidth),
      y: 0,
      width: imageWidth,
      height: mediaHeight,
    };

    let candidateHeight = mediaHeight;
    let result = layoutTextLines({
      prepared: input.prepared,
      cursor: { segmentIndex: 0, graphemeIndex: 0 },
      maxHeight: candidateHeight,
      maxWidth: copyWidth,
      lineHeight: input.textStyle.lineHeight,
      linePaintHeight: input.textStyle.linePaintHeight,
      fontSize: input.textStyle.fontSize,
      fontFamily: input.textStyle.fontFamily,
      obstacles: [obstacle],
    });

    const textBottom = getMeasuredTextHeight(result.lines);
    if (textBottom > 0 && textBottom < candidateHeight) {
      candidateHeight = reserveRhythmRows(textBottom, input.rhythm);
      obstacle.height = candidateHeight;
      result = layoutTextLines({
        prepared: input.prepared,
        cursor: { segmentIndex: 0, graphemeIndex: 0 },
        maxHeight: candidateHeight,
        maxWidth: copyWidth,
        lineHeight: input.textStyle.lineHeight,
        linePaintHeight: input.textStyle.linePaintHeight,
        fontSize: input.textStyle.fontSize,
        fontFamily: input.textStyle.fontFamily,
        obstacles: [obstacle],
      });
    }

    const whitespace = Math.max(0, candidateHeight - getMeasuredTextHeight(result.lines));
    const score = 50_000 - whitespace * 1.4 - Math.abs(candidateHeight - mediaHeight) * 0.35 - Math.abs(maxImageWidth - imageWidth) * 0.2;
    const candidate = {
      score,
      textLines: result.lines,
      imageHeight: Math.min(imageHeight, candidateHeight),
      imageWidth,
      captionHeight,
      mediaHeight: candidateHeight,
      copyWidth,
      textFrameHeight: reserveRhythmRows(getMeasuredTextHeight(result.lines), input.rhythm),
      hasMore: result.hasMore,
    };
    if (!best || candidate.score > best.score) best = candidate;
  }

  const fallbackImageHeight = input.rhythm.rowHeight * 6;
  return {
    mode: "obstacle",
    textLines: best?.textLines ?? [],
    imageHeight: best?.imageHeight ?? fallbackImageHeight,
    imageWidth: best?.imageWidth ?? maxImageWidth,
    captionHeight: best?.captionHeight ?? 0,
    mediaHeight: best?.mediaHeight ?? fallbackImageHeight,
    copyWidth: best?.copyWidth ?? input.containerWidth,
    textFrameHeight: best?.textFrameHeight ?? 0,
    hasMore: best?.hasMore ?? false,
    gap: input.gap,
  };
}

function solveFloatFeaturedItem(input: PreparedSolveInput): SolvedFeaturedItem {
  const geometry = computeFloatGeometry({
    containerWidth: input.containerWidth,
    viewportWidth: input.viewportWidth,
    rhythm: input.rhythm,
    gap: input.gap,
    aspectRatio: input.aspectRatio,
    imageAsset: input.imageAsset,
  });
  // Full-width frame with the image+caption as a top-right obstacle so excerpt
  // lines shorten beside the media block and resume full width below it.
  const frameWidth = input.containerWidth;
  const obstacle: TextObstacle = {
    x: Math.max(0, frameWidth - geometry.imageWidth - geometry.gap),
    y: 0,
    width: geometry.imageWidth + geometry.gap,
    height: geometry.mediaHeight,
  };
  const lines = layoutAllTextLines({
    prepared: input.prepared,
    maxWidth: frameWidth,
    lineHeight: input.textStyle.lineHeight,
    linePaintHeight: input.textStyle.linePaintHeight,
    fontSize: input.textStyle.fontSize,
    fontFamily: input.textStyle.fontFamily,
    obstacles: [obstacle],
  });

  return {
    mode: "float",
    textLines: lines,
    imageHeight: geometry.imageHeight,
    imageWidth: geometry.imageWidth,
    captionHeight: geometry.captionHeight,
    mediaHeight: geometry.mediaHeight,
    copyWidth: frameWidth,
    textFrameHeight: reserveRhythmRows(getMeasuredTextHeight(lines), input.rhythm),
    hasMore: false,
    gap: geometry.gap,
  };
}

/**
 * Geometry-only float solve for article pages (and any consumer that renders
 * flowing body copy rather than Pretext-measured excerpt lines). Shares the
 * same width/height/gap math as the edition-index lead float.
 */
export function solveFeaturedFloatGeometry(input: SolveFeaturedFloatGeometryInput): SolvedFeaturedFloatGeometry {
  const rhythm = input.rhythm ?? createDefaultBlogVerticalRhythm();
  const gap = getFeaturedLayoutGap(input.viewportWidth, input.itemIndex, rhythm);
  return {
    mode: "float",
    ...computeFloatGeometry({
      containerWidth: input.containerWidth,
      viewportWidth: input.viewportWidth,
      rhythm,
      gap,
      aspectRatio: getImageAspectRatio(input.imageAsset),
      imageAsset: input.imageAsset,
      // Article pages default larger than edition teasers; callers can override.
      imageWidthRatio: input.imageWidthRatio ?? ARTICLE_FLOAT_IMAGE_WIDTH_RATIO,
      viewportImageCapRatio: input.viewportImageCapRatio ?? ARTICLE_VIEWPORT_IMAGE_CAP_RATIO,
      maxWidthRows: input.maxWidthRows ?? ARTICLE_FLOAT_IMAGE_MAX_WIDTH_ROWS,
    }),
  };
}

type FloatGeometryInput = {
  containerWidth: number;
  viewportWidth: number;
  rhythm: VerticalRhythm;
  gap: number;
  aspectRatio: number;
  imageAsset: Pick<ArticleImageAsset, "caption" | "credit" | "layout">;
  imageWidthRatio?: number;
  viewportImageCapRatio?: number;
  maxWidthRows?: number;
};

function computeFloatGeometry(input: FloatGeometryInput): Omit<SolvedFeaturedFloatGeometry, "mode"> {
  let imageWidth = getFloatImageWidth(input);
  // Keep the frame proportional when layout.maxHeight would otherwise clip a
  // wide float down to the minimum height (snapPreferredHeightToRhythm falls
  // back to min when natural height exceeds max).
  const maxHeight = input.imageAsset.layout?.maxHeight ?? input.rhythm.rowHeight * 36;
  const widthFromMaxHeight = snapDownToRhythm(maxHeight * input.aspectRatio, input.rhythm);
  if (widthFromMaxHeight > 0) {
    imageWidth = Math.min(imageWidth, widthFromMaxHeight);
  }
  const absoluteMaxWidth = rhythmLengthRows(input.maxWidthRows ?? FLOAT_IMAGE_MAX_WIDTH_ROWS, input.rhythm);
  imageWidth = Math.min(imageWidth, absoluteMaxWidth);
  const copyWidth = Math.max(
    getFloatCopyMinimum(input.viewportWidth, input.rhythm),
    input.containerWidth - imageWidth - input.gap,
  );
  const imageHeight = snapImageHeight(imageWidth / input.aspectRatio, input.rhythm, input.imageAsset.layout);
  const captionHeight = getFeatureCaptionHeight(input.imageAsset, imageWidth, input.rhythm);
  return {
    imageHeight,
    imageWidth,
    captionHeight,
    mediaHeight: imageHeight + captionHeight,
    copyWidth,
    gap: input.gap,
  };
}

/** Matches the blog figcaption: meta size, one-row line box, rhythm-unit margin-top. */
const FEATURE_CAPTION_FONT_SIZE = 12;

function getFeatureCaptionHeight(
  asset: Pick<ArticleImageAsset, "caption" | "credit">,
  imageWidth: number,
  rhythm: VerticalRhythm,
): number {
  const caption = (asset.caption ?? asset.credit ?? "").trim();
  if (!caption) return 0;
  const fontFamily = 'Georgia, "Times New Roman", serif';
  const prepared = prepareWithSegments(caption, `${FEATURE_CAPTION_FONT_SIZE}px ${fontFamily}`, {
    whiteSpace: "pre-wrap",
  });
  const lines = layoutAllTextLines({
    prepared,
    maxWidth: Math.max(1, imageWidth),
    lineHeight: rhythm.rowHeight,
    linePaintHeight: rhythm.rowHeight,
    fontSize: FEATURE_CAPTION_FONT_SIZE,
    fontFamily,
  });
  const textHeight = Math.max(rhythm.rowHeight, getMeasuredTextHeight(lines));
  // Brand CSS: figcaption margin-top is one rhythm unit, a quarter of a row.
  const marginTop = rhythm.rowHeight / 4;
  return reserveRhythmRows(marginTop + textHeight, rhythm);
}

function getFeaturedLayoutGap(viewportWidth: number, itemIndex: number | undefined, rhythm: VerticalRhythm): number {
  if (itemIndex === 0) {
    return rhythmLengthRows(viewportWidth <= 600 ? LEAD_GAP_ROWS_NARROW : LEAD_GAP_ROWS, rhythm);
  }
  return rhythmLengthRows(DEFAULT_GAP_ROWS, rhythm);
}

function getFloatImageWidth(
  input: Pick<
    FloatGeometryInput,
    "containerWidth" | "viewportWidth" | "rhythm" | "gap" | "imageWidthRatio" | "viewportImageCapRatio" | "maxWidthRows"
  >,
): number {
  const imageWidthRatio = input.imageWidthRatio ?? FLOAT_IMAGE_WIDTH_RATIO;
  const viewportImageCapRatio = input.viewportImageCapRatio ?? (1 / 3);
  const preferred = snapDownToRhythm(Math.round(input.containerWidth * imageWidthRatio), input.rhythm);
  const viewportCap = snapDownToRhythm(Math.floor(input.viewportWidth * viewportImageCapRatio), input.rhythm);
  const copyCap = snapDownToRhythm(
    Math.max(0, input.containerWidth - input.gap - getFloatCopyMinimum(input.viewportWidth, input.rhythm)),
    input.rhythm,
  );
  const absoluteMaxWidth = rhythmLengthRows(input.maxWidthRows ?? FLOAT_IMAGE_MAX_WIDTH_ROWS, input.rhythm);
  const softMinimum = getFloatImageMinimum(input.viewportWidth, input.rhythm);
  const hardMinimum = rhythmLengthRows(5, input.rhythm);
  const hardMaximum = Math.max(
    hardMinimum,
    Math.min(absoluteMaxWidth, viewportCap, copyCap > 0 ? copyCap : viewportCap),
  );

  if (hardMaximum <= softMinimum) return hardMaximum;
  return clamp(Math.min(preferred, hardMaximum), softMinimum, hardMaximum);
}

function getFloatImageMinimum(viewportWidth: number, rhythm: VerticalRhythm): number {
  return rhythmLengthRows(viewportWidth <= 600 ? FLOAT_IMAGE_MIN_PHONE_ROWS : FLOAT_IMAGE_MIN_DESKTOP_ROWS, rhythm);
}

function getFloatCopyMinimum(viewportWidth: number, rhythm: VerticalRhythm): number {
  return rhythmLengthRows(viewportWidth <= 600 ? FLOAT_COPY_MIN_PHONE_ROWS : FLOAT_COPY_MIN_DESKTOP_ROWS, rhythm);
}

function getObstacleImageWidths(maximum: number, rhythm: VerticalRhythm): number[] {
  const candidateRows = [0, 1, 2].map((offset) => Math.max(rhythm.rowHeight * 5, maximum - (offset * rhythm.rowHeight)));
  return Array.from(new Set(candidateRows));
}

function snapImageHeight(
  naturalHeight: number,
  rhythm: VerticalRhythm,
  layout?: ArticleImageAsset["layout"],
): number {
  const maxHeight = layout?.maxHeight ?? rhythm.rowHeight * 36;
  // Cover may grow the frame to layout.minHeight. Contain/preserve must not —
  // on narrow viewports the chosen width implies a short natural height, and
  // stretching to minHeight leaves an empty outlined box around the pictogram.
  if (layout?.crop === "cover") {
    const minHeight = layout.minHeight ?? rhythm.rowHeight * 6;
    const clampedHeight = clamp(naturalHeight, minHeight, maxHeight);
    return snapPreferredHeightToRhythm(clampedHeight, rhythm, minHeight, maxHeight);
  }
  const hardMinimum = rhythm.rowHeight;
  const capped = clamp(naturalHeight, hardMinimum, maxHeight);
  return snapPreservedImageHeightToRhythm(capped, rhythm, hardMinimum, maxHeight);
}

function getImageAspectRatio(asset: Pick<ArticleImageAsset, "layout">): number {
  if (asset.layout?.aspectRatio) return asset.layout.aspectRatio;
  return 1;
}

function rhythmLengthRows(rows: number, rhythm: VerticalRhythm): number {
  return rows * rhythm.rowHeight;
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}

export function isFeaturedBlogItem(item: PublicationItem, index?: number, mode?: string): boolean {
  return mode === "blog" && index === 0 && Boolean(item.type === "article" || item.type === "brief");
}
