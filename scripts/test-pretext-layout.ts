import assert from "node:assert/strict";

class FixedWidthOffscreenCanvas {
  getContext() {
    return {
      font: "",
      measureText: (text: string) => ({ width: text.length * 9 }),
    };
  }
}
(globalThis as { OffscreenCanvas?: unknown }).OffscreenCanvas = FixedWidthOffscreenCanvas;

import { layoutTextLines, prepareWithSegments } from "../lib/pretext-layout";

const LINE_HEIGHT = 20;
const LINE_PAINT_HEIGHT = 24;
const MAX_WIDTH = 180;
const LONG_TEXT = Array.from({ length: 120 }, (_, index) => `word${index}`).join(" ");
const SHORT_TEXT = "one two three";
const STARTING_CURSOR = { segmentIndex: 0, graphemeIndex: 0 };

function layoutWithHeight(text: string, maxHeight: number, obstacles: Parameters<typeof layoutTextLines>[0]["obstacles"] = []) {
  return layoutTextLines({
    prepared: prepareWithSegments(text, "16px serif"),
    cursor: STARTING_CURSOR,
    maxHeight,
    maxWidth: MAX_WIDTH,
    lineHeight: LINE_HEIGHT,
    linePaintHeight: LINE_PAINT_HEIGHT,
    fontSize: 16,
    fontFamily: "serif",
    obstacles,
  });
}

assert.equal(layoutWithHeight(LONG_TEXT, LINE_PAINT_HEIGHT - 1).lines.length, 0, "a height shorter than one paint box shows no line");
assert.equal(layoutWithHeight(LONG_TEXT, LINE_PAINT_HEIGHT).lines.length, 1, "exactly one paint box shows one line");
assert.equal(layoutWithHeight(LONG_TEXT, LINE_PAINT_HEIGHT + LINE_HEIGHT - 1).lines.length, 1, "a second line needs its full paint box");
assert.equal(layoutWithHeight(LONG_TEXT, LINE_PAINT_HEIGHT + LINE_HEIGHT).lines.length, 2, "a second line appears once its paint box fits");
assert.equal(layoutWithHeight(LONG_TEXT, LINE_PAINT_HEIGHT + LINE_HEIGHT * 4).lines.length, 5);

const truncated = layoutWithHeight(LONG_TEXT, LINE_PAINT_HEIGHT + LINE_HEIGHT * 2);
assert.equal(truncated.lines.length, 3);
assert.equal(truncated.hasMore, true, "hasMore probes past the last fully visible line");
assert.notDeepEqual(truncated.cursor, STARTING_CURSOR, "cursor advances past the visible lines");
for (const line of truncated.lines) {
  assert.equal(line.lineHeight, LINE_HEIGHT);
  assert.equal(line.paintHeight, LINE_PAINT_HEIGHT);
}

const resumed = layoutTextLines({
  prepared: prepareWithSegments(LONG_TEXT, "16px serif"),
  cursor: truncated.cursor,
  maxHeight: LINE_PAINT_HEIGHT,
  maxWidth: MAX_WIDTH,
  lineHeight: LINE_HEIGHT,
  linePaintHeight: LINE_PAINT_HEIGHT,
  fontSize: 16,
  fontFamily: "serif",
  obstacles: [],
});
assert.ok(!resumed.lines[0].text.startsWith(truncated.lines[0].text), "resuming from the returned cursor does not repeat earlier text");

const exhausted = layoutWithHeight(SHORT_TEXT, LINE_PAINT_HEIGHT + LINE_HEIGHT * 5);
assert.equal(exhausted.hasMore, false, "hasMore is false once the text runs out");

const fullWidthObstacleRow = layoutWithHeight(LONG_TEXT, LINE_PAINT_HEIGHT + LINE_HEIGHT * 3, [
  { x: 0, y: 0, width: MAX_WIDTH, height: LINE_HEIGHT },
]);
assert.equal(fullWidthObstacleRow.lines[0].y, LINE_HEIGHT, "a full-width obstacle row leaves the first line row empty");
assert.equal(fullWidthObstacleRow.lines.length, 3, "the blocked row still consumes visible line capacity");

console.log("pretext layout ok");
