"use client";

import { useEffect, useMemo, useRef, useState, type RefObject } from "react";
import type { ArticleImage, ArticleVideoAsset } from "../../lib/articles";
import { solveFeaturedFloatGeometry } from "../../lib/blog-feature-solver";
import type { ArticlePageEditionFooter } from "../../lib/renderer";
import { SITE_BRAND } from "../../lib/site-brand";
import type { VideoScriptRef } from "../../lib/video-script";
import { ArticleVideoFigure } from "../../components/article-video";
import { BlogPageBackground as GenericBlogPageBackground } from "../../components/blog-page-background";
import { PictogramFigure as GenericPictogramFigure } from "../../components/pictogram-figure";
import { PresentationFooter } from "../../components/presentation-footer";
import { PresentationHeader } from "../../components/presentation-header";
import { useBlogHeaderObstacles } from "../../components/use-blog-header-obstacles";
import { useRhythmOverlay } from "../../components/use-rhythm-overlay";
import { BLOG_RHYTHM, getFeaturedLayoutStyle, getRhythmShellStyle } from "./rhythm-shell-style";

const BlogPageBackground = SITE_BRAND.components?.BlogPageBackground ?? GenericBlogPageBackground;
const PictogramFigure = SITE_BRAND.components?.PictogramFigure ?? GenericPictogramFigure;

export type RhythmArticlePageProps = {
  body: string[];
  deck?: string;
  editionDate?: string;
  editionFooter?: ArticlePageEditionFooter;
  headline: string;
  image: ArticleImage | null;
  itemType?: string;
  section: string;
  slug: string;
  video: ArticleVideoAsset | null;
  videoScript: VideoScriptRef | null;
};

export function RhythmArticlePage({
  body,
  deck,
  editionDate,
  editionFooter,
  headline,
  image,
  itemType,
  section,
  slug,
  video,
  videoScript,
}: RhythmArticlePageProps) {
  const articleRef = useRef<HTMLElement | null>(null);
  const pageRef = useRef<HTMLElement | null>(null);
  const containerWidth = useMeasuredWidth(articleRef);
  const viewportWidth = useViewportWidth();
  const showRhythmOverlay = useRhythmOverlay();
  const headerObstacles = useBlogHeaderObstacles(pageRef, BLOG_RHYTHM.paintBuffer);
  const floatGeometry = useMemo(() => {
    if (!image || !containerWidth) return null;
    return solveFeaturedFloatGeometry({
      containerWidth,
      viewportWidth,
      rhythm: BLOG_RHYTHM,
      imageAsset: image,
      itemIndex: 0,
    });
  }, [containerWidth, image, viewportWidth]);

  const hasImage = Boolean(image);
  const articleClassName = hasImage ? "article-page article-float-grid" : "article-page";

  return (
    <main
      className={`${editionFooter ? "article-shell article-shell--edition" : "article-shell"} blog-rhythm-shell`}
      data-rhythm-overlay={showRhythmOverlay ? "true" : "false"}
      ref={pageRef}
      style={getRhythmShellStyle(BLOG_RHYTHM)}
    >
      <BlogPageBackground headerObstacles={headerObstacles} pageRef={pageRef} rhythm={BLOG_RHYTHM} />
      <PresentationHeader
        editionBasePath={editionFooter?.editionBasePath}
        editionDate={editionDate}
        sections={editionFooter?.sections}
      />
      <article
        className={articleClassName}
        data-feature-layout={hasImage ? (floatGeometry?.mode ?? "float") : undefined}
        data-has-image={hasImage ? "true" : "false"}
        data-item-type={itemType}
        ref={articleRef}
        style={floatGeometry ? getFeaturedLayoutStyle(floatGeometry) : undefined}
      >
        {video ? (
          <div className="article-page__hero-video">
            <ArticleVideoFigure slug={slug} video={video} videoScript={videoScript} />
          </div>
        ) : null}
        <header className={hasImage ? "article-float-grid__header" : undefined}>
          <p className="story-label">{section}</p>
          <h1>{headline}</h1>
          {deck ? <p className="article-deck">{deck}</p> : null}
        </header>
        {image ? (
          <div className="presentation-item__media article-float-grid__media">
            <PictogramFigure
              alt={image.alt}
              caption={image.caption}
              credit={image.credit}
              figureClassName="presentation-item__image"
              frameHeight={floatGeometry?.imageHeight}
              frameWidth={floatGeometry?.imageWidth}
              height={760}
              layout={image.layout}
              priority
              sizes="(max-width: 900px) 100vw, 760px"
              slug={slug}
              src={image.src}
              themeVariants={image.themeVariants}
              width={1200}
            />
          </div>
        ) : null}
        <div className={hasImage ? "article-body article-float-grid__body" : "article-body"}>
          {body.map((paragraph) => (
            <p key={paragraph}>{paragraph}</p>
          ))}
        </div>
      </article>
      {editionFooter ? (
        <PresentationFooter
          editionBasePath={editionFooter.editionBasePath}
          entries={editionFooter.entries}
          resolveSectionHref={(entry) => `${editionFooter.editionBasePath}#section-${entry.sectionKey}`}
          subtitle={editionFooter.subtitle}
          title={editionFooter.title}
        />
      ) : null}
    </main>
  );
}

function useMeasuredWidth(ref: RefObject<HTMLElement | null>): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const update = () => setWidth(Math.max(1, Math.floor(node.getBoundingClientRect().width)));
    update();
    const observer = new ResizeObserver(update);
    observer.observe(node);
    window.addEventListener("resize", update);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", update);
    };
  }, [ref]);
  return width;
}

function useViewportWidth(): number {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const update = () => setWidth(Math.max(1, Math.floor(window.innerWidth)));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  return width;
}
