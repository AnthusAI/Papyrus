"use client";

import Link from "next/link";
import type { CSSProperties, MouseEvent as ReactMouseEvent, ReactNode, RefObject } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { findEditionSection, getEditionSectionItems } from "../lib/edition-sections";
import { getEditionSectionPath } from "../lib/edition-routes";
import { buildPresentationFooterEntries, type PresentationFooterEntry } from "../lib/presentation-footer";
import { layoutAllTextLines, prepareWithSegments, type TextLine } from "../lib/pretext-layout";
import { truncateWords } from "../lib/excerpts";
import {
  getPublicationItemImageAssets,
  getPublicationItemVideoAsset,
  type PublicationItem,
} from "../lib/publication-items";
import type { EditionContent, EditionPresentationFormat, EditionSection } from "../lib/content-types";
import type { ArticleVideoAsset } from "../lib/articles";
import { SITE_BRAND, enforcePresentation } from "../lib/site-brand";
import { ArticleVideoFigure } from "./article-video";
import { BlogPageBackground } from "../publications/threat_intelligence/blog-defense/page-background";
import { Newspaper } from "./newspaper";
import { PictogramFigure } from "../publications/threat_intelligence/pictograms/figure";
import { PresentationFooter } from "./presentation-footer";
import { readLocalReaderSettings, resolveReaderSettings, subscribeReaderSettingsChanges } from "./reader-settings";

type PresentationShellProps = {
  content: EditionContent;
  editionBasePath?: string;
  mastheadHomeHref?: string;
  initialPageNumber?: number;
  lockedPresentation?: EditionPresentationFormat;
  target?: PresentationTarget;
};

export type PresentationTarget =
  | { kind: "edition" }
  | { kind: "section"; sectionKey: string };

const PRESENTATION_TEXT_FONT = SITE_BRAND.textFont;
const BLOG_TEXT_STYLE = {
  fontSize: 18,
  lineHeight: 28,
  linePaintHeight: 24,
  fontFamily: PRESENTATION_TEXT_FONT,
};
const MAGAZINE_TEXT_STYLE = {
  fontSize: 17,
  lineHeight: 25,
  linePaintHeight: 22,
  fontFamily: PRESENTATION_TEXT_FONT,
};

export function PresentationShell({
  content,
  editionBasePath,
  mastheadHomeHref,
  initialPageNumber = 1,
  lockedPresentation,
  target = { kind: "edition" },
}: PresentationShellProps) {
  const defaultPresentation = enforcePresentation(content.defaultPresentation ?? SITE_BRAND.defaultPresentation);
  const [preferredPresentation, setPreferredPresentation] = useState<EditionPresentationFormat>(defaultPresentation);
  const activePresentation = enforcePresentation(lockedPresentation ?? preferredPresentation);
  const targetSection = target.kind === "section" ? findEditionSection(content.sections, target.sectionKey) : undefined;

  useEffect(() => {
    if (lockedPresentation) return;
    const localSettings = readLocalReaderSettings();
    setPreferredPresentation(enforcePresentation(localSettings.presentation));
    const unsubscribe = subscribeReaderSettingsChanges((settings) => {
      setPreferredPresentation(enforcePresentation(settings.presentation));
    });
    void resolveReaderSettings()
      .then((resolution) => setPreferredPresentation(enforcePresentation(resolution.settings.presentation)))
      .catch(() => undefined);
    return unsubscribe;
  }, [lockedPresentation]);

  if (activePresentation === "newspaper") {
    return (
      <PresentationFrame>
        <Newspaper
          content={content}
          editionBasePath={editionBasePath}
          mastheadHomeHref={mastheadHomeHref}
          initialPageNumber={initialPageNumber}
          initialSectionKey={targetSection?.key}
          preserveContentLocation={Boolean(targetSection)}
        />
      </PresentationFrame>
    );
  }

  const presentationProps = {
    content,
    editionBasePath,
    targetSection,
  };

  return (
    <PresentationFrame>
      {activePresentation === "blog" ? (
        <BlogPresentation {...presentationProps} />
      ) : (
        <MagazinePresentation {...presentationProps} />
      )}
    </PresentationFrame>
  );
}

