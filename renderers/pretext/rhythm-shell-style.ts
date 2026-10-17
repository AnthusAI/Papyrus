import type { CSSProperties } from "react";
import {
  BLOG_COPY_ROW_MULTIPLE,
  createDefaultBlogVerticalRhythm,
  type VerticalRhythm,
} from "../../lib/blog-rhythm";

export const BLOG_RHYTHM: VerticalRhythm = createDefaultBlogVerticalRhythm();

export function getRhythmShellStyle(rhythm: VerticalRhythm): CSSProperties {
  return {
    "--blog-rhythm": `${rhythm.rowHeight / BLOG_COPY_ROW_MULTIPLE}px`,
    "--blog-row-height": `${rhythm.rowHeight}px`,
    "--blog-paint-buffer": `${rhythm.paintBuffer}px`,
    "--blog-paint-height": `${rhythm.paintHeight}px`,
  } as CSSProperties;
}

export function getFeaturedLayoutStyle(layout: {
  copyWidth: number;
  imageWidth: number;
  imageHeight: number;
  gap: number;
  mediaHeight?: number;
  textFrameHeight?: number;
}): CSSProperties {
  return {
    "--feature-copy-width": `${layout.copyWidth}px`,
    "--feature-image-width": `${layout.imageWidth}px`,
    "--feature-image-height": `${layout.imageHeight}px`,
    "--feature-layout-gap": `${layout.gap}px`,
    ...(layout.mediaHeight === undefined ? {} : { "--feature-media-height": `${layout.mediaHeight}px` }),
    ...(layout.textFrameHeight === undefined ? {} : { "--feature-text-frame-height": `${layout.textFrameHeight}px` }),
  } as CSSProperties;
}
