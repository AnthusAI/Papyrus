"use client";

import type { RefObject } from "react";

/** A rectangle, in the background layer's own coordinates, that header text occupies. */
export type BlogHeaderObstacle = {
  x: number;
  y: number;
  width: number;
  height: number;
};

/** Vertical rhythm grid the rhythm blog layout is built on. */
export type BlogBackgroundRhythm = {
  rowHeight: number;
  paintBuffer: number;
  paintHeight: number;
};

export type BlogPageBackgroundProps = {
  pageRef: RefObject<HTMLElement | null>;
  /** Rhythm blog layout only: header text boxes the artwork should keep clear of. */
  headerObstacles?: BlogHeaderObstacle[];
  /** Rhythm blog layout only: the rhythm grid, so artwork can align to it. */
  rhythm?: BlogBackgroundRhythm;
};

/**
 * Default (no-op) blog page background for publications without a bespoke
 * backdrop. A publication supplies header artwork through the
 * `components.BlogPageBackground` brand slot; with the rhythm blog layout the
 * slot also receives `headerObstacles` and `rhythm`. This is what
 * `renderers/pretext` falls back to when no slot component is registered.
 */
export function BlogPageBackground(_props: BlogPageBackgroundProps) {
  return null;
}
