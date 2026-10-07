import {
  layoutNextLine,
  prepareWithSegments,
  type LayoutCursor,
  type LayoutLine,
  type PreparedTextWithSegments,
} from "@chenglou/pretext";

export { layoutNextLine, prepareWithSegments, type LayoutCursor, type PreparedTextWithSegments };

export type TextLine = {
  text: string;
  width: number;
  x: number;
  y: number;
  fontSize: number;
  fontFamily: string;
  lineHeight: number;
  paintHeight: number;
};

export type TextObstacle = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type LayoutTextLinesOptions = {
  prepared: PreparedTextWithSegments;
  cursor: LayoutCursor;
  maxHeight: number;
  maxWidth: number;
  lineHeight: number;
  linePaintHeight: number;
  fontSize: number;
  fontFamily: string;
  obstacles: TextObstacle[];
};

export function layoutTextLines({
  prepared,
  cursor,
  maxHeight,
  maxWidth,
  lineHeight,
  linePaintHeight,
  fontSize,
  fontFamily,
  obstacles,
}: LayoutTextLinesOptions): { lines: TextLine[]; cursor: LayoutCursor; hasMore: boolean } {
  const lines: TextLine[] = [];
  let current = { ...cursor };
  const maxLines = getVisibleLineCapacity(maxHeight, lineHeight, linePaintHeight);

  for (let lineIndex = 0; lineIndex < maxLines; lineIndex += 1) {
    const y = lineIndex * lineHeight;
    const slot = getAvailableSlot(maxWidth, y, linePaintHeight, obstacles);
    if (!slot) continue;
    const line = layoutNextLine(prepared, current, slot.width);
    if (!line) return { lines, cursor: current, hasMore: false };
    lines.push(toTextLine(line, slot.x, y, fontSize, fontFamily, lineHeight, linePaintHeight));
    current = line.end;
  }

  const nextSlot = getNextAvailableSlot(maxWidth, maxLines, lineHeight, linePaintHeight, obstacles) ?? { x: 0, width: maxWidth };
  return {
    lines,
    cursor: current,
    hasMore: layoutNextLine(prepared, current, nextSlot.width) !== null,
  };
}

export function layoutAllTextLines({
  prepared,
  maxWidth,
  lineHeight,
  linePaintHeight,
  fontSize,
  fontFamily,
  obstacles = [],
}: Omit<LayoutTextLinesOptions, "cursor" | "maxHeight" | "obstacles"> & { obstacles?: TextObstacle[] }): TextLine[] {
  const lines: TextLine[] = [];
  let cursor: LayoutCursor = { segmentIndex: 0, graphemeIndex: 0 };

  for (let lineIndex = 0; lineIndex < 2000; lineIndex += 1) {
    const y = lineIndex * lineHeight;
    const slot = getAvailableSlot(maxWidth, y, linePaintHeight, obstacles);
    if (!slot) continue;
    const line = layoutNextLine(prepared, cursor, slot.width);
    if (!line) return lines;
    lines.push(toTextLine(line, slot.x, y, fontSize, fontFamily, lineHeight, linePaintHeight));
    cursor = line.end;
  }

  return lines;
}

function getVisibleLineCapacity(maxHeight: number, lineHeight: number, linePaintHeight: number): number {
  if (maxHeight < linePaintHeight) return 0;
  return Math.floor((maxHeight - linePaintHeight) / lineHeight) + 1;
}

function getNextAvailableSlot(
  maxWidth: number,
  startLineIndex: number,
  lineHeight: number,
  linePaintHeight: number,
  obstacles: TextObstacle[],
): { x: number; width: number } | null {
  for (let offset = 0; offset < 24; offset += 1) {
    const slot = getAvailableSlot(maxWidth, (startLineIndex + offset) * lineHeight, linePaintHeight, obstacles);
    if (slot) return slot;
  }
  return null;
}

function getAvailableSlot(
  maxWidth: number,
  y: number,
  lineHeight: number,
  obstacles: TextObstacle[],
): { x: number; width: number } | null {
  if (obstacles.length === 0) return { x: 0, width: maxWidth };
  const bandTop = y;
  const bandBottom = y + lineHeight;
  const gutter = 14;
  const intervals = obstacles
    .filter((obstacle) => bandBottom > obstacle.y && bandTop < obstacle.y + obstacle.height)
    .map((obstacle) => ({
      start: clamp(obstacle.x - gutter, 0, maxWidth),
      end: clamp(obstacle.x + obstacle.width + gutter, 0, maxWidth),
    }))
    .filter((interval) => interval.end > interval.start)
    .sort((a, b) => a.start - b.start);

  if (intervals.length === 0) return { x: 0, width: maxWidth };

  const merged: Array<{ start: number; end: number }> = [];
  for (const interval of intervals) {
    const previous = merged[merged.length - 1];
    if (previous && interval.start <= previous.end) {
      previous.end = Math.max(previous.end, interval.end);
    } else {
      merged.push({ ...interval });
    }
  }

  const gaps: Array<{ x: number; width: number }> = [];
  let cursorX = 0;
  for (const interval of merged) {
    if (interval.start > cursorX) {
      gaps.push({ x: cursorX, width: interval.start - cursorX });
    }
    cursorX = Math.max(cursorX, interval.end);
  }
  if (cursorX < maxWidth) {
    gaps.push({ x: cursorX, width: maxWidth - cursorX });
  }

  const slot = gaps.reduce<{ x: number; width: number } | null>(
    (best, gap) => (!best || gap.width > best.width ? gap : best),
    null,
  );
  return slot && slot.width >= 80 ? slot : null;
}

function toTextLine(line: LayoutLine, x: number, y: number, fontSize: number, fontFamily: string, lineHeight: number, paintHeight: number): TextLine {
  return {
    text: line.text,
    width: line.width,
    x,
    y,
    fontSize,
    fontFamily,
    lineHeight,
    paintHeight,
  };
}

function clamp(value: number, min: number, max: number): number {
  return Math.max(min, Math.min(max, value));
}
