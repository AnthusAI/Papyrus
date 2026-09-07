import type { SiteBrand } from "../../lib/site-brand";
import { PILOBOL_US_THEME_PACK_TOKENS } from "../../lib/site-stack";

export const pilobolUsBrand: SiteBrand = {
  id: "pilobol-us",
  appTitle: "Pilobol.us",
  appDescription: "Pilobol.us publication on Papyrus.",
  mastheadTitle: "PILOBOL.US",
  mastheadSubtitle: "Field notes",
  backToHomeLabel: "Back to Pilobol.us",
  articleTitleSuffix: "Pilobol.us",
  placeholderByline: "Pilobol.us",
  defaultPresentation: "magazine",
  textFont: 'ui-sans-serif, system-ui, "Plus Jakarta Sans", sans-serif',
  mastheadWordSplit: false,
  mastheadDateFormat: "formatted",
  mastheadSource: "brand",
  sectionLinkStrategy: "route",
  themePack: "pilobol-us",
  themeTokens: PILOBOL_US_THEME_PACK_TOKENS,
  renderer: { kind: "markus" },
  hosting: { kind: "amplify-static" },
  opsChrome: "app",
};
