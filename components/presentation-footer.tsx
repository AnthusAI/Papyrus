"use client";

import Link from "next/link";
import type { CSSProperties, MouseEvent as ReactMouseEvent } from "react";
import {
  PRESENTATION_FOOTER_UTILITIES,
  type PresentationFooterEntry,
  type PresentationFooterGeometry,
  type PresentationFooterUtilityEntry,
} from "../lib/presentation-footer";
import { ReaderAuthControl } from "./reader-auth-control";

type PresentationFooterProps = {
  disableLinks?: boolean;
  editionBasePath?: string;
  entries: PresentationFooterEntry[];
  geometry?: PresentationFooterGeometry;
  onSectionClick?: (event: ReactMouseEvent<HTMLAnchorElement>, entry: PresentationFooterEntry, href: string) => void;
  resolveSectionHref: (entry: PresentationFooterEntry) => string;
  subtitle: string;
  utilityEntries?: PresentationFooterUtilityEntry[];
  variant?: "newspaper" | "presentation";
};

export function PresentationFooter({
  disableLinks = false,
  editionBasePath,
  entries,
  geometry,
  onSectionClick,
  resolveSectionHref,
  subtitle,
  utilityEntries = PRESENTATION_FOOTER_UTILITIES,
  variant = "presentation",
}: PresentationFooterProps) {
  const className = variant === "newspaper" ? "front-footer" : "front-footer front-footer--presentation";

  return (
    <footer
      aria-label="Publication footer"
      className={className}
      data-front-footer="true"
      data-presentation-footer={variant === "presentation" ? "true" : undefined}
      style={geometry ? getFooterGeometryStyle(geometry) : getPresentationFooterStyle(entries, utilityEntries)}
    >
      <div className="front-footer__heading">
        <span>{subtitle}</span>
        <span>{entries.length} sections</span>
      </div>
      {entries.length > 0 ? (
        <nav className="front-footer__sections" aria-label="Edition sections">
          {entries.map((entry) => {
            const href = resolveSectionHref(entry);
            if (disableLinks) {
              return (
                <span className="front-footer__section-link" data-footer-section={entry.section} key={`${entry.section}-${entry.articleSlug}`}>
                  <span className="front-footer__section-name">{entry.section}</span>
                  <span className="front-footer__section-title">{entry.articleTitle}</span>
                </span>
              );
            }
            return (
              <a
                className="front-footer__section-link"
                data-footer-section={entry.section}
                href={href}
                key={`${entry.section}-${entry.articleSlug}`}
                onClick={onSectionClick ? (event) => onSectionClick(event, entry, href) : undefined}
              >
                <span className="front-footer__section-name">{entry.section}</span>
                <span className="front-footer__section-title">{entry.articleTitle}</span>
              </a>
            );
          })}
        </nav>
      ) : null}
      <div className="front-footer__utilities" aria-label="Publication utilities">
        {utilityEntries.map((entry) => {
          if (entry.id === "newsDesk" && disableLinks) return null;

          if (entry.id === "login" && !disableLinks) {
            return (
              <ReaderAuthControl className="front-footer__utility-link" dataFooterUtility={entry.id} key={entry.id} postAuthPath={editionBasePath} />
            );
          }

          return entry.disabled || disableLinks ? (
            <span
              aria-disabled="true"
              className="front-footer__utility-link"
              data-footer-utility={entry.id}
              key={entry.id}
              role="link"
            >
              {entry.label}
            </span>
          ) : (
            <Link className="front-footer__utility-link" data-footer-utility={entry.id} href={entry.href} key={entry.id}>
              {entry.label}
            </Link>
          );
        })}
      </div>
    </footer>
  );
}

function getFooterGeometryStyle(geometry: PresentationFooterGeometry): CSSProperties {
  return {
    "--front-footer-height": `${geometry.height}px`,
    "--front-footer-margin-top": `${geometry.marginTop}px`,
    "--front-footer-row-height": `${geometry.rowHeight}px`,
    "--front-footer-section-columns": geometry.sectionColumns,
    "--front-footer-section-rows": geometry.sectionRows,
  } as CSSProperties;
}

function getPresentationFooterStyle(
  entries: PresentationFooterEntry[],
  utilityEntries: PresentationFooterUtilityEntry[],
): CSSProperties {
  const { sectionColumns, sectionRows } = getPresentationFooterGrid(entries.length, utilityEntries.length);
  return {
    "--front-footer-section-columns": sectionColumns,
    "--front-footer-section-rows": sectionRows,
    "--front-footer-utility-rows": utilityEntries.length,
  } as CSSProperties;
}

function getPresentationFooterGrid(entryCount: number, utilityCount: number) {
  const maxColumns = Math.max(1, Math.min(4, Math.max(entryCount, utilityCount)));
  const sectionColumns = entryCount === 0 ? 1 : Math.min(entryCount, maxColumns);
  const sectionRows = entryCount === 0 ? 0 : Math.ceil(entryCount / sectionColumns);
  return { sectionColumns, sectionRows };
}
