"use client";

import Image from "next/image";
import type { ArticleImageLayout, ArticleImageThemeVariants } from "../../../lib/articles";
import { shouldBypassImageOptimization } from "../../../lib/image-url";
import { resolveThemedImageSrc } from "../../../lib/themed-image";
import {
  getThreatIntelligencePictogramPhaseOffset,
  isThreatIntelligencePictogramSlug,
} from "./registry";
import { useResolvedPapyrusTheme } from "../../../components/use-resolved-papyrus-theme";
import { THREAT_INTELLIGENCE_PICTOGRAM_REGISTRY } from "./art";
import { PICTOGRAM_PALETTE, PictogramFrame, usePictogramMotion } from "./system";

type PictogramFigureProps = {
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

export function PictogramFigure({
  alt,
  caption,
  credit,
  figureClassName,
  height,
  layout,
  priority = false,
  sizes,
  slug,
  src = "",
  themeVariants,
  width,
}: PictogramFigureProps) {
  const resolvedTheme = useResolvedPapyrusTheme();
  const themedImageSrc = resolveThemedImageSrc(src, themeVariants, resolvedTheme);
  const registeredSlug = isThreatIntelligencePictogramSlug(slug) ? slug : null;
  const motionState = usePictogramMotion(registeredSlug ? getThreatIntelligencePictogramPhaseOffset(registeredSlug) : 0);

  if (!registeredSlug) {
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

  const entry = THREAT_INTELLIGENCE_PICTOGRAM_REGISTRY[registeredSlug];
  const palette = PICTOGRAM_PALETTE;
  const aspectRatio = layout?.aspectRatio ?? entry.aspectRatio ?? 1;
  const Pictogram = entry.render;

  return (
    <figure className={`${figureClassName} pictogram-figure`} data-pictogram-slug={slug}>
      <PictogramFrame aspectRatio={aspectRatio}>
        <Pictogram alt={alt} palette={palette} timing={motionState} />
      </PictogramFrame>
      <figcaption>{caption ?? credit}</figcaption>
    </figure>
  );
}
