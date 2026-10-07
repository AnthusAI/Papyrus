"use client";

import type { CSSProperties, MouseEvent as ReactMouseEvent, RefObject } from "react";
import { useEffect, useState } from "react";
import type { EditionSection } from "../../lib/content-types";
import { truncateWords } from "../../lib/excerpts";
import type { PresentationFooterEntry } from "../../lib/presentation-footer";
import type { PublicationItem } from "../../lib/publication-items";
import type { TextLine } from "../../lib/pretext-layout";

export type PresentationItemMode = "blog" | "magazine" | "magazine-feature";

export function MeasuredPresentationLines({ lines }: { lines: TextLine[] }) {
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

export function useMeasuredWidth(ref: RefObject<HTMLElement | null>): number {
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

export function usePresentationTargetScroll(targetSection: EditionSection | undefined) {
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

export function getSectionAnchorId(sectionKey: string): string {
  return `section-${sectionKey}`;
}

export function getPresentationTitle(item: PublicationItem): string {
  return item.type === "article" ? item.headline : item.title;
}

export function getPresentationBodyText(item: PublicationItem, mode: PresentationItemMode): string {
  const body = item.type === "article" ? item.body.join("\n\n") : (item.body ?? []).join("\n\n");
  if (mode !== "blog") return body;
  const excerpt = String(item.excerpt ?? "").trim();
  if (excerpt) return excerpt;
  return truncateWords(body, 80);
}

export function parseItemAnchorHash(hash: string): string | null {
  if (!hash) return null;
  try {
    const value = decodeURIComponent(hash.slice(1)).trim();
    return /^[a-z0-9][a-z0-9-]*$/i.test(value) ? value : null;
  } catch {
    return null;
  }
}

export function getBlogFooterSectionHref(entry: PresentationFooterEntry, editionBasePath?: string): string {
  const anchor = `#${getSectionAnchorId(entry.sectionKey)}`;
  return editionBasePath ? `${editionBasePath}${anchor}` : anchor;
}

export function handleBlogFooterSectionClick(
  event: ReactMouseEvent<HTMLAnchorElement>,
  entry: PresentationFooterEntry,
  href: string,
) {
  event.preventDefault();
  window.history.pushState(null, "", href);
  document.getElementById(getSectionAnchorId(entry.sectionKey))?.scrollIntoView({ block: "start" });
}

export function getPresentationItemRole(mode: PresentationItemMode, index?: number): "lead" | "secondary" {
  if (mode === "magazine-feature") return "lead";
  if (mode === "blog" && index === 0) return "lead";
  return "secondary";
}
