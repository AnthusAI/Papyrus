import type { Article, ArticleVideoAsset } from "../../lib/articles";
import type { SiteBrand } from "../../lib/site-brand";
import { DEFAULT_THEME_PACK_TOKENS } from "../../lib/site-stack";
import { BlogPageBackground } from "./blog-defense/page-background";
import { PictogramFigure } from "./pictograms/figure";
import seedContent from "./seed/seed-edition-content.json";

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
  defaultPresentation: "blog",
  forcedPresentation: "blog",
  textFont: 'system-ui, -apple-system, "Segoe UI", "Helvetica Neue", Arial, sans-serif',
  footerTitle: "ANTHUS THREAT INTELLIGENCE",
  footerSubtitleOverride: "",
  mastheadWordSplit: true,
  mastheadDateFormat: "formatted",
  mastheadSource: "brand",
  sectionLinkStrategy: "anchor",
  defaultVideoCredit: "Anthus Threat Intelligence video",
  themePack: "threat-intelligence",
  themeTokens: {
    ...DEFAULT_THEME_PACK_TOKENS,
    paper: "#f5f0e6",
    moss: "#1c1917",
    ochre: "#ea580c",
    ink: "#44403c",
  },
  renderer: { kind: "pretext" },
  hosting: { kind: "amplify-ssr" },
  opsChrome: "app",
  corpusKey: "threat-intelligence",
  steeringConfigPath: "corpora/papyrus-steering.yml",
  newsroomSectionsConfigPath: "corpora/papyrus-newsroom-sections.yml",
  analysisProfilesPath: "corpora/papyrus-analysis-profiles.yml",
  publicationName: "Anthus Threat Intelligence",
  components: { PictogramFigure, BlogPageBackground },
  video: { bundleEntry: "publications/threat_intelligence/videoml/browser-bundle.tsx" },
  demoEdition: {
    title: seedContent.title,
    editionDate: seedContent.publishDate,
    description: seedContent.description,
    articles: seedContent.articles as Article[],
    suppressNewsDeskAppendix: seedContent.suppressNewsDeskAppendix === true,
    editionVideo: seedContent.video as ArticleVideoAsset | undefined,
  },
};
