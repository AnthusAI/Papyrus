"use client";

import type { RefObject } from "react";

export type BlogPageBackgroundProps = {
  pageRef: RefObject<HTMLElement | null>;
};

/**
 * Default (no-op) blog page background for publications without a bespoke
 * backdrop. Threat Intelligence supplies its own animated defense-graph
 * background (publications/threat_intelligence/blog-defense/page-background.tsx);
 * every other publication gets no decorative background layer. This is what
 * `renderers/pretext` falls back to for any publication that isn't Threat
 * Intelligence, so the blog layout loads cleanly without depending on TI's
 * package.
 */
export function BlogPageBackground(_props: BlogPageBackgroundProps) {
  return null;
}
