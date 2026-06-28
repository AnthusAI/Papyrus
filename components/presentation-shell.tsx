"use client";

import Image from "next/image";
import Link from "next/link";
import type { CSSProperties, MouseEvent as ReactMouseEvent, ReactNode, RefObject } from "react";
import { useEffect, useMemo, useRef, useState } from "react";
import { findEditionSection, getEditionSectionItems } from "../lib/edition-sections";
import { getEditionSectionPath } from "../lib/edition-routes";
import { shouldBypassImageOptimization } from "../lib/image-url";
import { layoutAllTextLines, prepareWithSegments, type TextLine } from "../lib/pretext-layout";
import {
  getPublicationItemImageAssets,
  type PublicationItem,
} from "../lib/publication-items";
import type { EditionContent, EditionPresentationFormat, EditionSection } from "../lib/content-types";
import {
  buildPresentationFooterEntries,
  getPresentationFooterSubtitle,
  type PresentationFooterEntry,
} from "../lib/presentation-footer";
import { Newspaper } from "./newspaper";
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

const SERIF_TEXT_FONT = 'Georgia, "Times New Roman", serif';
const BLOG_TEXT_STYLE = {
  fontSize: 18,
  lineHeight: 28,
  linePaintHeight: 24,
  fontFamily: SERIF_TEXT_FONT,
};
const MAGAZINE_TEXT_STYLE = {
  fontSize: 17,
  lineHeight: 25,
  linePaintHeight: 22,
  fontFamily: SERIF_TEXT_FONT,
};

export function PresentationShell({
  content,
  editionBasePath,
  mastheadHomeHref,
  initialPageNumber = 1,
  lockedPresentation,
  target = { kind: "edition" },
}: PresentationShellProps) {
  const defaultPresentation = content.defaultPresentation ?? "newspaper";
  const [preferredPresentation, setPreferredPresentation] = useState<EditionPresentationFormat>(defaultPresentation);
  const activePresentation = lockedPresentation ?? preferredPresentation;
  const targetSection = target.kind === "section" ? findEditionSection(content.sections, target.sectionKey) : undefined;

  useEffect(() => {
    if (lockedPresentation) return;
    const localSettings = readLocalReaderSettings();
    setPreferredPresentation(localSettings.presentation);
    const unsubscribe = subscribeReaderSettingsChanges((settings) => {
      setPreferredPresentation(settings.presentation);
    });
    void resolveReaderSettings()
      .then((resolution) => setPreferredPresentation(resolution.settings.presentation))
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
  const sections = targetSection ? [targetSection] : content.sections;
  const footerEntries = useMemo(() => buildPresentationFooterEntries(content), [content]);
  usePresentationTargetScroll(targetSection);
  return (
    <main className="presentation-page presentation-page--blog" data-presentation-engine="blog">
      <PresentationHeader content={content} />
      <SectionNavigation content={content} editionBasePath={editionBasePath} />
      <div className="blog-sections">
        {sections.map((section) => (
          <section className="blog-section" data-edition-section={section.key} id={getSectionAnchorId(section.key)} key={section.key}>
            <header className="presentation-section-header">
              <p>{section.label}</p>
              {section.description ? <span>{section.description}</span> : null}
            </header>
            {getEditionSectionItems(section, content.items).map((item) => (
              <PresentationItem
                editionBasePath={editionBasePath}
                item={item}
                key={item.slug}
                mode="blog"
              />
            ))}
          </section>
        ))}
      </div>
      {!targetSection ? (
        <PresentationFooter
          editionBasePath={editionBasePath}
          entries={footerEntries}
          onSectionClick={handleBlogFooterSectionClick}
          resolveSectionHref={(entry) => getBlogFooterSectionHref(entry, editionBasePath)}
          subtitle={getPresentationFooterSubtitle(content)}
        />
      ) : null}
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

function PresentationHeader({ content }: { content: EditionContent }) {
  return (
    <header className="presentation-header">
      <p>{content.editionDate}</p>
      <h1>{content.title}</h1>
      {content.description ? <span>{content.description}</span> : null}
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
  item,
  mode,
}: {
  editionBasePath?: string;
  item: PublicationItem;
  mode: "blog" | "magazine" | "magazine-feature";
}) {
  const frameRef = useRef<HTMLDivElement | null>(null);
  const maxWidth = useMeasuredWidth(frameRef);
  const image = getPublicationItemImageAssets(item)[0];
  const textStyle = mode === "blog" ? BLOG_TEXT_STYLE : MAGAZINE_TEXT_STYLE;
  const text = getPresentationBodyText(item);
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
      data-item-type={item.type}
      id={item.slug}
    >
      <header className="presentation-item__header">
        <p>{item.section ?? "General"}</p>
        <h2>
          <Link href={directHref}>{getPresentationTitle(item)}</Link>
        </h2>
        {item.deck ? <span>{item.deck}</span> : null}
      </header>
      {image ? (
        <figure className="presentation-item__image">
          <Image
            src={image.src}
            alt={image.alt}
            width={1200}
            height={760}
            sizes={mode === "blog" ? "(max-width: 900px) 100vw, 760px" : "(max-width: 900px) 100vw, 50vw"}
            unoptimized={shouldBypassImageOptimization(image.src)}
          />
          <figcaption>{image.caption ?? image.credit}</figcaption>
        </figure>
      ) : null}
      <div className="presentation-item__text-frame" ref={frameRef} style={{ height: textHeight }}>
        <MeasuredPresentationLines lines={lines} />
      </div>
    </article>
  );
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

function getPresentationBodyText(item: PublicationItem): string {
  return item.type === "article" ? item.body.join("\n\n") : (item.body ?? []).join("\n\n");
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

function getBlogFooterSectionHref(entry: PresentationFooterEntry, editionBasePath?: string): string {
  const anchor = `#${encodeURIComponent(entry.articleSlug)}`;
  return editionBasePath ? `${editionBasePath}${anchor}` : anchor;
}

function handleBlogFooterSectionClick(
  event: ReactMouseEvent<HTMLAnchorElement>,
  entry: PresentationFooterEntry,
  href: string,
) {
  event.preventDefault();
  window.history.pushState(null, "", href);
  document.getElementById(entry.articleSlug)?.scrollIntoView({ block: "start" });
}
