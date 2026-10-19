import { isLocalPreviewEnabled } from "./local-preview";
import { areEditionsEnabled } from "./site-env";
import type { ComponentType } from "react";
import type { EditionPresentationFormat } from "./content-types";
import type { Article, ArticleVideoAsset } from "./articles";
import type { BlogPageBackgroundProps } from "../components/blog-page-background";
import type { SiteBrandFont } from "./brand-fonts";
import type { PictogramFigureProps } from "../components/pictogram-figure";
import papyrusSite from "papyrus-site";
import { DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS, type ContentItemStageDefinition } from "./content-item-lifecycle";
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
  /** The mark shown at the top of the newsroom CMS sidebar in place of the app title. */
  NewsroomLogo?: ComponentType<{ className?: string }>;
  PictogramFigure?: ComponentType<PictogramFigureProps>;
  BlogPageBackground?: ComponentType<BlogPageBackgroundProps>;
};

/**
 * One line of a brand's header tagline: an emphasized lead and a plain tail,
 * e.g. `{ emphasis: "Practical advice", tail: "for staying secure" }`.
 */
export type SiteBrandTaglineLine = {
  emphasis: string;
  tail: string;
};

/**
 * Blog presentation layout. `"classic"` (the default) is the original blog
 * layout. `"rhythm"` snaps every height and gap to the vertical rhythm grid,
 * floats featured images on the grid, draws rhythm rules between items, adds
 * the eyebrow/tagline header and the rhythm overlay hotkey (Ctrl+=).
 */
export type SiteBrandBlogLayout = "classic" | "rhythm";

/** Default scenario content a brand supplies for the layout lab. */
export type SiteBrandDemoEdition = {
  title: string;
  editionDate: string;
  description: string;
  articles: Article[];
  suppressNewsDeskAppendix?: boolean;
  editionVideo?: ArticleVideoAsset;
};

/**
 * Video slot: how a publication supplies its own VideoML scene components.
 * Paths are relative to the publication root.
 */
export type SiteBrandVideo = {
  /** TSX module that registers the brand's `@videoml` scene components via `window.Babulus.registerComponent`. */
  bundleEntry: string;
  /** DSL element aliases for the browser preview, e.g. `{ "quote-card": "acme-quote-card" }`. */
  sceneComponents?: Record<string, string>;
  rhythm?: Record<string, unknown>;
};

/**
 * The publication's name for its one content item. A content item keeps one
 * identity and one lifecycle from idea through research, reporting,
 * copywriting and publication; only the word editors see changes per
 * publication (for example Story, Article or Post).
 */
export type ContentItemName = {
  singular: string;
  plural: string;
};

export const DEFAULT_CONTENT_ITEM_NAME: ContentItemName = { singular: "Story", plural: "Stories" };

/** Browser-tab icon files under `public/`, as site-root paths. The dark variant defaults to the light one. */
export type SiteBrandIcons = { light: string; dark?: string; appleTouch?: string };

export const DEFAULT_SITE_BRAND_ICONS: Required<Pick<SiteBrandIcons, "light" | "dark">> & { fallback: string } = { light: "/icon-light.png", dark: "/icon-dark.png", fallback: "/icon.png" };

export type SiteBrand = {
  id: SiteBrandId;
  /** The browser-tab icon. Omit to use the Papyrus plant. */
  icons?: SiteBrandIcons;
  appTitle: string;
  appDescription: string;
  mastheadTitle: string;
  mastheadSubtitle: string;
  mastheadTagline?: string;
  /** Rhythm blog layout only: small line above the masthead title, e.g. "Acme Research". The first word is emphasized. */
  mastheadEyebrow?: string;
  /** Rhythm blog layout only: structured tagline; `mastheadTagline` stays the plain-text fallback. */
  mastheadTaglineLines?: SiteBrandTaglineLine[];
  backToHomeLabel: string;
  articleTitleSuffix: string;
  /** Defaults to Story / Stories, the newsroom term. */
  contentItemName?: ContentItemName;
  /** The lifecycle stages in board order, last one being publication. Defaults to the standard newsroom lifecycle. */
  contentItemStages?: readonly ContentItemStageDefinition[];
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
  /** Public URL prefix for the Pretext reader (home, editions, articles, archive, settings). Default `""`; e.g. `/information`. */
  readerBasePath?: string;
  opsChrome: OpsChrome;
  /** Opt-in CMS viewport layout; independent of the public reader renderer/theme. */
  newsroomLayout?: "organizer";
  corpusKey: string;
  steeringConfigPath: string;
  newsroomSectionsConfigPath: string;
  analysisProfilesPath: string;
  publicationName: string;
  components?: SiteBrandComponents;
  /**
   * Video player chrome. `"native"` (default) is the browser's controls;
   * `"framed"` wraps the media in `.article-video__media` and renders a
   * "Play Video" button with a seek bar (`.article-video__cta*`), styled by the publication CSS.
   */
  videoPlayer?: "native" | "framed";
  /** Blog presentation layout. Default `"classic"`. See `SiteBrandBlogLayout`. */
  blogLayout?: SiteBrandBlogLayout;
  /**
   * Brand font slot: families the root layout loads (Google Fonts stylesheet
   * or self-hosted files) and exposes as CSS custom properties. See
   * `lib/brand-fonts.ts` and docs/brand-slots.md.
   */
  fonts?: SiteBrandFont[];
  demoEdition?: SiteBrandDemoEdition;
  video?: SiteBrandVideo;
  /**
   * Editions are an optional setting, off unless `{ enabled: true }`. When off the
   * publication is a plain stream of items: no edition date routes, archive or masthead date.
   */
  editions?: { enabled: boolean };
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
const REGISTERED_SITE_BRANDS: Record<SiteBrandId, SiteBrand> = {
  ...REFERENCE_SITE_BRANDS,
  ...Object.fromEntries((papyrusSite.brands ?? []).map((brand) => [brand.id, brand])),
};

const SITE_BRANDS: Record<SiteBrandId, SiteBrand> = isLocalPreviewEnabled()
  ? Object.fromEntries(
      Object.entries(REGISTERED_SITE_BRANDS).map(([id, brand]) => [id, { ...brand, newsroomLayout: "organizer" as const }]),
    )
  : REGISTERED_SITE_BRANDS;

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

export function getContentItemName(brand: SiteBrand = SITE_BRAND): ContentItemName {
  return brand.contentItemName ?? DEFAULT_CONTENT_ITEM_NAME;
}

export function getContentItemStageDefinitions(brand: SiteBrand = SITE_BRAND): readonly ContentItemStageDefinition[] {
  return brand.contentItemStages?.length ? brand.contentItemStages : DEFAULT_CONTENT_ITEM_STAGE_DEFINITIONS;
}

/** Root-route config for a brand, defaulting to `{ kind: "reader" }`. */
export function getRootRoute(brand: SiteBrand = SITE_BRAND): RootRouteConfig {
  return brand.rootRoute ?? { kind: "reader" };
}

export const rootRoute = getRootRoute();

/** The brand setting wins when present; otherwise the PAPYRUS_EDITIONS_ENABLED switch decides. */
export function editionsEnabled(brand: Pick<SiteBrand, "editions"> = SITE_BRAND): boolean {
  return brand.editions?.enabled ?? areEditionsEnabled();
}

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
