import type { SiteBrand } from "../../lib/site-brand";

export const pilobolUsBrand: SiteBrand = {
  id: "pilobol-us",
  appTitle: "Pilobol.us",
  appDescription: "Pilobol.us — Markus static publication.",
  mastheadTitle: "PILOBOL.US",
  mastheadSubtitle: "pilobol.us",
  backToHomeLabel: "Back to Pilobol.us",
  articleTitleSuffix: "Pilobol.us",
  placeholderByline: "Pilobol.us",
  rendererConfig: {
    kind: "markus",
    theme: "hackerman",
  },
  textFont: 'system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
  mastheadWordSplit: false,
  mastheadDateFormat: "formatted",
  mastheadSource: "brand",
  sectionLinkStrategy: "route",
};
