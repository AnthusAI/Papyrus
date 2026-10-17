import assert from "node:assert/strict";
import { createDefaultBlogVerticalRhythm, reserveRhythmRows, snapToNearestRhythm } from "../lib/blog-rhythm";
import {
  getFeaturedLayoutMode,
  isFeaturedBlogItem,
  solveFeaturedFloatGeometry,
} from "../lib/blog-feature-solver";
import { layoutAllTextLines, prepareWithSegments } from "../lib/pretext-layout";
import type { PublicationItem } from "../lib/publication-items";

class FixedWidthOffscreenCanvas {
  getContext() {
    return {
      font: "",
      measureText: (text: string) => ({ width: text.length * 9 }),
    };
  }
}
(globalThis as { OffscreenCanvas?: unknown }).OffscreenCanvas = FixedWidthOffscreenCanvas;

const rhythm = createDefaultBlogVerticalRhythm();
assert.equal(rhythm.rowHeight, 16);
assert.equal(rhythm.paintHeight, 18);
assert.equal(snapToNearestRhythm(30, rhythm), 32);
assert.equal(reserveRhythmRows(30, rhythm), 32);

assert.equal(getFeaturedLayoutMode(1280, true), "float");
assert.equal(getFeaturedLayoutMode(900, true), "float");
assert.equal(getFeaturedLayoutMode(540, true), "float");
assert.equal(getFeaturedLayoutMode(540, false), "stacked");

const imageAsset = { layout: { aspectRatio: 1.5 } } as Parameters<typeof solveFeaturedFloatGeometry>[0]["imageAsset"];

const desktop = solveFeaturedFloatGeometry({ containerWidth: 800, viewportWidth: 1280, imageAsset, itemIndex: 0 });
assert.deepEqual(desktop, {
  mode: "float",
  imageHeight: 256,
  imageWidth: 384,
  captionHeight: 0,
  mediaHeight: 256,
  copyWidth: 384,
  gap: 32,
});

const tablet = solveFeaturedFloatGeometry({ containerWidth: 600, viewportWidth: 900, imageAsset, itemIndex: 0 });
assert.equal(tablet.imageWidth, 288);
assert.equal(tablet.gap, 32);

const phone = solveFeaturedFloatGeometry({ containerWidth: 360, viewportWidth: 390, imageAsset, itemIndex: 0 });
assert.equal(phone.imageWidth, 160);
assert.equal(phone.gap, 16, "narrow phone lead gap collapses to one rhythm row");

const trailing = solveFeaturedFloatGeometry({ containerWidth: 800, viewportWidth: 1280, imageAsset, itemIndex: 1 });
assert.equal(trailing.gap, 64, "non-lead items use the default four-row gap");

for (const geometry of [desktop, tablet, phone, trailing]) {
  assert.equal(geometry.imageHeight % rhythm.rowHeight, 0, "image height snaps to the rhythm");
  assert.equal(geometry.mediaHeight % rhythm.rowHeight, 0, "media height snaps to the rhythm");
  assert.equal(geometry.gap % rhythm.rowHeight, 0, "gap snaps to the rhythm");
}
for (const [viewportWidth, geometry] of [[1280, desktop], [900, tablet]] as const) {
  assert.ok(geometry.imageWidth <= Math.floor(viewportWidth / 3), "image width caps at one third of the viewport");
}

const articleGeometry = solveFeaturedFloatGeometry({
  containerWidth: 800,
  viewportWidth: 1280,
  imageAsset,
  itemIndex: 0,
  imageWidthRatio: 0.48,
  viewportImageCapRatio: 0.5,
  maxWidthRows: 24,
});
assert.equal(articleGeometry.imageWidth, 384);
assert.ok(articleGeometry.imageWidth <= 24 * rhythm.rowHeight);

const article = { type: "article" } as PublicationItem;
const brief = { type: "brief" } as PublicationItem;
const photo = { type: "photo" } as unknown as PublicationItem;
assert.equal(isFeaturedBlogItem(article, 0, "blog"), true);
assert.equal(isFeaturedBlogItem(brief, 0, "blog"), true);
assert.equal(isFeaturedBlogItem(article, 1, "blog"), false);
assert.equal(isFeaturedBlogItem(article, 0, "magazine"), false);
assert.equal(isFeaturedBlogItem(photo, 0, "blog"), false);

const prepared = prepareWithSegments("alpha beta gamma delta epsilon zeta eta theta iota kappa", "18px serif", {
  whiteSpace: "pre-wrap",
});
const options = {
  prepared,
  maxWidth: 200,
  lineHeight: 32,
  linePaintHeight: 32,
  fontSize: 18,
  fontFamily: "serif",
};
const openLines = layoutAllTextLines(options);
assert.ok(openLines.length > 0);
assert.ok(openLines.every((line, index) => line.x === 0 && line.y === index * 32));
const obstructedLines = layoutAllTextLines({
  ...options,
  obstacles: [{ x: 100, y: 0, width: 100, height: 64 }],
});
assert.ok(obstructedLines.slice(0, 2).every((line) => line.x + line.width <= 100 - 14 + 0.01));
assert.ok(obstructedLines.length >= openLines.length);

console.log("blog feature solver checks passed");
