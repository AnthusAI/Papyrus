"use client";

import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import { solveFeaturedItem } from "../../lib/blog-feature-solver";
import { createDefaultBlogTextStyle, getMeasuredTextHeight, reserveRhythmRows } from "../../lib/blog-rhythm";
import type { ArticleVideoAsset } from "../../lib/articles";
import type { EditionContent, EditionSection } from "../../lib/content-types";
import { getEditionSectionItems } from "../../lib/edition-sections";
import { layoutAllTextLines, prepareWithSegments } from "../../lib/pretext-layout";
import { buildPresentationFooterEntries } from "../../lib/presentation-footer";
import {
  getPublicationItemImageAssets,
  getPublicationItemVideoAsset,
  type PublicationItem,
} from "../../lib/publication-items";
import { SITE_BRAND } from "../../lib/site-brand";
import type { VideoScriptRef } from "../../lib/video-script";
import { ArticleVideoFigure } from "../../components/article-video";
import { BlogPageBackground as GenericBlogPageBackground } from "../../components/blog-page-background";
import { PictogramFigure as GenericPictogramFigure } from "../../components/pictogram-figure";
import { PresentationFooter } from "../../components/presentation-footer";
import { getSectionAnchorId, PresentationHeader } from "../../components/presentation-header";
import { PresentationRhythmHRule } from "../../components/presentation-rhythm-hrule";
import { useBlogHeaderObstacles } from "../../components/use-blog-header-obstacles";
import { useBrandFontsReadyVersion } from "../../components/use-brand-fonts-ready";
import { useRhythmOverlay } from "../../components/use-rhythm-overlay";
import {
  getBlogFooterSectionHref,
  getPresentationBodyText,
  getPresentationItemRole,
  getPresentationTitle,
  handleBlogFooterSectionClick,
  MeasuredPresentationLines,
  useMeasuredWidth,
  usePresentationTargetScroll,
} from "./presentation-shared";
import { BLOG_RHYTHM, getFeaturedLayoutStyle, getRhythmShellStyle } from "./rhythm-shell-style";

const BlogPageBackground = SITE_BRAND.components?.BlogPageBackground ?? GenericBlogPageBackground;
const PictogramFigure = SITE_BRAND.components?.PictogramFigure ?? GenericPictogramFigure;
const BLOG_TEXT_STYLE = createDefaultBlogTextStyle(SITE_BRAND.textFont);
const EDITION_OVERVIEW_VIDEO_KEY = "edition-overview";
const SECONDARY_PAIR_ITEM_INDEX = 2;

type PapyrusTestWindow = Window & typeof globalThis & {
  __PAPYRUS_SCENARIO__?: string;
};

export function RhythmBlogPresentation({
  content,
  editionBasePath,
  targetSection,
}: {
  content: EditionContent;
  editionBasePath?: string;
  targetSection?: EditionSection;
}) {
  const footerEntries = useMemo(() => buildPresentationFooterEntries(content), [content]);
  const footerSubtitle = SITE_BRAND.id === "papyrus" ? (content.description?.trim() || "Inside Papyrus") : SITE_BRAND.mastheadSubtitle;
  const pageRef = useRef<HTMLElement | null>(null);
  const showRhythmOverlay = useRhythmOverlay();
  const headerObstacles = useBlogHeaderObstacles(pageRef, BLOG_RHYTHM.paintBuffer);
  usePresentationTargetScroll(targetSection);
  useEffect(() => {
    (window as PapyrusTestWindow).__PAPYRUS_SCENARIO__ = content.scenarioId;
    return () => {
      delete (window as PapyrusTestWindow).__PAPYRUS_SCENARIO__;
    };
  }, [content.scenarioId]);

  return (
    <main
      className="presentation-page presentation-page--blog blog-rhythm-shell"
      data-presentation-engine="blog"
      data-rhythm-overlay={showRhythmOverlay ? "true" : "false"}
      ref={pageRef}
      style={getRhythmShellStyle(BLOG_RHYTHM)}
    >
      <BlogPageBackground headerObstacles={headerObstacles} pageRef={pageRef} rhythm={BLOG_RHYTHM} />
      <PresentationHeader
        description={content.description}
        editionBasePath={editionBasePath}
        editionDate={content.editionDate}
        sections={content.sections}
        title={content.title}
      />
      <div className="blog-sections">
        {content.sections.map((section, sectionIndex) => (
          <section className="blog-section" data-edition-section={section.key} id={getSectionAnchorId(section.key)} key={section.key}>
            {sectionIndex === 0 && content.editionVideo ? (
              <EditionOverviewVideo
                editionVideo={content.editionVideo}
                videoScript={content.videoScripts?.[EDITION_OVERVIEW_VIDEO_KEY] ?? null}
              />
            ) : null}
            <header className="presentation-section-header">
              <div className="presentation-section-header__band">
                <p>{section.label}</p>
              </div>
              {section.description ? <span>{section.description}</span> : null}
            </header>
            {getEditionSectionItems(section, content.items).flatMap((item, index) => [
              ...(index > 0
                ? [
                    <PresentationRhythmHRule
                      hideInSecondaryPair={index === SECONDARY_PAIR_ITEM_INDEX}
                      key={`hrule-before-${item.slug}`}
                    />,
                  ]
                : []),
              <RhythmPresentationItem
                editionBasePath={editionBasePath}
                index={index}
                item={item}
                key={item.slug}
                videoScript={content.videoScripts?.[item.slug] ?? null}
              />,
            ])}
          </section>
        ))}
      </div>
      <PresentationFooter
        editionBasePath={editionBasePath}
        entries={footerEntries}
        onSectionClick={handleBlogFooterSectionClick}
        resolveSectionHref={(entry) => getBlogFooterSectionHref(entry, editionBasePath)}
        subtitle={SITE_BRAND.footerSubtitleOverride ?? footerSubtitle}
        title={SITE_BRAND.footerTitle}
      />
    </main>
  );
}

