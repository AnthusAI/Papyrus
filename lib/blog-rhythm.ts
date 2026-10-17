import type { TextLine } from "./pretext-layout";

export type VerticalRhythm = {
  rowHeight: number;
  paintHeight: number;
  paintBuffer: number;
};

export type BlogTextStyle = {
  fontSize: number;
  lineHeight: number;
  linePaintHeight: number;
  fontFamily: string;
};

export const BLOG_RHYTHM_UNIT = 4;
export const BLOG_COPY_ROW_MULTIPLE = 4;
export const BLOG_PAINT_BUFFER_PX = 2;
/* Blog body and excerpt copy must never fall below the section
   subheading scale. At the default 16px rhythm row, that means an 18px font
   set on a two-row (32px) line box so multi-line copy always keeps one blank
   rhythm row between lines. */
export const BLOG_FONT_SIZE_ROW_RATIO = 18 / 16;
export const BLOG_LINE_HEIGHT_ROWS = 2;

export function createVerticalRhythm(rowHeight: number, paintBuffer = BLOG_PAINT_BUFFER_PX): VerticalRhythm {
  const paintHeight = rowHeight + paintBuffer;
  return {
    rowHeight,
    paintHeight,
    paintBuffer: paintHeight - rowHeight,
  };
}

export function createDefaultBlogVerticalRhythm(): VerticalRhythm {
  return createVerticalRhythm(BLOG_RHYTHM_UNIT * BLOG_COPY_ROW_MULTIPLE, BLOG_PAINT_BUFFER_PX);
}

export function createDefaultBlogTextStyle(fontFamily: string): BlogTextStyle {
  const rhythm = createDefaultBlogVerticalRhythm();
  const lineHeight = rhythm.rowHeight * BLOG_LINE_HEIGHT_ROWS;
  return {
    fontSize: rhythm.rowHeight * BLOG_FONT_SIZE_ROW_RATIO,
    lineHeight,
    /* The measured blog excerpt renderer clips each line to linePaintHeight.
       Once copy was raised to the 18px / 32px minimum policy, the old
       one-row paint box (18px) started chopping off the bottom of the glyphs.
       Use the full two-row line box for paint so measured lines match the
       visible CSS line box and never clip descenders or lower halves. */
    linePaintHeight: lineHeight,
    fontFamily,
  };
}

export function snapUpToRhythm(value: number, rhythm: VerticalRhythm): number {
  if (value <= 0) return 0;
  return Math.ceil(value / rhythm.rowHeight) * rhythm.rowHeight;
}

export function snapDownToRhythm(value: number, rhythm: VerticalRhythm): number {
  if (value <= 0) return 0;
  return Math.floor(value / rhythm.rowHeight) * rhythm.rowHeight;
}

export function snapToNearestRhythm(value: number, rhythm: VerticalRhythm): number {
  if (value <= 0) return 0;
  return Math.round(value / rhythm.rowHeight) * rhythm.rowHeight;
}

export function reserveRhythmRows(value: number, rhythm: VerticalRhythm): number {
  return snapUpToRhythm(value, rhythm);
}

export function clampRhythmHeight(value: number, minimum: number, maximum: number, rhythm: VerticalRhythm): number {
  const snappedMinimum = reserveRhythmRows(minimum, rhythm);
  const snappedMaximum = Math.max(snappedMinimum, snapDownToRhythm(maximum, rhythm));
  return clamp(reserveRhythmRows(value, rhythm), snappedMinimum, snappedMaximum);
}

export function snapPreferredHeightToRhythm(
  value: number,
  rhythm: VerticalRhythm,
  minimum = rhythm.rowHeight,
  maximum = Number.POSITIVE_INFINITY,
): number {
  const snappedMinimum = reserveRhythmRows(minimum, rhythm);
  const snappedMaximum = Number.isFinite(maximum)
    ? Math.max(snappedMinimum, snapDownToRhythm(maximum, rhythm))
    : Number.POSITIVE_INFINITY;
  const down = snapDownToRhythm(value, rhythm);
  const up = reserveRhythmRows(value, rhythm);
  const candidates = [down, up].filter((candidate) => candidate >= snappedMinimum && candidate <= snappedMaximum);
  if (candidates.length === 0) return snappedMinimum;
  return candidates.sort((left, right) => Math.abs(left - value) - Math.abs(right - value) || left - right)[0];
}

export function snapPreservedImageHeightToRhythm(
  value: number,
  rhythm: VerticalRhythm,
  minimum = rhythm.rowHeight,
  maximum = Number.POSITIVE_INFINITY,
): number {
  const snappedMinimum = reserveRhythmRows(minimum, rhythm);
  const snappedMaximum = Number.isFinite(maximum)
    ? Math.max(snappedMinimum, snapDownToRhythm(maximum, rhythm))
    : Number.POSITIVE_INFINITY;
  return clamp(reserveRhythmRows(value, rhythm), snappedMinimum, snappedMaximum);
}

export function getLineStackHeight(lineCount: number, lineHeight: number, paintHeight: number): number {
  if (lineCount <= 0) return 0;
  return Math.ceil((lineCount - 1) * lineHeight + paintHeight);
}

export function getMeasuredTextHeight(lines: TextLine[]): number {
  const last = lines[lines.length - 1];
  return last ? last.y + last.paintHeight : 0;
}

export function rhythmRows(value: number, rhythm: VerticalRhythm): number {
  return Math.max(0, Math.round(value / rhythm.rowHeight));
}

export function rhythmLength(rows: number, rhythm: VerticalRhythm): number {
  return rows * rhythm.rowHeight;
}

export function snapRhythmCoordinate(value: number, rhythm: VerticalRhythm): number {
  return snapToNearestRhythm(value, rhythm);
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
