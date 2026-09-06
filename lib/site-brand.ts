import type { PretextLayout, RendererConfig } from "./renderer-config";
import { buildDefaultEmptyEditionLayoutPlan } from "./empty-edition-layout-plan";
import { threatIntelligenceBrand } from "../publications/threat_intelligence/brand";
import { pilobolUsBrand } from "../publications/pilobol_us/brand";
import { PRETEXT_LAYOUTS } from "../renderers/pretext/layouts";

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
  rendererConfig: RendererConfig;
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

const DEFAULT_PRETEXT_LAYOUT_PLAN = buildDefaultEmptyEditionLayoutPlan();

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
    rendererConfig: {
      kind: "pretext",
      layout: "newsprint",
      layoutPlan: DEFAULT_PRETEXT_LAYOUT_PLAN,
    },
    textFont: SERIF_TEXT_FONT,
    mastheadWordSplit: false,
    mastheadDateFormat: "raw",
    mastheadSource: "edition",
    sectionLinkStrategy: "route",
  },
  "threat-intelligence": threatIntelligenceBrand,
  "pilobol-us": pilobolUsBrand,
};

function normalizeSiteBrandId(value: string | undefined | null): SiteBrandId | null {
  if (!value) return null;
  const normalized = value.trim().toLowerCase();
  if (!normalized) return null;
  if (normalized === "papyrus") return "papyrus";
  if (normalized === "threat-intelligence" || normalized === "threat_intelligence" || normalized === "anthus") {
    return "threat-intelligence";
  }
  if (normalized === "pilobol-us" || normalized === "pilobol_us" || normalized === "pilobol") {
    return "pilobol-us";
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

export function getDefaultPretextLayout(): PretextLayout {
  const config = SITE_BRAND.rendererConfig;
  if (config.kind !== "pretext") {
    throw new Error(`Site brand "${SITE_BRAND.id}" does not define a Pretext layout.`);
  }
  return config.layout;
}

export function getPresentationChoices(): PretextLayout[] {
  if (SITE_BRAND.rendererConfig.kind !== "pretext") return [];
  if (SITE_BRAND.id === "threat-intelligence") return ["blog"];
  return [...PRETEXT_LAYOUTS];
}

export function getForcedPresentation(): PretextLayout | undefined {
  const choices = getPresentationChoices();
  return choices.length === 1 ? choices[0] : undefined;
}

export function enforcePresentation(presentation: PretextLayout): PretextLayout {
  const forced = getForcedPresentation();
  if (forced) return forced;
  const choices = getPresentationChoices();
  if (choices.includes(presentation)) return presentation;
  return getDefaultPretextLayout();
}

export function getRendererKind(): RendererConfig["kind"] {
  return SITE_BRAND.rendererConfig.kind;
}
