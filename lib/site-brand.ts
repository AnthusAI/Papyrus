import type { ComponentType } from "react";
import type { EditionPresentationFormat } from "./content-types";
import type { Article, ArticleVideoAsset } from "./articles";
import type { BlogPageBackgroundProps } from "../components/blog-page-background";
import type { PictogramFigureProps } from "../components/pictogram-figure";
import papyrusSite from "papyrus-site";
import {
  DEFAULT_THEME_PACK_TOKENS,
  type HostingConfig,
  type OpsChrome,
  type ReaderDeployment,
  type RendererConfig,
  type RootRouteConfig,
  type ThemePackId,
  type ThemePackTokens,
} from "./site-stack";

/** Open string: a publication registers its own brand through `papyrus.config.ts` (`defineSite`). */
export type SiteBrandId = string;

/** Brand-specific replacements for generic Pretext components. */
export type SiteBrandComponents = {
  PictogramFigure?: ComponentType<PictogramFigureProps>;
  BlogPageBackground?: ComponentType<BlogPageBackgroundProps>;
};

/** Default scenario content a brand supplies for the layout lab. */
export type SiteBrandDemoEdition = {
  title: string;
  editionDate: string;
  description: string;
  articles: Article[];
  suppressNewsDeskAppendix?: boolean;
  editionVideo?: ArticleVideoAsset;
};

export type SiteBrand = {
  id: SiteBrandId;
  appTitle: string;
  appDescription: string;
  mastheadTitle: string;
  mastheadSubtitle: string;
  mastheadTagline?: string;
  backToHomeLabel: string;
  articleTitleSuffix: string;
  placeholderByline: string;
  defaultPresentation: EditionPresentationFormat;
  forcedPresentation?: EditionPresentationFormat;
  textFont: string;
  footerTitle?: string;
  footerSubtitleOverride?: string;
  mastheadWordSplit: boolean;
  mastheadDateFormat: "raw" | "formatted";
  mastheadSource: "edition" | "brand";
  sectionLinkStrategy: "route" | "anchor";
  defaultVideoCredit?: string;
  themePack: ThemePackId;
  themeTokens: ThemePackTokens;
  renderer: RendererConfig;
  hosting: HostingConfig;
  /** Static reader app when it is not co-hosted with this Papyrus checkout. */
  readerDeployment?: ReaderDeployment;
  /**
   * What the root route (`/`) does. Defaults to `{ kind: "reader" }` (render
   * the publication home page). Set to `{ kind: "redirect", destination }`
   * for a CMS-only deployment whose reader lives elsewhere.
   */
  rootRoute?: RootRouteConfig;
  /** Public URL prefix for newsroom routes. Default `/newsroom`; use `""` on a CMS-only subdomain. */
  newsroomBasePath?: string;
  opsChrome: OpsChrome;
  corpusKey: string;
  steeringConfigPath: string;
  newsroomSectionsConfigPath: string;
  analysisProfilesPath: string;
  publicationName: string;
  components?: SiteBrandComponents;
  demoEdition?: SiteBrandDemoEdition;
};

const SERIF_TEXT_FONT = 'Georgia, "Times New Roman", serif';

const REFERENCE_SITE_BRANDS: Record<SiteBrandId, SiteBrand> = {
  papyrus: {
    id: "papyrus",
    appTitle: "Papyrus",
    appDescription: "A Pretext-powered responsive newspaper layout lab.",
    mastheadTitle: "PAPYRUS",
    mastheadSubtitle: "Inside Papyrus",
    backToHomeLabel: "Back to Papyrus",
    articleTitleSuffix: "Papyrus",
    placeholderByline: "Papyrus",
    defaultPresentation: "newsprint",
    textFont: SERIF_TEXT_FONT,
    mastheadWordSplit: false,
    mastheadDateFormat: "raw",
    mastheadSource: "edition",
    sectionLinkStrategy: "route",
    themePack: "papyrus",
    themeTokens: DEFAULT_THEME_PACK_TOKENS,
    renderer: { kind: "pretext" },
    hosting: { kind: "amplify-ssr" },
    opsChrome: "app",
    corpusKey: "threat-intelligence",
    steeringConfigPath: "corpora/papyrus-steering.yml",
    newsroomSectionsConfigPath: "corpora/papyrus-newsroom-sections.yml",
    analysisProfilesPath: "corpora/papyrus-analysis-profiles.yml",
    publicationName: "Anthus Threat Intelligence",
  },
};

/**
 * The Papyrus reference brand plus whatever the publication registered in its
 * own `papyrus.config.ts` (resolved through the `papyrus-site` alias).
 */
const SITE_BRANDS: Record<SiteBrandId, SiteBrand> = {
  ...REFERENCE_SITE_BRANDS,
  ...Object.fromEntries((papyrusSite.brands ?? []).map((brand) => [brand.id, brand])),
};

export function normalizeSiteBrandId(value: string | undefined | null): SiteBrandId | null {
  if (!value) return null;
  const trimmed = value.trim();
  return Object.prototype.hasOwnProperty.call(SITE_BRANDS, trimmed) ? trimmed : null;
}

function unknownBrandError(value: string): Error {
  return new Error(`Unknown brand '${value}'. Registered: ${Object.keys(SITE_BRANDS).join(", ")}`);
}

export function resolveSiteBrandId(
  raw: string | undefined | null = process.env.NEXT_PUBLIC_PAPYRUS_SITE_BRAND ?? process.env.PAPYRUS_SITE_BRAND,
): SiteBrandId {
  const requested = raw?.trim();
  if (requested) {
    const normalized = normalizeSiteBrandId(requested);
    if (normalized === null) throw unknownBrandError(requested);
    return normalized;
  }
  const fallback = papyrusSite.defaultBrand ?? "papyrus";
  const normalizedFallback = normalizeSiteBrandId(fallback);
  if (normalizedFallback === null) throw unknownBrandError(fallback);
  return normalizedFallback;
}

export function getSiteBrand(id: SiteBrandId = resolveSiteBrandId()): SiteBrand {
  const brand = Object.prototype.hasOwnProperty.call(SITE_BRANDS, id) ? SITE_BRANDS[id] : undefined;
  if (!brand) throw unknownBrandError(id);
  return brand;
}

export const SITE_BRAND = getSiteBrand();

/** Root-route config for a brand, defaulting to `{ kind: "reader" }`. */
export function getRootRoute(brand: SiteBrand = SITE_BRAND): RootRouteConfig {
  return brand.rootRoute ?? { kind: "reader" };
}

export const rootRoute = getRootRoute();

export function enforcePresentation(presentation: EditionPresentationFormat): EditionPresentationFormat {
  return SITE_BRAND.forcedPresentation ?? presentation;
}

export function getPresentationChoices(brand: SiteBrand = SITE_BRAND): EditionPresentationFormat[] {
  return brand.forcedPresentation
    ? [brand.forcedPresentation]
    : ["newsprint", "blog", "magazine"];
}

export function getForcedPresentation(): EditionPresentationFormat | undefined {
  return SITE_BRAND.forcedPresentation;
}

export function getDefaultPretextLayout(): EditionPresentationFormat {
  return SITE_BRAND.defaultPresentation;
}

export function getRendererKind(): RendererConfig["kind"] {
  return SITE_BRAND.renderer.kind;
}
