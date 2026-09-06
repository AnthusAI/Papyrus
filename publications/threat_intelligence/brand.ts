import type { SiteBrand } from "../../lib/site-brand";
import { buildDefaultEmptyEditionLayoutPlan } from "../../lib/empty-edition-layout-plan";

export const threatIntelligenceBrand: SiteBrand = {
  id: "threat-intelligence",
  appTitle: "Threat Intelligence",
  appDescription: "ANTHUS THREAT INTELLIGENCE from Anthus AI Solutions.",
  mastheadTitle: "THREAT INTELLIGENCE",
  mastheadSubtitle: "from Anthus AI Solutions",
  mastheadTagline: "Practical advice for staying secure as the threat landscape shifts.",
  backToHomeLabel: "Back to Threat Intelligence",
  articleTitleSuffix: "Threat Intelligence",
  placeholderByline: "Anthus AI Solutions",
  rendererConfig: {
    kind: "pretext",
    layout: "blog",
    layoutPlan: buildDefaultEmptyEditionLayoutPlan(),
  },
  textFont: 'system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
  footerTitle: "ANTHUS THREAT INTELLIGENCE",
  footerSubtitleOverride: "",
  mastheadWordSplit: true,
  mastheadDateFormat: "formatted",
  mastheadSource: "brand",
  sectionLinkStrategy: "anchor",
  defaultVideoCredit: "Anthus Threat Intelligence video",
};
