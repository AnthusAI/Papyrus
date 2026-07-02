import type { EditionPresentationFormat } from "./content-types";
import { threatIntelligenceBrand } from "../publications/threat_intelligence/brand";

export type SiteBrandId = "papyrus" | "threat-intelligence";

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
  },
  "threat-intelligence": threatIntelligenceBrand,
};

function normalizeSiteBrandId(value: string | undefined | null): SiteBrandId | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "papyrus") return "papyrus";
  if (normalized === "threat-intelligence" || normalized === "threat_intelligence" || normalized === "anthus") {
    return "threat-intelligence";
  }
  return null;
}

function resolveSiteBrandId(): SiteBrandId {
  const configured = normalizeSiteBrandId(
    process.env.NEXT_PUBLIC_PAPYRUS_SITE_BRAND
      ?? process.env.PAPYRUS_SITE_BRAND,
  );
  return configured ?? "papyrus";
}

export const SITE_BRAND = SITE_BRANDS[resolveSiteBrandId()];

export function enforcePresentation(presentation: EditionPresentationFormat): EditionPresentationFormat {
  return SITE_BRAND.forcedPresentation ?? presentation;
}

export function getPresentationChoices(): EditionPresentationFormat[] {
  return SITE_BRAND.forcedPresentation
    ? [SITE_BRAND.forcedPresentation]
    : ["newspaper", "blog", "magazine"];
}
