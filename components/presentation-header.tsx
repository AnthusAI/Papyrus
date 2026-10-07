"use client";

import Link from "next/link";
import { getEditionSectionPath } from "../lib/edition-routes";
import { SITE_BRAND } from "../lib/site-brand";

export type PresentationHeaderSection = {
  key: string;
  label: string;
};

export type PresentationHeaderProps = {
  editionDate?: string;
  title?: string;
  description?: string;
  sections?: PresentationHeaderSection[];
  editionBasePath?: string;
};

export function PresentationHeader({
  editionDate,
  title: contentTitle,
  description,
  sections,
  editionBasePath,
}: PresentationHeaderProps) {
  const title = SITE_BRAND.mastheadSource === "brand" ? SITE_BRAND.mastheadTitle : contentTitle;
  const subtitle = SITE_BRAND.mastheadSource === "brand" ? SITE_BRAND.mastheadSubtitle : description;
  const eyebrow = SITE_BRAND.mastheadEyebrow ?? null;
  const tagline = SITE_BRAND.mastheadTagline ?? null;
  const taglineLines = SITE_BRAND.mastheadTaglineLines ?? null;
  const displayDate = editionDate
    ? SITE_BRAND.mastheadDateFormat === "formatted"
      ? formatMastheadDate(editionDate)
      : editionDate
    : null;

  const eyebrowParts = eyebrow ? splitEyebrow(eyebrow) : null;

  return (
    <>
      <header className="presentation-header">
        <div className="presentation-header__copy-stack">
          {eyebrowParts ? (
            <span className="presentation-header__eyebrow">
              <span className="presentation-header__eyebrow-strong">{eyebrowParts.lead}</span>
              {eyebrowParts.rest ? (
                <span className="presentation-header__eyebrow-muted">{eyebrowParts.rest}</span>
              ) : null}
            </span>
          ) : null}
          <h1>
            {SITE_BRAND.mastheadWordSplit && title
              ? title.split(/\s+/).map((word) => (
                  <span className="presentation-header__word" key={word}>
                    <span className="presentation-header__word-text">{word}</span>
                  </span>
                ))
              : title}
          </h1>
          <div className="presentation-header__meta">
            {subtitle && !eyebrow ? <span className="presentation-header__subtitle">{subtitle}</span> : null}
            {displayDate ? <p className="presentation-header__date">{displayDate}</p> : null}
          </div>
        </div>
        {tagline ? (
          <span className="presentation-header__tagline">
            {taglineLines && taglineLines.length > 0
              ? taglineLines.map((line, index) => (
                  <span className="presentation-header__tagline-line" key={index}>
                    <span className="presentation-header__tagline-emphasis">{line.emphasis}</span>
                    <span className="presentation-header__tagline-tail">{line.tail}</span>
                    {index < taglineLines.length - 1 ? " " : null}
                  </span>
                ))
              : tagline}
          </span>
        ) : null}
      </header>
      {sections && sections.length > 0 ? (
        <nav className="presentation-section-nav" aria-label="Edition sections">
          {sections.map((section) => (
            <Link
              href={getSectionHref(section, { editionBasePath, editionDate })}
              key={section.key}
            >
              {section.label}
            </Link>
          ))}
        </nav>
      ) : null}
    </>
  );
}

function getSectionHref(
  section: PresentationHeaderSection,
  options: { editionBasePath?: string; editionDate?: string },
): string {
  if (SITE_BRAND.sectionLinkStrategy === "anchor") {
    const anchor = `#${getSectionAnchorId(section.key)}`;
    return options.editionBasePath ? `${options.editionBasePath}${anchor}` : anchor;
  }
  if (options.editionBasePath) {
    return `${options.editionBasePath}/section/${encodeURIComponent(section.key)}`;
  }
  if (options.editionDate) {
    const datedPath = getEditionSectionPath(options.editionDate, section.key);
    return datedPath.startsWith("//") ? `#${getSectionAnchorId(section.key)}` : datedPath;
  }
  return `#${getSectionAnchorId(section.key)}`;
}

export function getSectionAnchorId(sectionKey: string): string {
  return `section-${sectionKey}`;
}

function splitEyebrow(text: string): { lead: string; rest: string } {
  const trimmed = text.trim();
  const firstSpace = trimmed.indexOf(" ");
  if (firstSpace === -1) return { lead: trimmed, rest: "" };
  return { lead: trimmed.slice(0, firstSpace), rest: trimmed.slice(firstSpace + 1) };
}

export function formatMastheadDate(value: string): string {
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
