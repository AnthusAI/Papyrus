import { type ArticlePublicationItem, getPublicationItemText } from "./publication-items";
import {
  type LayoutCursor,
  layoutTextLines,
  type PreparedTextWithSegments,
  prepareWithSegmentsCached,
  type TextLine,
  type TextObstacle,
} from "./pretext-layout";
import { reserveRhythmRows, type VerticalRhythm } from "./blog-rhythm";
import {
  type FurnitureSufficiencyReport,
  type LayoutConfig,
  type SolvedChromeBox,
  type SolvedFurniture,
} from "./layout-types";
import { SERIF_TEXT_FONT, clamp, getSpanWidth } from "./layout-config";
import { rectsOverlap } from "./furniture";

export function layoutTextColumns({
  item,
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
  const preparedText = getPrepared(item, localConfig.bodyFont);
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

export function getPrepared(article: ArticlePublicationItem, font: string): PreparedTextWithSegments {
  return prepareWithSegmentsCached(getPublicationItemText(article), font, { whiteSpace: "pre-wrap" });
}

export function getLineLimitHeight(maxLines: number, lineHeight: number, linePaintHeight: number, rhythm: VerticalRhythm): number {
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

export function getColumnWhitespace(columns: TextLine[][], textHeight: number, furniture: SolvedFurniture[]): number {
  return columns.reduce(
    (total, column, columnIndex) =>
      total + Math.max(0, textHeight - getLinesHeight(column) - getColumnObstacleHeight(furniture, columnIndex, textHeight)),
    0,
  );
}

export function getFurnitureSufficiencyReport({
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

export function getDeadColumnCount(columns: TextLine[][], textHeight: number, furniture: SolvedFurniture[]): number {
  return columns.reduce((count, column, columnIndex) => {
    if (column.length > 0) return count;
    const obstacleHeight = getColumnObstacleHeight(furniture, columnIndex, textHeight);
    return obstacleHeight >= Math.min(96, textHeight * 0.18) ? count : count + 1;
  }, 0);
}

export function getLinesHeight(lines: TextLine[]): number {
  return lines.length === 0 ? 0 : Math.max(...lines.map((line) => line.y + line.paintHeight));
}

export function getFurnitureBottom(furniture: SolvedFurniture[]): number {
  return furniture.reduce((bottom, item) => Math.max(bottom, item.y + item.height), 0);
}
