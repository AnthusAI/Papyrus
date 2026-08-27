"use client";

import { useEffect, useState } from "react";
import type { ArticleVideoAsset } from "@/lib/articles";
import { resolveThemedVideoSrc } from "@/lib/themed-image";
import { useResolvedPapyrusTheme } from "@/components/use-resolved-papyrus-theme";

type ArticleVideoFigureProps = {
  video: ArticleVideoAsset;
  slug: string;
  figureClassName?: string;
  priority?: boolean;
};

export function ArticleVideoFigure({ video, slug, figureClassName = "article-photo article-video" }: ArticleVideoFigureProps) {
  const theme = useResolvedPapyrusTheme();
  const [hasHydrated, setHasHydrated] = useState(false);

  useEffect(() => {
    setHasHydrated(true);
  }, []);

  // Match SSR to the default dark MP4 in `video.src` until after hydration.
  const resolvedTheme = hasHydrated ? theme : "dark";
  const src = resolveThemedVideoSrc(video.src, video.themeVariants, resolvedTheme);

  return (
    <figure className={figureClassName} data-media-type="video" data-video-theme={resolvedTheme}>
      <video
        controls
        playsInline
        preload="metadata"
        poster={video.posterSrc}
        aria-label={video.alt}
        className="article-video__player"
        key={hasHydrated ? src : "ssr"}
      >
        <source src={src} type="video/mp4" />
      </video>
      {video.caption ? <figcaption>{video.caption}</figcaption> : null}
      {video.credit ? <p className="article-video__credit">{video.credit}</p> : null}
      <span className="sr-only" data-video-slug={slug}>
        {video.alt}
      </span>
    </figure>
  );
}
