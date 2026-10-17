import assert from "node:assert/strict";
import {
  BLOG_COPY_ROW_MULTIPLE,
  BLOG_PAINT_BUFFER_PX,
  BLOG_RHYTHM_UNIT,
  clampRhythmHeight,
  createDefaultBlogTextStyle,
  createDefaultBlogVerticalRhythm,
  createVerticalRhythm,
  getLineStackHeight,
  getMeasuredTextHeight,
  reserveRhythmRows,
  rhythmLength,
  rhythmRows,
  snapDownToRhythm,
  snapPreferredHeightToRhythm,
  snapPreservedImageHeightToRhythm,
  snapRhythmCoordinate,
  snapToNearestRhythm,
  snapUpToRhythm,
} from "../lib/blog-rhythm";
import type { TextLine } from "../lib/pretext-layout";

const rhythm = createDefaultBlogVerticalRhythm();
assert.equal(BLOG_RHYTHM_UNIT * BLOG_COPY_ROW_MULTIPLE, 16);
assert.equal(rhythm.rowHeight, 16);
assert.equal(rhythm.paintHeight, 16 + BLOG_PAINT_BUFFER_PX);
assert.equal(rhythm.paintBuffer, BLOG_PAINT_BUFFER_PX);
assert.deepEqual(createVerticalRhythm(24, 4), { rowHeight: 24, paintHeight: 28, paintBuffer: 4 });

assert.equal(snapToNearestRhythm(30, rhythm), 32);
assert.equal(snapToNearestRhythm(23, rhythm), 16);
assert.equal(reserveRhythmRows(30, rhythm), 32);
assert.equal(snapUpToRhythm(17, rhythm), 32);
assert.equal(snapUpToRhythm(32, rhythm), 32);
assert.equal(snapDownToRhythm(31, rhythm), 16);
assert.equal(snapDownToRhythm(32, rhythm), 32);
for (const snap of [snapUpToRhythm, snapDownToRhythm, snapToNearestRhythm, reserveRhythmRows, snapRhythmCoordinate]) {
  assert.equal(snap(0, rhythm), 0);
  assert.equal(snap(-5, rhythm), 0);
}
assert.equal(snapRhythmCoordinate(40, rhythm), 48);

assert.equal(clampRhythmHeight(10, 20, 100, rhythm), 32);
assert.equal(clampRhythmHeight(500, 20, 100, rhythm), 96);
assert.equal(clampRhythmHeight(50, 20, 100, rhythm), 64);
assert.equal(clampRhythmHeight(50, 100, 20, rhythm), 112);

assert.equal(snapPreferredHeightToRhythm(40, rhythm), 32);
assert.equal(snapPreferredHeightToRhythm(35, rhythm), 32);
assert.equal(snapPreferredHeightToRhythm(45, rhythm), 48);
assert.equal(snapPreferredHeightToRhythm(5, rhythm, 32), 32);
assert.equal(snapPreferredHeightToRhythm(200, rhythm, 16, 100), 16);
assert.equal(snapPreservedImageHeightToRhythm(35, rhythm), 48);
assert.equal(snapPreservedImageHeightToRhythm(200, rhythm, 16, 100), 96);
assert.equal(snapPreservedImageHeightToRhythm(5, rhythm, 32), 32);

assert.equal(rhythmRows(48, rhythm), 3);
assert.equal(rhythmRows(-48, rhythm), 0);
assert.equal(rhythmLength(3, rhythm), 48);

const textStyle = createDefaultBlogTextStyle("Serif");
assert.equal(textStyle.fontSize, 18);
assert.equal(textStyle.lineHeight, 32);
assert.equal(textStyle.linePaintHeight, 32);
assert.equal(textStyle.fontFamily, "Serif");
assert.ok(textStyle.lineHeight >= textStyle.fontSize * 1.5, "copy keeps one blank rhythm row between lines");

assert.equal(getLineStackHeight(0, 32, 18), 0);
assert.equal(getLineStackHeight(1, 32, 18), 18);
assert.equal(getLineStackHeight(3, 32, 18), 82);

const measuredLine = (y: number): TextLine => ({
  text: "",
  width: 0,
  x: 0,
  y,
  fontSize: 18,
  fontFamily: "Serif",
  lineHeight: 32,
  paintHeight: 32,
});
assert.equal(getMeasuredTextHeight([]), 0);
assert.equal(getMeasuredTextHeight([measuredLine(0), measuredLine(32)]), 64);

console.log("blog rhythm checks passed");