function PresentationFrame({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

function BlogPresentation({
  content,
  editionBasePath,
  targetSection,
}: {
  content: EditionContent;
  editionBasePath?: string;
  targetSection?: EditionSection;
}) {
  const sections = content.sections;
  const footerEntries = useMemo(() => buildPresentationFooterEntries(content), [content]);
  const footerSubtitle = SITE_BRAND.id === "papyrus" ? (content.description?.trim() || "Inside Papyrus") : SITE_BRAND.mastheadSubtitle;
  const contentRef = useRef<HTMLDivElement | null>(null);
  const pageRef = useRef<HTMLElement | null>(null);
  usePresentationTargetScroll(targetSection);
  return (
    <main className="presentation-page presentation-page--blog" data-presentation-engine="blog" ref={pageRef}>
      <BlogPageBackground pageRef={pageRef} />
      <PresentationHeader content={content} />
      <SectionNavigation content={content} editionBasePath={editionBasePath} />
      <div className="blog-sections" ref={contentRef}>
        {sections.map((section, sectionIndex) => (
          <section className="blog-section" data-edition-section={section.key} id={getSectionAnchorId(section.key)} key={section.key}>
            {sectionIndex === 0 && content.editionVideo ? (
              <EditionOverviewVideo editionVideo={content.editionVideo} />
            ) : null}
            <header className="presentation-section-header">
              <p>{section.label}</p>
              {section.description ? <span>{section.description}</span> : null}
            </header>
            {getEditionSectionItems(section, content.items).map((item, index) => (
              <PresentationItem
                editionBasePath={editionBasePath}
                index={index}
                item={item}
                key={item.slug}
                mode="blog"
              />
            ))}
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

function MagazinePresentation({
  content,
  editionBasePath,
  targetSection,
}: {
  content: EditionContent;
  editionBasePath?: string;
  targetSection?: EditionSection;
}) {
  const sections = targetSection ? [targetSection] : content.sections;
  usePresentationTargetScroll(targetSection);
  return (
    <main className="presentation-page presentation-page--magazine" data-presentation-engine="magazine">
      <PresentationHeader content={content} />
      <SectionNavigation content={content} editionBasePath={editionBasePath} />
      <div className="magazine-sections">
        {sections.map((section) => {
          const items = getEditionSectionItems(section, content.items);
          return (
            <section className="magazine-section" data-edition-section={section.key} id={getSectionAnchorId(section.key)} key={section.key}>
              <header className="presentation-section-header presentation-section-header--magazine">
                <p>{section.label}</p>
                {section.description ? <span>{section.description}</span> : null}
              </header>
              <div className="magazine-spread">
                {items.map((item, index) => (
                  <PresentationItem
                    editionBasePath={editionBasePath}
                    item={item}
                    key={item.slug}
                    mode={index === 0 ? "magazine-feature" : "magazine"}
                  />
                ))}
              </div>
            </section>
          );
        })}
      </div>
    </main>
  );
}

function EditionOverviewVideo({ editionVideo }: { editionVideo: ArticleVideoAsset }) {
  return (
    <section className="presentation-edition-video" aria-label={editionVideo.alt}>
      <ArticleVideoFigure
        figureClassName="presentation-edition-video__figure article-video"
        slug="edition-overview"
        video={editionVideo}
      />
    </section>
  );
}

function PresentationHeader({ content }: { content: EditionContent }) {
  const title = SITE_BRAND.mastheadSource === "brand" ? SITE_BRAND.mastheadTitle : content.title;
  const subtitle = SITE_BRAND.mastheadSource === "brand" ? SITE_BRAND.mastheadSubtitle : content.description;
  const tagline = SITE_BRAND.mastheadTagline ?? null;
  const displayDate = SITE_BRAND.mastheadDateFormat === "formatted"
    ? formatMastheadDate(content.editionDate)
    : content.editionDate;

  return (
    <header className="presentation-header">
      <div className="presentation-header__copy-stack">
        <h1>
          {SITE_BRAND.mastheadWordSplit
            ? title.split(/\s+/).map((word) => <span key={word}>{word}</span>)
            : title}
        </h1>
        <div className="presentation-header__meta">
          {subtitle ? <span className="presentation-header__subtitle">{subtitle}</span> : null}
          <p className="presentation-header__date">{displayDate}</p>
        </div>
        {tagline ? <span className="presentation-header__tagline">{tagline}</span> : null}
      </div>
    </header>
  );
}

function SectionNavigation({ content, editionBasePath }: { content: EditionContent; editionBasePath?: string }) {
  return (
    <nav className="presentation-section-nav" aria-label="Edition sections">
      {content.sections.map((section) => (
        <Link href={getSectionHref(content, section, editionBasePath)} key={section.key}>
          {section.label}
        </Link>
      ))}
    </nav>
  );
}

function PresentationItem({
  editionBasePath,
  index,
  item,
  mode,
}: {
  editionBasePath?: string;
  index?: number;
  item: PublicationItem;
  mode: "blog" | "magazine" | "magazine-feature";
}) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const maxWidth = useMeasuredWidth(frameRef);
  const image = getPublicationItemImageAssets(item)[0];
  const video = getPublicationItemVideoAsset(item);
  const textStyle = mode === "blog" ? BLOG_TEXT_STYLE : MAGAZINE_TEXT_STYLE;
  const text = getPresentationBodyText(item, mode);
  const itemRole = getPresentationItemRole(mode, index);
  const lines = useMemo(() => {
    if (!maxWidth || !text.trim()) return [];
    return layoutAllTextLines({
      prepared: prepareWithSegments(text, `${textStyle.fontSize}px ${textStyle.fontFamily}`),
      maxWidth,
      ...textStyle,
    });
  }, [maxWidth, text, textStyle]);
  const textHeight = getMeasuredTextHeight(lines);
  const directHref = editionBasePath ? `${editionBasePath}/${encodeURIComponent(item.slug)}` : `/articles/${encodeURIComponent(item.slug)}`;

  return (
    <article
      className={`presentation-item presentation-item--${mode}`}
      data-item-id={item.slug}
      data-item-index={index}
      data-item-role={itemRole}
      data-item-type={item.type}
      data-has-image={image ? "true" : "false"}
      data-has-video={video ? "true" : "false"}
      id={item.slug}
    >
      <div className="presentation-item__copy">
        <header className="presentation-item__header">
          <p>{item.section ?? "General"}</p>
          <h2>
            <Link href={directHref}>{getPresentationTitle(item)}</Link>
          </h2>
          {item.deck ? <span>{item.deck}</span> : null}
        </header>
        <div className="presentation-item__text-frame" ref={frameRef} style={{ height: textHeight }}>
          <MeasuredPresentationLines lines={lines} />
        </div>
        {mode === "blog" ? (
          <Link className="presentation-item__cta" href={directHref}>
            Read Article
          </Link>
        ) : null}
      </div>
      {image ? (
        <div className="presentation-item__media">
          <PictogramFigure
            alt={image.alt}
            caption={image.caption}
            credit={image.credit}
            figureClassName="presentation-item__image"
            height={760}
            layout={image.layout}
            sizes={mode === "blog" ? "(max-width: 900px) 100vw, 760px" : "(max-width: 900px) 100vw, 50vw"}
            slug={item.slug}
            src={image.src}
            themeVariants={image.themeVariants}
            width={1200}
          />
        </div>
      ) : null}
      {video && mode === "blog" ? (
        <div className="presentation-item__video">
          <ArticleVideoFigure
            figureClassName="presentation-item__video-figure article-video"
            slug={item.slug}
            video={video}
          />
        </div>
      ) : null}
    </article>
  );
}

function getPresentationItemRole(mode: "blog" | "magazine" | "magazine-feature", index?: number): "lead" | "secondary" {
  if (mode === "magazine-feature") return "lead";
  if (mode === "blog" && index === 0) return "lead";
  return "secondary";
}

function MeasuredPresentationLines({ lines }: { lines: TextLine[] }) {
  return (
    <div className="presentation-measured-lines">
      {lines.map((line, index) => (
        <span
          className="presentation-measured-line"
          key={`${index}-${line.text}`}
          style={{
            "--line-font-family": line.fontFamily,
            "--line-font-size": `${line.fontSize}px`,
            "--line-height": `${line.lineHeight}px`,
            "--line-paint-height": `${line.paintHeight}px`,
            left: line.x,
            top: line.y,
          } as CSSProperties}
        >
          {line.text}
        </span>
      ))}
    </div>
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

function usePresentationTargetScroll(targetSection: EditionSection | undefined) {
  useEffect(() => {
    const scrollToCurrentTarget = () => {
      const hashTarget = parseItemAnchorHash(window.location.hash);
      const targetId = hashTarget ?? (targetSection ? getSectionAnchorId(targetSection.key) : null);
      if (!targetId) return;
      document.getElementById(targetId)?.scrollIntoView({ block: "start" });
    };
    requestAnimationFrame(scrollToCurrentTarget);
    window.addEventListener("hashchange", scrollToCurrentTarget);
    return () => window.removeEventListener("hashchange", scrollToCurrentTarget);
  }, [targetSection]);
}

function getSectionHref(content: EditionContent, section: EditionSection, editionBasePath?: string): string {
  if (SITE_BRAND.sectionLinkStrategy === "anchor") {
    const anchor = `#${getSectionAnchorId(section.key)}`;
    return editionBasePath ? `${editionBasePath}${anchor}` : anchor;
  }
  if (editionBasePath) return `${editionBasePath}/section/${encodeURIComponent(section.key)}`;
  const datedPath = getEditionSectionPath(content.editionDate, section.key);
  return datedPath.startsWith("//") ? `#${getSectionAnchorId(section.key)}` : datedPath;
}

function getSectionAnchorId(sectionKey: string): string {
  return `section-${sectionKey}`;
}

function getMeasuredTextHeight(lines: TextLine[]): number {
  const last = lines[lines.length - 1];
  return last ? last.y + last.paintHeight : 0;
}

function getPresentationTitle(item: PublicationItem): string {
  return item.type === "article" ? item.headline : item.title;
}

function getPresentationBodyText(item: PublicationItem, mode: "blog" | "magazine" | "magazine-feature"): string {
  const body = item.type === "article" ? item.body.join("\n\n") : (item.body ?? []).join("\n\n");
  if (mode !== "blog") return body;
  const excerpt = String(item.excerpt ?? "").trim();
  if (excerpt) return excerpt;
  return truncateWords(body, 80);
}

function parseItemAnchorHash(hash: string): string | null {
  if (!hash) return null;
  try {
    const value = decodeURIComponent(hash.slice(1)).trim();
    return /^[a-z0-9][a-z0-9-]*$/i.test(value) ? value : null;
  } catch {
    return null;
  }
}

function formatMastheadDate(value: string): string {
  const normalized = value?.trim();
  if (!normalized) return value;
  const date = new Date(`${normalized}T00:00:00`);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en-US", {
    month: "long",
    day: "numeric",
    year: "numeric",
  }).format(date);
}

function getBlogFooterSectionHref(entry: PresentationFooterEntry, editionBasePath?: string): string {
  const anchor = `#${getSectionAnchorId(entry.sectionKey)}`;
  return editionBasePath ? `${editionBasePath}${anchor}` : anchor;
}

function handleBlogFooterSectionClick(
  event: ReactMouseEvent<HTMLAnchorElement>,
  entry: PresentationFooterEntry,
  href: string,
) {
  event.preventDefault();
  window.history.pushState(null, "", href);
  document.getElementById(getSectionAnchorId(entry.sectionKey))?.scrollIntoView({ block: "start" });
}