function EditionOverviewVideo({
  editionVideo,
  videoScript,
}: {
  editionVideo: ArticleVideoAsset;
  videoScript: VideoScriptRef | null;
}) {
  return (
    <section className="presentation-edition-video" aria-label={editionVideo.alt}>
      <ArticleVideoFigure
        figureClassName="presentation-edition-video__figure article-video"
        slug={EDITION_OVERVIEW_VIDEO_KEY}
        video={editionVideo}
        videoScript={videoScript}
      />
    </section>
  );
}

function RhythmPresentationItem({
  editionBasePath,
  index,
  item,
  videoScript,
}: {
  editionBasePath?: string;
  index: number;
  item: PublicationItem;
  videoScript: VideoScriptRef | null;
}) {
  const articleRef = useRef<HTMLElement | null>(null);
  const frameRef = useRef<HTMLDivElement | null>(null);
  const containerWidth = useMeasuredWidth(articleRef);
  const frameWidth = useMeasuredWidth(frameRef);
  const viewportWidth = useViewportWidth();
  const fontsReadyVersion = useBrandFontsReadyVersion();
  const textStyle = useMemo(() => ({ ...BLOG_TEXT_STYLE, fontsReadyVersion }), [fontsReadyVersion]);
  const image = getPublicationItemImageAssets(item)[0];
  const video = getPublicationItemVideoAsset(item);
  const text = getPresentationBodyText(item, "blog");
  const hasImage = Boolean(image);
  const featuredLayout = useMemo(() => {
    if (!hasImage || !containerWidth || !image) return null;
    return solveFeaturedItem({
      text,
      containerWidth,
      viewportWidth,
      rhythm: BLOG_RHYTHM,
      textStyle,
      imageAsset: image,
      itemIndex: index,
    });
  }, [containerWidth, hasImage, image, index, text, textStyle, viewportWidth]);
  const lines = useMemo(() => {
    if (featuredLayout) return featuredLayout.textLines;
    const maxWidth = frameWidth || containerWidth;
    if (!maxWidth || !text.trim()) return [];
    return layoutAllTextLines({
      prepared: prepareWithSegments(text, `${textStyle.fontSize}px ${textStyle.fontFamily}`, { whiteSpace: "pre-wrap" }),
      maxWidth,
      ...textStyle,
    });
  }, [containerWidth, featuredLayout, frameWidth, text, textStyle]);
  const textHeight = featuredLayout?.textFrameHeight ?? reserveRhythmRows(getMeasuredTextHeight(lines), BLOG_RHYTHM);
  const layoutMode = featuredLayout?.mode ?? "stacked";
  const directHref = editionBasePath ? `${editionBasePath}/${encodeURIComponent(item.slug)}` : `/articles/${encodeURIComponent(item.slug)}`;

  return (
    <article
      className="presentation-item presentation-item--blog"
      data-feature-layout={hasImage ? layoutMode : undefined}
      data-has-image={hasImage ? "true" : "false"}
      data-has-video={video ? "true" : "false"}
      data-item-id={item.slug}
      data-item-index={index}
      data-item-role={getPresentationItemRole("blog", index)}
      data-item-type={item.type}
      id={item.slug}
      ref={articleRef}
      style={featuredLayout ? getFeaturedLayoutStyle(featuredLayout) : undefined}
    >
      <div className="presentation-item__copy">
        <header className="presentation-item__header">
          <p>{item.section ?? "General"}</p>
          <h2>
            <Link href={directHref}>{getPresentationTitle(item)}</Link>
          </h2>
          {item.deck ? <span>{item.deck}</span> : null}
        </header>
        <div className="presentation-item__body">
          {image ? (
            <div className="presentation-item__media">
              <PictogramFigure
                alt={image.alt}
                caption={image.caption}
                credit={image.credit}
                figureClassName="presentation-item__image"
                frameHeight={featuredLayout?.imageHeight}
                frameWidth={featuredLayout?.imageWidth}
                height={760}
                layout={image.layout}
                sizes="(max-width: 900px) 100vw, 760px"
                slug={item.slug}
                src={image.src}
                themeVariants={image.themeVariants}
                width={1200}
              />
            </div>
          ) : null}
          <div
            className="presentation-item__text-frame"
            data-layout-mode={layoutMode}
            ref={frameRef}
            style={{ height: textHeight }}
          >
            <MeasuredPresentationLines lines={lines} />
          </div>
          <Link className="presentation-item__cta" href={directHref}>
            Read Article
          </Link>
        </div>
      </div>
      {video ? (
        <div className="presentation-item__video">
          <ArticleVideoFigure
            figureClassName="presentation-item__video-figure article-video"
            slug={item.slug}
            video={video}
            videoScript={videoScript}
          />
        </div>
      ) : null}
    </article>
  );
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
