import type { EditionPresentationFormat } from "./content-types";
import { threatIntelligenceBrand } from "../publications/threat_intelligence/brand";
import { pilobolUsBrand } from "../publications/pilobol_us/brand";
import { anthUsBrand } from "../publications/anth_us/brand";
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

export type SiteBrandId = "papyrus" | "threat-intelligence" | "pilobol-us" | "anth-us";

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
};

const SERIF_TEXT_FONT = 'Georgia, "Times New Roman", serif';

const SITE_BRANDS: Record<SiteBrandId, SiteBrand> = {
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
  "threat-intelligence": threatIntelligenceBrand,
  "pilobol-us": pilobolUsBrand,
  "anth-us": anthUsBrand,
};

export function normalizeSiteBrandId(value: string | undefined | null): SiteBrandId | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase().replace(/[._]/g, "-");
  if (!normalized) return null;
  if (normalized === "papyrus") return "papyrus";
  // NOTE: the bare alias `anthus` has resolved to `threat-intelligence` since
  // that brand was added and is kept pointing there so existing
  // PAPYRUS_SITE_BRAND values do not silently change meaning. The Anth.us
  // publication is therefore addressed as `anth-us` / `anth.us` / `anth_us`
  // only. Do not "tidy" this by moving `anthus` across.
  if (normalized === "threat-intelligence" || normalized === "threat-intel" || normalized === "anthus") {
    return "threat-intelligence";
  }
  if (normalized === "anth-us") {
    // `normalized` has already mapped `.` and `_` to `-`, so this covers
    // `anth.us` and `anth_us` too.
    return "anth-us";
  }
  if (
    normalized === "pilobol-us" ||
    normalized === "pilobolus" ||
    normalized === "pilobol_us" ||
    normalized === "pilobol"
  ) {
    return "pilobol-us";
  }
  return null;
}

export function resolveSiteBrandId(
  raw: string | undefined | null = process.env.NEXT_PUBLIC_PAPYRUS_SITE_BRAND ?? process.env.PAPYRUS_SITE_BRAND,
): SiteBrandId {
  return normalizeSiteBrandId(raw) ?? "papyrus";
}

/** Cookie set by middleware when `?brand=` is present (demo without rebuild). */
export function resolveRuntimeSiteBrandId(
  cookieOverride: string | undefined | null = null,
): SiteBrandId {
  return normalizeSiteBrandId(cookieOverride) ?? resolveSiteBrandId();
}

export function getSiteBrand(id: SiteBrandId = resolveSiteBrandId()): SiteBrand {
  return SITE_BRANDS[id];
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
