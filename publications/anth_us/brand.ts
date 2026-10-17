import type { SiteBrand } from "../../lib/site-brand";
import { ANTH_US_THEME_PACK_TOKENS } from "../../lib/site-stack";

/**
 * Site definition for the Anth.us publication on Papyrus.
 *
 * This is the **site**: masthead, theme pack, corpus wiring, deployment
 * metadata. It is a sibling of `publications/anthus/`, which is the
 * **editorial identity** (`style-profile.yml`, `editorial-rewrite-skill.yml`,
 * `reference-samples/`) and is not touched by this file.
 *
 * Every string below is read off the live Gatsby site at `AnthusAI/Anth.us`:
 * `gatsby-config.mjs` `siteMetadata` for the title/description/author,
 * `src/components/header.js` for the wordmark, `gatsby-plugin-manifest` for
 * "Anth.us AI Solutions", and `src/components/seo.js` for the
 * `"<page> | Anthus"` title pattern.
 */
export const anthUsBrand: SiteBrand = {
  id: "anth-us",
  appTitle: "Anthus",
  appDescription:
    "Anthus builds and operates self-aligning AI systems — custom models, agent harnesses, and evaluation loops with a human in the loop, grounded in 14 years of production operations.",
  // The live header renders the bare word "Anthus" (Jersey 25, weight 900),
  // not a dotted domain wordmark, so this is not "ANTH.US".
  mastheadTitle: "Anthus",
  mastheadSubtitle: "AI Solutions",
  backToHomeLabel: "Back to Anthus",
  articleTitleSuffix: "Anthus",
  placeholderByline: "Ryan Porter",
  // The source site is a blog with a long single-column measure, not a
  // newsprint grid.
  defaultPresentation: "blog",
  textFont:
    '"Montserrat", -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif',
  mastheadWordSplit: false,
  mastheadDateFormat: "formatted",
  mastheadSource: "brand",
  sectionLinkStrategy: "route",
  themePack: "anth-us",
  themeTokens: ANTH_US_THEME_PACK_TOKENS,
  renderer: { kind: "markus" },
  hosting: { kind: "amplify-ssr" },
  readerDeployment: {
    kind: "amplify-static",
    repository: "https://github.com/AnthusAI/Anth.us-Papyrus",
    // `domain` and `amplifyAppId` are deliberately unset.
    //
    // This reader is a **staging** port of a live marketing site. Production
    // `anth.us` stays pointed at the existing Gatsby build until the port has
    // been reviewed, so writing `domain: "anth.us"` here would assert a
    // canonical host this build does not serve. Staging runs on whatever
    // hostname Amplify hands out. No DNS or domain association is configured
    // anywhere in this repo for it.
    //
    // The repository is private while the port is half-finished; the URL above
    // will 404 for anyone without access. That is expected, not a typo.
  },
  rootRoute: { kind: "newsroom" },
  newsroomBasePath: "",
  opsChrome: "app",
  corpusKey: "anth-us",
  // Declared paths. The YAML files themselves are not in the repo yet — see
  // README.md "Not wired yet".
  steeringConfigPath: "corpora/anth-us-steering.yml",
  newsroomSectionsConfigPath: "corpora/anth-us-newsroom-sections.yml",
  analysisProfilesPath: "corpora/anth-us-analysis-profiles.yml",
  publicationName: "Anthus",
};
