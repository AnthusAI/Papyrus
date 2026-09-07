import type { EditionPresentationFormat } from "./content-types";
import { threatIntelligenceBrand } from "../publications/threat_intelligence/brand";
import { pilobolUsBrand } from "../publications/pilobol_us/brand";
import {
  DEFAULT_THEME_PACK_TOKENS,
  type HostingConfig,
  type OpsChrome,
  type RendererConfig,
  type ThemePackId,
  type ThemePackTokens,
} from "./site-stack";

export type SiteBrandId = "papyrus" | "threat-intelligence" | "pilobol-us";

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
  opsChrome: OpsChrome;
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
    defaultPresentation: "newspaper",
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
  },
  "threat-intelligence": threatIntelligenceBrand,
  "pilobol-us": pilobolUsBrand,
};

export function normalizeSiteBrandId(value: string | undefined | null): SiteBrandId | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase().replace(/[._]/g, "-");
  if (!normalized) return null;
  if (normalized === "papyrus") return "papyrus";
  if (normalized === "threat-intelligence" || normalized === "threat-intel" || normalized === "anthus") {
    return "threat-intelligence";
  }
  if (normalized === "pilobol-us" || normalized === "pilobolus") {
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

export function enforcePresentation(presentation: EditionPresentationFormat): EditionPresentationFormat {
  return SITE_BRAND.forcedPresentation ?? presentation;
}

export function getPresentationChoices(brand: SiteBrand = SITE_BRAND): EditionPresentationFormat[] {
  return brand.forcedPresentation
    ? [brand.forcedPresentation]
    : ["newspaper", "blog", "magazine"];
}
