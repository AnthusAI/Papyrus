import type { ComponentType } from "react";
import type { Article } from "./articles";
import type { EditionContent, EditionPresentationFormat } from "./content-types";
import type { PresentationFooterEntry } from "./presentation-footer";
import type { PublicationItem } from "./publication-items";

/**
 * Renderer is the swappable render pipeline that turns standard content
 * (`EditionContent` / `PublicationItem` / `Article`) into a site: today
 * `"pretext"` (the existing client-side layout solver), with `"markus"`
 * (Anthus-flavored Markdown -> static HTML) as the second implementation
 * this shape is designed to admit. See docs/pluggable-publishers.md.
 *
 * `Layout` (`"newsprint" | "blog" | "magazine"`, `EditionPresentationFormat`
 * below) is a *Pretext-internal* concern -- it is the look within Pretext,
 * not a concept every renderer needs to understand. A renderer that isn't
 * Pretext may support none of these layouts; `supportsLayout` is how a
 * caller finds out.
 */
export type RendererId = "pretext" | "markus";

export type PresentationTarget =
  | { kind: "edition" }
  | { kind: "section"; sectionKey: string };

export type RenderEditionProps = {
  content: EditionContent;
  editionBasePath?: string;
  mastheadHomeHref?: string;
  initialPageNumber?: number;
  lockedPresentation?: EditionPresentationFormat;
  target?: PresentationTarget;
};

export type ArticlePageEditionFooter = {
  editionBasePath: string;
  entries: PresentationFooterEntry[];
  subtitle: string;
  title?: string;
};

export type RenderArticleProps = {
  article: Article;
  backHref: string;
  backLabel?: string;
  editionFooter?: ArticlePageEditionFooter;
  editionDate?: string;
};

export type RenderItemProps = {
  item: PublicationItem;
  backHref: string;
  backLabel?: string;
  editionFooter?: ArticlePageEditionFooter;
  editionDate?: string;
};

/**
 * The operations below are derived directly from real call sites, not
 * guessed:
 *
 * - `renderEdition` backs `PresentationShell`, used by the date-scoped
 *   edition route (`app/[year]/[month]/[day]/edition-route-page.tsx`).
 * - `renderArticle` / `renderItem` back `ArticlePageView` / `ItemPageView`,
 *   used directly by `app/articles/[slug]/page.tsx` and
 *   `app/[year]/[month]/[day]/[articleSlug]/page.tsx`.
 * - `stylesheets` lets a renderer declare CSS it owns. Pretext's CSS is not
 *   currently extracted from the monolithic `app/globals.css` bundle (it is
 *   imported unconditionally by `app/layout.tsx` regardless of renderer), so
 *   its implementation returns an empty array today -- this hook exists so a
 *   future static-output renderer (Markus's vendored + per-site CSS layers,
 *   see docs/pluggable-publishers.md section 6) has somewhere real to report
 *   the stylesheets it needs mounted.
 * - `supportsLayout` is the capability/validation hook: since Layout is
 *   Pretext-internal, a renderer must be able to say which layouts (if any)
 *   it understands, rather than every caller assuming all renderers share
 *   Pretext's three layouts.
 */
export type Renderer = {
  id: RendererId;
  renderEdition: ComponentType<RenderEditionProps>;
  renderArticle: ComponentType<RenderArticleProps>;
  renderItem: ComponentType<RenderItemProps>;
  stylesheets(): string[];
  supportsLayout(layout: EditionPresentationFormat): boolean;
};
