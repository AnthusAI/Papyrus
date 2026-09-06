"use client";

import Image from "next/image";
import type { ArticleImageLayout, ArticleImageThemeVariants } from "../lib/articles";
import { shouldBypassImageOptimization } from "../lib/image-url";
import { resolveThemedImageSrc } from "../lib/themed-image";
import { useResolvedPapyrusTheme } from "./use-resolved-papyrus-theme";

export type PictogramFigureProps = {
  alt: string;
  caption?: string;
  credit: string;
  figureClassName: string;
  height: number;
  layout?: ArticleImageLayout;
  priority?: boolean;
  sizes: string;
  slug: string;
  src?: string;
  themeVariants?: ArticleImageThemeVariants;
  width: number;
};

/**
 * Generic media figure for publications without a bespoke pictogram system.
 * This is the default `renderers/pretext` falls back to for any publication
 * that isn't Threat Intelligence -- it mirrors the plain-image branch of
 * `publications/threat_intelligence/pictograms/figure.tsx` (the branch that
 * component itself already uses whenever a slug isn't a registered TI
 * pictogram), so behavior for a plain themed image is identical either way.
 */
export function PictogramFigure({
  alt,
  caption,
  credit,
  figureClassName,
  height,
  priority = false,
  sizes,
  src = "",
  themeVariants,
  width,
}: PictogramFigureProps) {
  const resolvedTheme = useResolvedPapyrusTheme();
  const themedImageSrc = resolveThemedImageSrc(src, themeVariants, resolvedTheme);

  if (!themedImageSrc) {
    return null;
  }

  return (
    <figure className={figureClassName}>
      <Image
        src={themedImageSrc}
        alt={alt}
        width={width}
        height={height}
        sizes={sizes}
        priority={priority}
        unoptimized={shouldBypassImageOptimization(themedImageSrc)}
      />
      <figcaption>{caption ?? credit}</figcaption>
    </figure>
  );
}
